from __future__ import annotations

import re
from pathlib import Path

EMPTY_TEXT_MIN_CHARS = 24
TEXT_LIKE = {"text", "srt", "json"}
DEFAULT_REFUSALS = (
    r"i can'?t help",
    r"i cannot help",
    r"i'?m unable to",
    r"не могу помочь",
    r"отказ",
)


def _matches(patterns: tuple[str, ...], text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


def classify(
    *,
    exit_code: int,
    out_path: str | None,
    out_type: str,
    stderr: str,
    timed_out: bool,
    quota_patterns: tuple[str, ...],
    refusal_patterns: tuple[str, ...] = DEFAULT_REFUSALS,
) -> str:
    """Класс исхода. exit 0 сам по себе успехом не считается."""
    if timed_out:
        return "timeout"
    if quota_patterns and _matches(quota_patterns, stderr):
        return "quota"
    if _matches(refusal_patterns, stderr):
        return "refused"
    if exit_code != 0:
        return "crash"
    if out_path is None:
        return "success"
    path = Path(out_path)
    if not path.exists() or path.stat().st_size == 0:
        return "empty"
    if out_type in TEXT_LIKE:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len("".join(content.split())) < EMPTY_TEXT_MIN_CHARS:
            return "empty"
    return "success"
