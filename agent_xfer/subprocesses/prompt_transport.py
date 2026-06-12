from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ARG_MAX_BYTES = 120_000


def prompt_arg_max_bytes() -> int:
    value = os.environ.get("AGENT_XFER_PROMPT_ARG_MAX")
    if not value:
        return DEFAULT_ARG_MAX_BYTES
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_ARG_MAX_BYTES
    return max(parsed, 1)


def _argv_size_bytes(args: list[str]) -> int:
    return sum(len(arg.encode("utf-8")) + 1 for arg in args)


def ensure_prompt_fits_argv(
    prompt: str,
    *,
    provider: str,
    artifact_path: Path | None = None,
    argv: list[str] | None = None,
) -> None:
    limit = prompt_arg_max_bytes()
    prompt_bytes = len(prompt.encode("utf-8"))
    measured_bytes = _argv_size_bytes(argv) if argv is not None else prompt_bytes
    if measured_bytes <= limit:
        return
    hint = f" Prompt artifact: {artifact_path}" if artifact_path else ""
    size = (
        f"{provider} argv is {measured_bytes} bytes (prompt is {prompt_bytes} bytes)"
        if argv is not None
        else f"{provider} prompt is {prompt_bytes} bytes"
    )
    raise RuntimeError(
        f"{size}, above AGENT_XFER_PROMPT_ARG_MAX={limit}; "
        "refusing argv transport before provider-specific stdin/tempfile support is configured."
        f"{hint}"
    )
