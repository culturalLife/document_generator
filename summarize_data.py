"""
summarize_data.py — Generic JSON Payload → Markdown Summary
=============================================================
Converts *any* valid JSON payload into a structured markdown string
that is injected into the Mistral system prompt alongside the user's
own instructions.

This module is intentionally schema-agnostic: it knows nothing about
the shape of the incoming JSON. It recursively walks the structure and
produces human-readable markdown using the following rules:

  - Dict keys become headings (depth-limited to h4, then bold labels)
  - Homogeneous lists of dicts become markdown tables
  - Heterogeneous / nested lists become numbered sub-sections
  - Lists of primitives become bulleted lists
  - Scalar values are rendered as **key:** value pairs

Production changes from original (domain-specific) version:
  - All domain-specific keys (framework_name, gates, etc.) removed
  - validate_payload() now only checks for non-empty dict
  - clean_data_summary() delegates to generic recursive converter
  - load_and_summarize() preserved for local testing
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Union

# pyrefly: ignore [missing-import]
import config
# pyrefly: ignore [missing-import]
from logger import get_logger

logger = get_logger(__name__)

# Maximum heading depth before falling back to bold labels
_MAX_HEADING_DEPTH = 4


def validate_payload(data: Any) -> None:
    """
    Validates that the payload is a usable JSON structure.
    Raises ValueError if validation fails.

    Only requirement: must be a non-empty dict (top-level object).
    No schema-specific key checks.
    """
    if not isinstance(data, dict):
        raise ValueError(
            "JSON payload must be a JSON object (dict) at the top level. "
            f"Received type: {type(data).__name__}"
        )
    if len(data) == 0:
        raise ValueError("JSON payload is an empty object. Nothing to summarize.")

    logger.debug(f"Payload validation passed | top-level keys={len(data)}")


def _format_key(key: str) -> str:
    """Converts a snake_case or camelCase key into a readable title."""
    # Replace underscores and hyphens with spaces
    readable = key.replace("_", " ").replace("-", " ")
    # Insert space before uppercase letters in camelCase
    result = []
    for i, ch in enumerate(readable):
        if ch.isupper() and i > 0 and readable[i - 1].islower():
            result.append(" ")
        result.append(ch)
    return "".join(result).strip().title()


def _is_homogeneous_dict_list(items: list) -> bool:
    """
    Returns True if `items` is a non-empty list where every element is a dict
    and all dicts share exactly the same set of keys.
    """
    if not items or not all(isinstance(item, dict) for item in items):
        return False
    first_keys = set(items[0].keys())
    return all(set(item.keys()) == first_keys for item in items)


def _is_simple_dict(d: dict) -> bool:
    """Returns True if all values in the dict are scalars (not dicts or lists)."""
    return all(not isinstance(v, (dict, list)) for v in d.values())


def _render_table(items: List[Dict[str, Any]]) -> List[str]:
    """Renders a list of homogeneous dicts as a markdown table."""
    if not items:
        return []

    headers = list(items[0].keys())
    lines = []

    # Header row
    header_labels = [_format_key(h) for h in headers]
    lines.append("| " + " | ".join(header_labels) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    # Data rows
    for item in items:
        cells = []
        for h in headers:
            val = item.get(h, "")
            if isinstance(val, list):
                cell_text = ", ".join(str(v) for v in val)
            elif val is None:
                cell_text = "—"
            else:
                cell_text = str(val)
            # Escape pipe characters inside table cells
            cell_text = cell_text.replace("|", "\\|")
            # Truncate very long cell values to keep tables readable
            if len(cell_text) > 200:
                cell_text = cell_text[:197] + "..."
            cells.append(cell_text)
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")  # blank line after table
    return lines


def _json_to_markdown_recursive(
    data: Any,
    depth: int = 1,
    parent_key: str = "",
) -> List[str]:
    """
    Recursively converts a JSON-compatible Python object into markdown lines.

    Args:
        data:       The current node (dict, list, or scalar).
        depth:      Current heading depth (1 = h1, 2 = h2, ...).
        parent_key: The key name from the parent dict (used for context).

    Returns:
        A list of markdown-formatted strings (one per line).
    """
    lines: List[str] = []

    if isinstance(data, dict):
        for key, value in data.items():
            label = _format_key(key)

            if isinstance(value, dict):
                if _is_simple_dict(value):
                    # Simple flat dict → render as heading + key-value pairs
                    if depth <= _MAX_HEADING_DEPTH:
                        lines.append(f"{'#' * depth} {label}")
                    else:
                        lines.append(f"**{label}:**")
                    lines.append("")
                    for sub_key, sub_val in value.items():
                        sub_label = _format_key(sub_key)
                        display_val = "—" if sub_val is None else str(sub_val)
                        lines.append(f"- **{sub_label}:** {display_val}")
                    lines.append("")
                else:
                    # Complex nested dict → heading + recurse
                    if depth <= _MAX_HEADING_DEPTH:
                        lines.append(f"{'#' * depth} {label}")
                    else:
                        lines.append(f"**{label}:**")
                    lines.append("")
                    lines.extend(_json_to_markdown_recursive(value, depth + 1, key))

            elif isinstance(value, list):
                if depth <= _MAX_HEADING_DEPTH:
                    lines.append(f"{'#' * depth} {label}")
                else:
                    lines.append(f"**{label}:**")
                lines.append("")

                if not value:
                    lines.append("*(empty list)*")
                    lines.append("")
                elif all(isinstance(item, (str, int, float, bool)) for item in value):
                    # List of primitives → bullet list
                    for item in value:
                        lines.append(f"- {item}")
                    lines.append("")
                elif _is_homogeneous_dict_list(value) and _is_simple_dict(value[0]):
                    # Homogeneous list of flat dicts → table
                    lines.extend(_render_table(value))
                else:
                    # Heterogeneous or nested list → numbered sub-sections
                    for idx, item in enumerate(value, start=1):
                        if isinstance(item, dict):
                            # Try to find a natural title from the item
                            item_title = _extract_title(item, idx)
                            next_depth = min(depth + 1, _MAX_HEADING_DEPTH + 1)
                            if next_depth <= _MAX_HEADING_DEPTH:
                                lines.append(f"{'#' * next_depth} {item_title}")
                            else:
                                lines.append(f"**{item_title}**")
                            lines.append("")
                            lines.extend(
                                _json_to_markdown_recursive(item, next_depth + 1, key)
                            )
                        elif isinstance(item, list):
                            lines.append(f"**Item {idx}:**")
                            lines.extend(
                                _json_to_markdown_recursive(item, depth + 1, key)
                            )
                        else:
                            lines.append(f"- {item}")
                    lines.append("")

            else:
                # Scalar value
                display_val = "—" if value is None else str(value)
                lines.append(f"- **{label}:** {display_val}")

    elif isinstance(data, list):
        if not data:
            lines.append("*(empty list)*")
            lines.append("")
        elif all(isinstance(item, (str, int, float, bool)) for item in data):
            for item in data:
                lines.append(f"- {item}")
            lines.append("")
        elif _is_homogeneous_dict_list(data) and _is_simple_dict(data[0]):
            lines.extend(_render_table(data))
        else:
            for idx, item in enumerate(data, start=1):
                if isinstance(item, dict):
                    item_title = _extract_title(item, idx)
                    lines.append(f"**{item_title}**")
                    lines.append("")
                    lines.extend(
                        _json_to_markdown_recursive(item, depth + 1, parent_key)
                    )
                else:
                    lines.append(f"- {item}")
            lines.append("")
    else:
        # Top-level scalar (unusual but possible)
        lines.append(str(data))
        lines.append("")

    return lines


def _extract_title(item: dict, fallback_index: int) -> str:
    """
    Attempts to extract a human-readable title from a dict item.
    Looks for common title/name/label keys. Falls back to 'Item N'.
    """
    title_keys = [
        "title", "name", "label", "heading", "id",
        "gate_title", "dimension_title", "question_text",
        "section_title", "category", "type",
    ]
    for tk in title_keys:
        if tk in item and item[tk] is not None:
            return str(item[tk])
    # Fallback: use index
    return f"Item {fallback_index}"


def clean_data_summary(data: Dict[str, Any]) -> str:
    """
    Converts any valid JSON payload dict into a structured markdown string.

    This is the public API consumed by api.py. The function signature is
    intentionally preserved from the original domain-specific version
    to avoid breaking changes in the calling code.

    Args:
        data: Parsed JSON dict (any structure).

    Returns:
        A multi-line markdown string ready to be injected as LLM context.

    Raises:
        ValueError: If the payload is not a non-empty dict.
    """
    validate_payload(data)

    lines = _json_to_markdown_recursive(data, depth=1)
    summary = "\n".join(lines)

    logger.debug(f"Data summary generated | chars={len(summary)}")
    return summary


def load_and_summarize() -> str:
    """
    Convenience function: loads data.json from config path and returns summary.
    Used for local testing or when called outside the API context.
    """
    json_path: Path = config.JSON_PAYLOAD_PATH
    if not json_path.exists():
        raise FileNotFoundError(f"JSON payload not found at: {json_path}")

    logger.info(f"Loading JSON payload from {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return clean_data_summary(data)


if __name__ == "__main__":
    # Quick local test: summarize data.json and print to stdout
    print(load_and_summarize())
