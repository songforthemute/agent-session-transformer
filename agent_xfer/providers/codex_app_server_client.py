from __future__ import annotations

import json
import os
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


def app_server_timeout() -> int:
    value = os.environ.get("AGENT_XFER_CODEX_APP_SERVER_TIMEOUT", "30")
    try:
        return max(int(value), 1)
    except ValueError:
        return 30


def app_server_retries() -> int:
    value = os.environ.get("AGENT_XFER_CODEX_APP_SERVER_RETRIES", "0")
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


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


def read_thread_via_app_server(command: str, thread_id: str, cwd: Path, timeout: int | None = None, retries: int | None = None) -> AppServerReadResult:
    args = shlex.split(command)
    if not args:
        raise RuntimeError("Codex app-server command is empty")
    timeout = app_server_timeout() if timeout is None else timeout
    retries = app_server_retries() if retries is None else retries
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "thread/read",
        "params": {"threadId": thread_id, "includeTurns": True, "path": str(cwd)},
    }
    last_error: RuntimeError | None = None
    for attempt in range(retries + 1):
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
            last_error = RuntimeError(f"Codex app-server timed out after {timeout}s on attempt {attempt + 1}")
            continue
        if completed.returncode == 0:
            return AppServerReadResult(payload=_decode_response(completed.stdout), command=args, stderr=completed.stderr.strip())
        last_error = RuntimeError(f"Codex app-server exited {completed.returncode} on attempt {attempt + 1}: {completed.stderr.strip()}")
    assert last_error is not None
    raise last_error
