from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agent_xfer.core.ids import ID_KINDS
from agent_xfer.providers.antigravity import antigravity_home, find_last_conversation_for_cwd
from agent_xfer.providers.claude import claude_config_dir


def _entry(provider: str, ident: str | None, available: bool, reason: str, *, cwd: Path, path: str | None = None) -> dict[str, Any]:
    return {
        "provider": provider,
        "id": ident,
        "id_kind": ID_KINDS[provider],
        "available": available,
        "reason": reason,
        "cwd": str(cwd),
        "path": path,
    }


def _grok_session_entries(cwd: Path) -> list[dict[str, Any]]:
    if shutil.which("grok") is None:
        return []
    try:
        completed = subprocess.run(["grok", "sessions", "--json"], cwd=cwd, text=True, capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        sessions = payload.get("sessions", [])
    else:
        sessions = payload
    results: list[dict[str, Any]] = []
    if not isinstance(sessions, list):
        return results
    for item in sessions:
        if not isinstance(item, dict):
            continue
        ident = item.get("id") or item.get("session_id") or item.get("sessionId")
        if isinstance(ident, str) and ident:
            results.append(_entry("grok", ident, True, "grok sessions --json", cwd=cwd, path=None))
    return results


def _antigravity_brain_entries(cwd: Path) -> list[dict[str, Any]]:
    brain = antigravity_home() / "brain"
    if not brain.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for child in sorted(brain.iterdir()):
        if not child.is_dir():
            continue
        logs = child / ".system_generated" / "logs"
        transcript = logs / "transcript_full.jsonl"
        if not transcript.exists():
            transcript = logs / "transcript.jsonl"
        if transcript.exists():
            results.append(_entry("antigravity", child.name, True, "found Antigravity transcript under brain/", cwd=cwd, path=str(transcript)))
    return results


def discover_sources(cwd: Path, deep: bool = False) -> list[dict[str, Any]]:
    cwd = cwd.resolve()
    results: list[dict[str, Any]] = [
        _entry("fake", "source-1", True, "built-in deterministic fake source", cwd=cwd)
    ]

    grok_cli = shutil.which("grok")
    grok_deep = _grok_session_entries(cwd) if deep else []
    if grok_deep:
        results.extend(grok_deep)
    else:
        results.append(_entry("grok", None, grok_cli is not None, "grok CLI found; provide grok:<session_id> manually" if grok_cli else "grok CLI not found", cwd=cwd))

    codex_payload = os.environ.get("AGENT_XFER_CODEX_THREAD_READ_JSON")
    codex_app_server = os.environ.get("AGENT_XFER_CODEX_APP_SERVER_COMMAND")
    codex_available = bool(codex_payload) or bool(codex_app_server)
    codex_reason = "AGENT_XFER_CODEX_THREAD_READ_JSON is set" if codex_payload else (
        "AGENT_XFER_CODEX_APP_SERVER_COMMAND is set" if codex_app_server else "set AGENT_XFER_CODEX_THREAD_READ_JSON or AGENT_XFER_CODEX_APP_SERVER_COMMAND"
    )
    results.append(
        _entry(
            "codex",
            None,
            codex_available,
            codex_reason,
            cwd=cwd,
            path=codex_payload or codex_app_server,
        )
    )

    ag_home = antigravity_home()
    ag_id, last_conversations = find_last_conversation_for_cwd(cwd)
    results.append(
        _entry(
            "antigravity",
            ag_id,
            ag_id is not None,
            "matched cwd in last_conversations.json" if ag_id else "no cwd match in Antigravity last_conversations.json",
            cwd=cwd,
            path=str(last_conversations),
        )
    )
    if deep:
        known_ag_ids = {item["id"] for item in results if item["provider"] == "antigravity" and item.get("id")}
        for item in _antigravity_brain_entries(cwd):
            if item.get("id") not in known_ag_ids:
                results.append(item)

    claude_transcript = os.environ.get("AGENT_XFER_CLAUDE_TRANSCRIPT")
    claude_available = bool(claude_transcript) or claude_config_dir().exists()
    results.append(
        _entry(
            "claude",
            None,
            claude_available,
            "AGENT_XFER_CLAUDE_TRANSCRIPT is set or Claude config dir exists" if claude_available else "Claude config dir not found",
            cwd=cwd,
            path=claude_transcript,
        )
    )
    return results


def discover_targets(cwd: Path) -> list[dict[str, Any]]:
    cwd = cwd.resolve()
    checks = [
        ("fake", "target-1", True, "built-in deterministic fake target"),
        ("codex", None, shutil.which("codex") is not None, "codex CLI found; provide codex:<thread_id> manually"),
        ("grok", None, shutil.which("grok") is not None, "grok CLI found; provide grok:<session_id> manually"),
        ("antigravity", None, shutil.which("agy") is not None, "agy CLI found; provide antigravity:<conversation_id> manually"),
        ("claude", None, shutil.which("claude") is not None, "claude CLI found; provide claude:<session_id> manually"),
    ]
    results: list[dict[str, Any]] = []
    for provider, ident, available, success_reason in checks:
        results.append(
            _entry(
                provider,
                ident,
                available,
                success_reason if available else f"{provider} target CLI not found",
                cwd=cwd,
            )
        )
    return results
