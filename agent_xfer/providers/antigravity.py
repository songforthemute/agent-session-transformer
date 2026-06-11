from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent_xfer.core.models import InspectResult, ProviderCapabilities, ReadSessionResult, SendResult
from agent_xfer.parsing.antigravity import parse_antigravity_transcript_jsonl
from agent_xfer.subprocesses.runner import run_command


def _write_prompt_artifact(path: Path | None, prompt: str) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")


def antigravity_home() -> Path:
    override = os.environ.get("AGENT_XFER_ANTIGRAVITY_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".gemini" / "antigravity-cli"


LAST_CONVERSATION_ALIASES = {"last", "cwd", "current"}


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cwd_lookup_keys(cwd: Path) -> list[str]:
    keys: list[str] = []
    for candidate in (cwd, cwd.resolve()):
        value = str(candidate)
        if value not in keys:
            keys.append(value)
    return keys


def find_last_conversation_for_cwd(cwd: Path) -> tuple[str | None, Path]:
    path = antigravity_home() / "cache" / "last_conversations.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return None, path
    for key in _cwd_lookup_keys(cwd):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value, path
    return None, path


def resolve_conversation_id(source_id: str, cwd: Path) -> str:
    if source_id not in LAST_CONVERSATION_ALIASES:
        return source_id
    conversation_id, path = find_last_conversation_for_cwd(cwd)
    if conversation_id:
        return conversation_id
    raise FileNotFoundError(f"Antigravity last conversation alias {source_id!r} could not be resolved from {path}")


class AntigravityAdapter:
    provider = "antigravity"
    id_kind = "conversation_id"
    capabilities = ProviderCapabilities(
        can_read_session=True,
        can_resume_target=True,
        can_send_prompt_to_target=True,
        can_emit_machine_readable_events=True,
        can_locate_local_transcripts=True,
        uses_official_api=False,
        uses_private_or_semiprivate_files=True,
        requires_auth=True,
        requires_local_cli=False,
    )

    def _transcript_path(self, source_id: str) -> Path:
        override = os.environ.get("AGENT_XFER_ANTIGRAVITY_TRANSCRIPT")
        if override:
            return Path(override).expanduser()
        base = antigravity_home() / "brain" / source_id / ".system_generated" / "logs"
        full = base / "transcript_full.jsonl"
        if full.exists():
            return full
        return base / "transcript.jsonl"

    def healthcheck(self, cwd: Path) -> dict:
        home = antigravity_home()
        return {"provider": self.provider, "ok": home.exists(), "home": str(home), "cwd": str(cwd)}

    def read_session(self, source_id: str, cwd: Path) -> ReadSessionResult:
        resolved_source_id = resolve_conversation_id(source_id, cwd)
        path = self._transcript_path(resolved_source_id)
        if not path.exists():
            raise FileNotFoundError(f"Antigravity transcript not found: {path}")
        text = path.read_text(encoding="utf-8")
        events, warnings = parse_antigravity_transcript_jsonl(text, resolved_source_id, cwd)
        if not events:
            warnings.append("Antigravity transcript produced no normalized events")
        return ReadSessionResult(
            provider=self.provider,
            source_id=resolved_source_id,
            id_kind=self.id_kind,
            cwd=str(cwd),
            events=events,
            read_method="antigravity-transcript-jsonl",
            created_at=events[0].created_at if events else None,
            updated_at=events[-1].created_at if events else None,
            raw_artifacts=[{"kind": "antigravity-transcript", "path": str(path), "redacted": False}],
            warnings=warnings,
        )

    def inspect(self, source_id: str, cwd: Path) -> InspectResult:
        result = self.read_session(source_id, cwd)
        return InspectResult(
            provider=self.provider,
            source_id=result.source_id,
            id_kind=self.id_kind,
            cwd=str(cwd),
            can_read=True,
            read_method=result.read_method,
            event_count=len(result.events),
            created_at=result.created_at,
            updated_at=result.updated_at,
            warnings=result.warnings,
        )

    def send_handoff(self, target_id: str, prompt: str, cwd: Path, artifact_path: Path | None = None) -> SendResult:
        _write_prompt_artifact(artifact_path, prompt)
        result = run_command(["agy", "--conversation", target_id, "--print", prompt, "--print-timeout", "30s"], cwd=cwd)
        if result.returncode != 0:
            raise RuntimeError(f"agy conversation print failed with exit {result.returncode}: {result.stderr.strip()}")
        return SendResult(
            provider=self.provider,
            target_id=target_id,
            sent=True,
            method="agy-conversation-print",
            artifact_path=str(artifact_path) if artifact_path else None,
            warnings=[result.stderr.strip()] if result.stderr.strip() else [],
        )
