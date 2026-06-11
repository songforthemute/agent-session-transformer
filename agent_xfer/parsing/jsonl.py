from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def parse_jsonl_lines(lines: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse JSONL lines, returning parsed objects plus non-fatal warnings."""
    objects: list[dict[str, Any]] = []
    warnings: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            warnings.append(f"line {lineno}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(value, dict):
            warnings.append(f"line {lineno}: expected JSON object, got {type(value).__name__}")
            continue
        objects.append(value)
    return objects, warnings
