from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from agent_xfer.core.models import InspectResult, ProviderCapabilities, ReadSessionResult, SendResult
from agent_xfer.parsing.codex_app_server import parse_codex_thread_read
from agent_xfer.providers.codex_app_server_client import read_thread_via_app_server
from agent_xfer.subprocesses.prompt_transport import ensure_prompt_fits_argv
from agent_xfer.subprocesses.runner import run_command


def _write_prompt_artifact(path: Path | None, prompt: str) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")


class CodexAdapter:
    provider = "codex"
    id_kind = "thread_id"
    capabilities = ProviderCapabilities(
        can_read_session=True,
        can_resume_target=True,
        can_send_prompt_to_target=True,
        can_emit_machine_readable_events=True,
        can_locate_local_transcripts=False,
        uses_official_api=True,
        uses_private_or_semiprivate_files=False,
        requires_auth=True,
        requires_local_cli=True,
    )

    def healthcheck(self, cwd: Path) -> dict:
        path = shutil.which("codex")
        fixture = os.environ.get("AGENT_XFER_CODEX_THREAD_READ_JSON")
        app_server_command = os.environ.get("AGENT_XFER_CODEX_APP_SERVER_COMMAND")
        return {
            "provider": self.provider,
            "ok": path is not None or bool(fixture) or bool(app_server_command),
            "cli": path,
            "fixture": fixture,
            "app_server_command": app_server_command,
            "cwd": str(cwd),
        }

    def _payload_path(self) -> Path | None:
        value = os.environ.get("AGENT_XFER_CODEX_THREAD_READ_JSON")
        if not value:
            return None
        return Path(value).expanduser()

    def _app_server_command(self) -> str | None:
        return os.environ.get("AGENT_XFER_CODEX_APP_SERVER_COMMAND")

    def _read_payload(self, source_id: str, cwd: Path) -> tuple[dict, str, list[dict], list[str]]:
        path = self._payload_path()
        if path is not None:
            return (
                json.loads(path.read_text(encoding="utf-8")),
                "codex-thread-read-json",
                [{"kind": "codex-thread-read-json", "path": str(path), "redacted": False}],
                [],
            )
        command = self._app_server_command()
        if command:
            response = read_thread_via_app_server(command, source_id, cwd)
            raw_artifacts = [{"kind": "codex-app-server-thread-read", "command": response.command, "redacted": False}]
            warnings = [response.stderr] if response.stderr else []
            return response.payload, "codex-app-server-thread-read", raw_artifacts, warnings
        raise NotImplementedError(
            "Codex read requires AGENT_XFER_CODEX_THREAD_READ_JSON or AGENT_XFER_CODEX_APP_SERVER_COMMAND"
        )

    def read_session(self, source_id: str, cwd: Path) -> ReadSessionResult:
        payload, read_method, raw_artifacts, warnings = self._read_payload(source_id, cwd)
        events = parse_codex_thread_read(payload, source_id, cwd)
        if not events:
            warnings.append("Codex thread/read payload produced no normalized events")
        resolved_source_id = events[0].source_id if events else source_id
        return ReadSessionResult(
            provider=self.provider,
            source_id=resolved_source_id,
            id_kind=self.id_kind,
            cwd=str(cwd),
            events=events,
            read_method=read_method,
            created_at=events[0].created_at if events else None,
            updated_at=events[-1].created_at if events else None,
            raw_artifacts=raw_artifacts,
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
        ensure_prompt_fits_argv(prompt, provider=self.provider, artifact_path=artifact_path)
        result = run_command(["codex", "exec", "resume", target_id, prompt], cwd=cwd)
        if result.returncode != 0:
            raise RuntimeError(f"codex exec resume failed with exit {result.returncode}: {result.stderr.strip()}")
        return SendResult(
            provider=self.provider,
            target_id=target_id,
            sent=True,
            method="codex-exec-resume",
            artifact_path=str(artifact_path) if artifact_path else None,
            warnings=[result.stderr.strip()] if result.stderr.strip() else [],
        )
