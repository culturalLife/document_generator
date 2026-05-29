"""
config.py — Central Configuration for docs_gen Pipeline
=========================================================
All tuneable knobs live here. Change values here only; never hardcode in logic files.

INPUT MODE:
  Currently FILE-DRIVEN: the API reads prompt.md and data.json from disk.
  To switch to API-DRIVEN (caller POSTs prompt + payload), set INPUT_MODE = "api"
  and update api.py accordingly.
"""

from pathlib import Path

# ─── Base Directory ────────────────────────────────────────────────────────────
# Absolute path to the VMCompatible folder — all relative paths resolve from here.
BASE_DIR = Path(__file__).parent

# ─── Input Mode ────────────────────────────────────────────────────────────────
# Set to "file" to read prompt.md and data.json from disk.
# Set to "api" to accept prompt and json_payload in the POST request body.
INPUT_MODE: str = "api"

# ─── Model Settings ────────────────────────────────────────────────────────────
# Which Mistral model to use for report generation.
# Options: "mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"
GENERATION_MODEL: str = "mistral-large-latest"

# LLM temperature. 0.0 = deterministic, 1.0 = creative.
TEMPERATURE: float = 0.2

# Number of parallel Mistral API calls to fan out during generation.
# Set to 1 for generic single-call mode (user prompt defines report structure).
# Increase only if report_generator.py is extended with a multi-part split strategy.
MAX_PARALLEL_CALLS: int = 1

# ─── Input Paths (File-Driven Mode) ────────────────────────────────────────────
# The pipeline reads these two files from disk at request time.
# Update these paths when deploying to the VM if directory layout differs.
PROMPT_FILE_PATH: Path = BASE_DIR / "prompt.md"
JSON_PAYLOAD_PATH: Path = BASE_DIR / "data.json"

# ─── Output Settings ───────────────────────────────────────────────────────────
# Directory where generated .docx reports are saved.
REPORTS_OUTPUT_DIR: Path = BASE_DIR / "reports"

# Prefix used in report filenames: <PREFIX>_YYYYMMDD_HHMMSS.docx
REPORT_FILENAME_PREFIX: str = "Generated_Report"

# ─── API Server Settings ───────────────────────────────────────────────────────
# Host and port uvicorn will bind to on the VM.
# 0.0.0.0 makes it reachable from outside the VM (private network).
API_HOST: str = "0.0.0.0"
API_PORT: int = 8000

# ─── Retry Settings ────────────────────────────────────────────────────────────
# How many times to retry a failed Mistral API call before giving up.
MAX_RETRIES: int = 3

# Base backoff in seconds. Actual wait = RETRY_BACKOFF_SECONDS * 2^(attempt-1)
# e.g. attempt 1 → 2s, attempt 2 → 4s, attempt 3 → 8s
RETRY_BACKOFF_SECONDS: float = 2.0

# ─── Logging Settings ──────────────────────────────────────────────────────────
# Log level: "DEBUG", "INFO", "WARNING", "ERROR"
LOG_LEVEL: str = "INFO"

# Rotating log file path. Set to None to disable file logging (console only).
LOG_FILE: Path = BASE_DIR / "logs" / "pipeline.log"

# Max size per log file before rotation (bytes). 5MB default.
LOG_MAX_BYTES: int = 5 * 1024 * 1024

# Number of rotated log backups to keep alongside the current log file.
LOG_BACKUP_COUNT: int = 3

# ─── Prompts & Directives ──────────────────────────────────────────────────────
# The system prompt template for Mistral.
# Use '{data_summary_text}' placeholder where the dynamically summarized JSON data should be injected.
# This template is intentionally domain-agnostic — the user's prompt defines the report domain and structure.
SYSTEM_PROMPT_TEMPLATE: str = (
    "You are a professional report-generation assistant. "
    "You will be given structured data and a user prompt describing the desired report.\n\n"
    "--- DATA CONTEXT ---\n{data_summary_text}\n--- END DATA CONTEXT ---\n\n"
    "MANDATORY OUTPUT REQUIREMENTS (non-negotiable, apply to every report):\n"
    "- Target length: 3000–5000 words minimum. Write as much as the data supports — do NOT truncate.\n"
    "- Every section requested by the user must be fully written out with complete paragraphs.\n"
    "- Each section must contain at minimum 2–4 detailed paragraphs of substantive analysis.\n"
    "- Use markdown tables (with | separators) wherever data comparison, metrics, or structured lists appear.\n"
    "- Do NOT summarise or compress content. If the data is rich, the report must reflect that richness.\n"
    "- If the user prompt specifies sub-sections, write ALL of them in full — never skip or merge.\n"
    "- The final document should be equivalent to a 9–15 page professional consulting report.\n\n"
    "STYLE & FORMATTING DIRECTIVES:\n"
    "1. Your response must be highly professional and well-structured.\n"
    "2. DO NOT use conversational fillers like 'I think', 'Here is the report', or 'Sure, I can help'.\n"
    "3. DO NOT use markdown code blocks (```) or double ticks (``). Render data cleanly.\n"
    "4. Format tabular data using standard markdown tables (with | separators) where required.\n"
    "5. Be assertive, evidence-based, and directive in your language.\n"
    "6. You MUST begin each section with a standard markdown heading (e.g. '## Section Title'). "
    "DO NOT use bold styling '**Heading**' for section titles; always use markdown '##' so they are recognized by the document formatting engine.\n"
    "7. Follow the user's prompt instructions to determine the report structure, sections, and content focus.\n"
    "8. Base all analysis, observations, and recommendations on the data provided in the DATA CONTEXT above. "
    "Do not invent data that is not present.\n"
    "9. Where the data is limited on a topic, explicitly state what is known, what is inferred, and what remains a gap — "
    "do not pad with generic text, but do not leave sections empty either."
)

