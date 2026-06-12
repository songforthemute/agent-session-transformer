from __future__ import annotations

import os
import shutil
from pathlib import Path

from agent_xfer.core.models import InspectResult, ProviderCapabilities, ReadSessionResult, SendResult
from agent_xfer.parsing.claude import parse_claude_jsonl
from agent_xfer.subprocesses.prompt_transport import ensure_prompt_fits_argv
from agent_xfer.subprocesses.runner import run_command


def claude_config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude"


def _encoded_project_path(cwd: Path) -> str:
    # Claude Code project directories are path-derived. This fallback matches the
    # commonly observed dash-encoded absolute path and remains secondary to the
    # explicit AGENT_XFER_CLAUDE_TRANSCRIPT override used by tests and scripts.
    return str(cwd.resolve()).replace("/", "-")


def _write_prompt_artifact(path: Path | None, prompt: str) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")


class ClaudeAdapter:
    provider = "claude"
    id_kind = "session_id"
    capabilities = ProviderCapabilities(
        can_read_session=True,
        can_resume_target=True,
        can_send_prompt_to_target=True,
        can_emit_machine_readable_events=True,
        can_locate_local_transcripts=True,
        uses_official_api=True,
        uses_private_or_semiprivate_files=True,
        requires_auth=True,
        requires_local_cli=True,
    )

    def _transcript_path(self, source_id: str, cwd: Path) -> Path:
        override = os.environ.get("AGENT_XFER_CLAUDE_TRANSCRIPT")
        if override:
            return Path(override).expanduser()
        return claude_config_dir() / "projects" / _encoded_project_path(cwd) / f"{source_id}.jsonl"

    def healthcheck(self, cwd: Path) -> dict:
        cli = shutil.which("claude")
        transcript = os.environ.get("AGENT_XFER_CLAUDE_TRANSCRIPT")
        return {
            "provider": self.provider,
            "ok": cli is not None or bool(transcript),
            "cli": cli,
            "transcript": transcript,
            "config_dir": str(claude_config_dir()),
            "cwd": str(cwd),
        }

    def read_session(self, source_id: str, cwd: Path) -> ReadSessionResult:
        path = self._transcript_path(source_id, cwd)
        if not path.exists():
            raise FileNotFoundError(f"Claude transcript not found: {path}")
        text = path.read_text(encoding="utf-8")
        events, warnings = parse_claude_jsonl(text, source_id, cwd)
        if not events:
            warnings.append("Claude transcript produced no normalized events")
        return ReadSessionResult(
            provider=self.provider,
            source_id=source_id,
            id_kind=self.id_kind,
            cwd=str(cwd),
            events=events,
            read_method="claude-jsonl",
            created_at=events[0].created_at if events else None,
            updated_at=events[-1].created_at if events else None,
            raw_artifacts=[{"kind": "claude-jsonl", "path": str(path), "redacted": False}],
            warnings=warnings,
        )

    def inspect(self, source_id: str, cwd: Path) -> InspectResult:
        result = self.read_session(source_id, cwd)
        return InspectResult(
            provider=self.provider,
            source_id=source_id,
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
        args = ["claude", "--resume", target_id, "-p", prompt]
        ensure_prompt_fits_argv(prompt, provider=self.provider, artifact_path=artifact_path, argv=args)
        result = run_command(args, cwd=cwd)
        if result.returncode != 0:
            raise RuntimeError(f"claude resume failed with exit {result.returncode}: {result.stderr.strip()}")
        return SendResult(
            provider=self.provider,
            target_id=target_id,
            sent=True,
            method="claude-resume-p",
            artifact_path=str(artifact_path) if artifact_path else None,
            warnings=[result.stderr.strip()] if result.stderr.strip() else [],
        )
