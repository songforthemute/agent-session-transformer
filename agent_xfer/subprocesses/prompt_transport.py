from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ARG_MAX_CHARS = 120_000


def prompt_arg_max_chars() -> int:
    value = os.environ.get("AGENT_XFER_PROMPT_ARG_MAX")
    if not value:
        return DEFAULT_ARG_MAX_CHARS
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_ARG_MAX_CHARS
    return max(parsed, 1)


def ensure_prompt_fits_argv(prompt: str, *, provider: str, artifact_path: Path | None = None) -> None:
    limit = prompt_arg_max_chars()
    if len(prompt) <= limit:
        return
    hint = f" Prompt artifact: {artifact_path}" if artifact_path else ""
    raise RuntimeError(
        f"{provider} prompt is {len(prompt)} chars, above AGENT_XFER_PROMPT_ARG_MAX={limit}; "
        "refusing argv transport before provider-specific stdin/tempfile support is configured."
        f"{hint}"
    )
