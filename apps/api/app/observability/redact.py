"""Sanitized, bounded summaries for spans. Traces never hold prompts, document text, memory
text, credentials or full payloads: only short one-line summaries and small scalar metadata."""

import re
from typing import Any

SUMMARY_CHARS = 200
METADATA_VALUE_CHARS = 200
METADATA_KEYS = 30
SECRET_KEY = re.compile(
    r"pass(word)?|secret|token|api[_-]?key|authorization|cookie|credential|private", re.I
)
SECRET_VALUE = re.compile(
    r"(bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", re.I
)
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def clip(text: Any, limit: int = SUMMARY_CHARS) -> str | None:
    """One line, control characters removed, secret-looking tokens masked, bounded."""
    if text is None:
        return None
    value = SECRET_VALUE.sub("[redacted]", CONTROL.sub(" ", str(text))).strip()
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def arguments_summary(arguments: dict[str, Any] | None) -> str | None:
    """'key=value, …' for tool arguments, with secret-named keys masked."""
    if not arguments:
        return None
    parts = []
    for key, value in list(arguments.items())[:8]:
        shown = "[redacted]" if SECRET_KEY.search(str(key)) else clip(value, 60)
        parts.append(f"{key}={shown}")
    return clip(", ".join(parts))


def safe_metadata(values: dict[str, Any]) -> dict[str, Any]:
    """Keep scalars and short scalar lists; mask secret-named keys; drop everything else."""
    result: dict[str, Any] = {}
    for key, value in list(values.items())[:METADATA_KEYS]:
        key = str(key)[:60]
        if SECRET_KEY.search(key):
            result[key] = "[redacted]"
        elif value is None or isinstance(value, bool | int | float):
            result[key] = value
        elif isinstance(value, str):
            result[key] = clip(value, METADATA_VALUE_CHARS)
        elif isinstance(value, list | tuple):
            result[key] = [
                item if isinstance(item, bool | int | float) else clip(item, 80)
                for item in list(value)[:10]
            ]
        else:
            result[key] = clip(value, METADATA_VALUE_CHARS)
    return result
