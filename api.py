"""
api.py — Production FastAPI Application
========================================
Entry point for the generic document generation pipeline.

Endpoints:
  GET  /health             → Liveness check for VM/monitoring
  POST /api/generate-docs  → Accepts a single combined_input form field containing
                             the prompt text and a ```json ... ``` fenced block,
                             runs the full pipeline, returns a .docx as download.

Input format for combined_input:
  Your detailed prompt here...

  ```json
  { "key": "value", ... }
  ```

Design decisions:
  - Single-field API: combined_input is the only accepted input method.
  - No frontend served (VM-only, no UI required)
  - No auth (private network VM)
  - Each request gets a short UUID (request_id) threaded through all log lines
  - Errors are sanitized: caller sees clean HTTP messages, full detail in logs
"""

import json
import re as _re
import uuid
import datetime
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

import config  # pyrefly: ignore [missing-import]
from logger import get_logger  # pyrefly: ignore [missing-import]
from summarize_data import clean_data_summary  # pyrefly: ignore [missing-import]
from report_generator import generate_report  # pyrefly: ignore [missing-import]

logger = get_logger("api")

# ─── Combined-Input Parser ──────────────────────────────────────────────────────
#
# Strategy priority (first match wins):
#
#  1. ```json ... ```   — fenced block with explicit "json" language tag
#  2. ``` ... ```       — plain fenced block (no language tag), content is valid JSON
#  3. Explicit delimiter — "---JSON---", "===JSON===", "##JSON##", "--JSON--"
#  4. Raw JSON at end   — prompt text followed by a bare { or [ block at the end
#  5. Raw JSON anywhere — first standalone { } or [ ] block found in the text
#
# In all cases: everything OUTSIDE the detected JSON block becomes the prompt.

# Strategy 1: ```json ... ``` (with language tag)
_FENCE_WITH_TAG_RE = _re.compile(
    r"```json\s*\n(.*?)\n\s*```",
    _re.DOTALL | _re.IGNORECASE,
)

# Strategy 2: ``` ... ``` (no language tag)
_FENCE_NO_TAG_RE = _re.compile(
    r"```\s*\n(.*?)\n\s*```",
    _re.DOTALL,
)

# Strategy 3: explicit text delimiters
_DELIMITER_RE = _re.compile(
    r"(?:---|===|##)JSON(?:---|===|##)\s*\n(.*?)(?:\n(?:---|===|##)END(?:---|===|##)|$)",
    _re.DOTALL | _re.IGNORECASE,
)

# Strategy 4 & 5: bare JSON object or array — greedy match of the outermost braces/brackets
_BARE_JSON_RE = _re.compile(
    r"(\{.*\}|\[.*\])",
    _re.DOTALL,
)


def _try_parse_json(raw: str):
    """Returns parsed JSON or None if invalid."""
    try:
        return json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def _build_prompt(combined: str, match_start: int, match_end: int) -> str:
    """Strips the JSON span from combined and returns the remaining text as the prompt."""
    before = combined[:match_start].rstrip()
    after = combined[match_end:].lstrip()
    parts = [p for p in [before, after] if p]
    return "\n\n".join(parts).strip()


def _extract_prompt_and_json(combined: str, request_id: str = ""):
    """
    Smart multi-strategy extractor. Tries each pattern in priority order and
    uses the first one that yields valid JSON. Everything outside the JSON span
    becomes the prompt text.

    Supported input shapes
    ─────────────────────
    1. Fenced with ```json tag:
           Your prompt...
           ```json
           { ... }
           ```

    2. Fenced with plain ```:
           Your prompt...
           ```
           { ... }
           ```

    3. Explicit delimiter line:
           Your prompt...
           ---JSON---
           { ... }
           ---END---    ← optional closing delimiter

    4. Raw JSON appended at the end:
           Your prompt...
           { "key": "value", ... }

    5. Raw JSON block anywhere in the text (first valid object/array found).

    Returns:
        (prompt_text, json_data)

    Raises:
        HTTPException 400  if no valid JSON can be found or the prompt is empty.
    """
    strategies = [
        ("Strategy 1 [```json fence]",   _FENCE_WITH_TAG_RE),
        ("Strategy 2 [plain ``` fence]",  _FENCE_NO_TAG_RE),
        ("Strategy 3 [---JSON--- delim]", _DELIMITER_RE),
    ]

    # ── Strategies 1-3: regex with a capture group ──────────────────────────────
    for label, pattern in strategies:
        match = pattern.search(combined)
        if match:
            raw = match.group(1).strip()
            parsed = _try_parse_json(raw)
            if parsed is not None:
                prompt_text = _build_prompt(combined, match.start(), match.end())
                if prompt_text:
                    logger.info(
                        f"[{request_id}] {label} matched | "
                        f"prompt={len(prompt_text)} chars, json={len(raw)} chars"
                    )
                    return prompt_text, parsed
                # JSON found but no prompt text — try next strategy
                logger.warning(f"[{request_id}] {label} matched but no prompt text found — trying next.")

    # ── Strategy 4: raw JSON at the END of the text ─────────────────────────────
    # Walk backwards through lines to find where a valid JSON block starts.
    lines = combined.splitlines()
    for start_idx in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[start_idx:]).strip()
        if candidate.startswith(("{", "[")):
            parsed = _try_parse_json(candidate)
            if parsed is not None:
                prompt_text = "\n".join(lines[:start_idx]).strip()
                if prompt_text:
                    logger.info(
                        f"[{request_id}] Strategy 4 [raw JSON at end] matched | "
                        f"prompt={len(prompt_text)} chars, json={len(candidate)} chars"
                    )
                    return prompt_text, parsed

    # ── Strategy 5: first raw JSON block anywhere ────────────────────────────────
    for match in _BARE_JSON_RE.finditer(combined):
        raw = match.group(1).strip()
        parsed = _try_parse_json(raw)
        if parsed is not None:
            prompt_text = _build_prompt(combined, match.start(), match.end())
            if prompt_text:
                logger.info(
                    f"[{request_id}] Strategy 5 [bare JSON block] matched | "
                    f"prompt={len(prompt_text)} chars, json={len(raw)} chars"
                )
                return prompt_text, parsed

    # ── All strategies exhausted ─────────────────────────────────────────────────
    logger.error(f"[{request_id}] No valid JSON could be extracted from combined_input.")
    raise HTTPException(
        status_code=400,
        detail=(
            "Could not extract a valid JSON block from combined_input. "
            "Supported formats:\n"
            "  1. Wrap JSON in ```json ... ``` (recommended)\n"
            "  2. Wrap JSON in plain ``` ... ```\n"
            "  3. Use ---JSON--- delimiter before the JSON block\n"
            "  4. Append raw JSON { } or [ ] after your prompt text"
        ),
    )


# ─── App Initialization ─────────────────────────────────────────────────────────
app = FastAPI(
    title="Generic Docs Gen API",
    version="3.0.0",
    description=(
        "Schema-agnostic document generation pipeline. "
        "Send a single combined_input field containing your prompt and a ```json ... ``` block. "
        "The API extracts both, runs Mistral generation, and returns a formatted .docx."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Startup Validation ─────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_checks():
    """Ensures the output directory exists and the API key is reachable."""
    config.REPORTS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"[STARTUP] Reports directory ready: {config.REPORTS_OUTPUT_DIR}")
    logger.info(
        f"[STARTUP] Server ready | model={config.GENERATION_MODEL} "
        f"| parallel_calls={config.MAX_PARALLEL_CALLS}"
    )


# ─── Health Check ───────────────────────────────────────────────────────────────
@app.get("/health", summary="Liveness check")
async def health():
    """Returns server status. Hit this to confirm the service is alive."""
    return {
        "status": "ok",
        "version": "3.0.0",
        "model": config.GENERATION_MODEL,
        "parallel_calls": config.MAX_PARALLEL_CALLS,
    }


# ─── Main Endpoint ──────────────────────────────────────────────────────────────
@app.post(
    "/api/generate-docs",
    summary="Generate a .docx report from combined prompt + JSON input",
    response_description="Returns a .docx report as a file download",
)
async def generate_docs(
    request: Request,
    combined_input: str = Form(..., description=(
        "A single text block containing:\n"
        "1. Your detailed prompt (plain text)\n"
        "2. Your JSON data wrapped in a ```json ... ``` fence\n\n"
        "Example:\n"
        "  Generate a quarterly sales report with trends.\n\n"
        "  ```json\n"
        "  { \"sales\": 1000, \"region\": \"North\" }\n"
        "  ```"
    )),
):
    """
    Triggers the full document generation pipeline:
      1. Extracts prompt text and JSON from combined_input
      2. Converts JSON data into a generic markdown summary
      3. Sends prompt + summary to Mistral for report generation
      4. Assembles a professionally formatted .docx
      5. Returns it as a downloadable file
    """
    request_id = str(uuid.uuid4())[:8].upper()
    t_start = datetime.datetime.now()
    logger.info(f"[{request_id}] ── New request received from {request.client.host} ──")

    try:
        # ── Step 1: Extract prompt and JSON from combined_input ──────────────────
        logger.info(f"[{request_id}] Parsing combined_input...")
        prompt_text, json_data = _extract_prompt_and_json(combined_input, request_id=request_id)

        # ── Step 2: Summarize JSON → markdown ───────────────────────────────────
        logger.info(f"[{request_id}] Summarizing JSON payload...")
        try:
            data_summary_text = clean_data_summary(json_data)
        except ValueError as e:
            logger.error(f"[{request_id}] Payload validation failed: {e}")
            raise HTTPException(status_code=400, detail=f"Data payload error: {e}")

        # ── Step 3: Generate report ──────────────────────────────────────────────
        timestamp = t_start.strftime("%Y%m%d_%H%M%S")
        filename = f"{config.REPORT_FILENAME_PREFIX}_{timestamp}.docx"
        output_path = config.REPORTS_OUTPUT_DIR / filename

        logger.info(f"[{request_id}] Starting pipeline → output: {filename}")
        try:
            generate_report(
                prompt_text=prompt_text,
                data_summary_text=data_summary_text,
                output_path=str(output_path),
                request_id=request_id,
            )
        except RuntimeError as e:
            logger.error(f"[{request_id}] Pipeline failure: {e}")
            raise HTTPException(
                status_code=503,
                detail="Report generation failed — upstream API error. Check server logs.",
            )
        except Exception as e:
            logger.exception(f"[{request_id}] Unexpected pipeline error: {e}")
            raise HTTPException(
                status_code=500,
                detail="Internal server error during report generation. Check server logs.",
            )

        # ── Step 4: Return as downloadable file ──────────────────────────────────
        elapsed = (datetime.datetime.now() - t_start).total_seconds()
        logger.info(f"[{request_id}] ── Request completed in {elapsed:.1f}s → {filename} ──")

        return FileResponse(
            path=str(output_path),
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    except HTTPException:
        raise
    except Exception as e:
        elapsed = (datetime.datetime.now() - t_start).total_seconds()
        logger.exception(f"[{request_id}] Unhandled exception after {elapsed:.1f}s: {e}")
        raise HTTPException(status_code=500, detail="Unexpected server error. Check server logs.")


# ─── Custom Error Responses ─────────────────────────────────────────────────────
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": "Endpoint not found", "available_endpoints": ["GET /health", "POST /api/generate-docs"]},
    )
