from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppServerReadResult:
    payload: dict[str, Any]
    command: list[str]
    stderr: str


def _decode_response(stdout: str) -> dict[str, Any]:
    last_error: json.JSONDecodeError | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(obj, dict) and (obj.get("jsonrpc") == "2.0" or "result" in obj or "error" in obj):
            if obj.get("error"):
                raise RuntimeError(f"Codex app-server returned error: {obj['error']}")
            result = obj.get("result", obj)
            if isinstance(result, dict):
                return result
            raise RuntimeError("Codex app-server result was not a JSON object")
    if last_error:
        raise RuntimeError(f"Codex app-server returned no parseable JSON response: {last_error.msg}")
    raise RuntimeError("Codex app-server returned no JSON response")


def read_thread_via_app_server(command: str, thread_id: str, cwd: Path, timeout: int = 30) -> AppServerReadResult:
    args = shlex.split(command)
    if not args:
        raise RuntimeError("Codex app-server command is empty")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "thread/read",
        "params": {"threadId": thread_id, "includeTurns": True, "path": str(cwd)},
    }
    try:
        completed = subprocess.run(
            args,
            input=json.dumps(request, ensure_ascii=False) + "\n",
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Codex app-server command not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Codex app-server timed out after {timeout}s") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Codex app-server exited {completed.returncode}: {completed.stderr.strip()}")
    return AppServerReadResult(payload=_decode_response(completed.stdout), command=args, stderr=completed.stderr.strip())
