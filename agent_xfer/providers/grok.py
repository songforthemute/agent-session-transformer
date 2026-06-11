from __future__ import annotations

import os
import shutil
from pathlib import Path

from agent_xfer.core.models import InspectResult, ProviderCapabilities, ReadSessionResult, SendResult
from agent_xfer.parsing.grok_trace import parse_grok_trace_archive
from agent_xfer.parsing.markdown_transcript import parse_grok_export_markdown
from agent_xfer.subprocesses.runner import run_command


def _write_prompt_artifact(path: Path | None, prompt: str) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")


class GrokAdapter:
    provider = "grok"
    id_kind = "session_id"
    capabilities = ProviderCapabilities(
        can_read_session=True,
        can_resume_target=True,
        can_send_prompt_to_target=True,
        can_emit_machine_readable_events=False,
        can_locate_local_transcripts=False,
        uses_official_api=False,
        uses_private_or_semiprivate_files=False,
        requires_auth=True,
        requires_local_cli=True,
    )

    def healthcheck(self, cwd: Path) -> dict:
        path = shutil.which("grok")
        return {"provider": self.provider, "ok": path is not None, "cli": path, "cwd": str(cwd)}

    def read_session(self, source_id: str, cwd: Path) -> ReadSessionResult:
        trace_archive = os.environ.get("AGENT_XFER_GROK_TRACE_ARCHIVE")
        if trace_archive:
            path = Path(trace_archive).expanduser()
            events, warnings = parse_grok_trace_archive(path, source_id, cwd)
            if not events:
                warnings.append("grok trace archive returned no parseable events")
            return ReadSessionResult(
                provider=self.provider,
                source_id=source_id,
                id_kind=self.id_kind,
                cwd=str(cwd),
                events=events,
                read_method="grok-trace-archive",
                created_at=events[0].created_at if events else None,
                updated_at=events[-1].created_at if events else None,
                raw_artifacts=[{"kind": "grok-trace", "path": str(path), "redacted": False}],
                warnings=warnings,
            )

        result = run_command(["grok", "export", source_id], cwd=cwd)
        warnings: list[str] = []
        if result.returncode != 0:
            raise RuntimeError(f"grok export failed with exit {result.returncode}: {result.stderr.strip()}")
        events = parse_grok_export_markdown(result.stdout, source_id, cwd)
        if not events:
            warnings.append("grok export returned no parseable User/Assistant turns")
        return ReadSessionResult(
            provider=self.provider,
            source_id=source_id,
            id_kind=self.id_kind,
            cwd=str(cwd),
            events=events,
            read_method="grok-export",
            created_at=events[0].created_at if events else None,
            updated_at=events[-1].created_at if events else None,
            raw_artifacts=[{"kind": "grok-export", "redacted": False}],
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
        result = run_command(["grok", "-r", target_id, "-p", prompt, "--cwd", str(cwd)], cwd=cwd)
        if result.returncode != 0:
            raise RuntimeError(f"grok resume failed with exit {result.returncode}: {result.stderr.strip()}")
        return SendResult(
            provider=self.provider,
            target_id=target_id,
            sent=True,
            method="grok-resume-p",
            artifact_path=str(artifact_path) if artifact_path else None,
            warnings=[result.stderr.strip()] if result.stderr.strip() else [],
        )
