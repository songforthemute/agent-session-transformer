from __future__ import annotations

from pathlib import Path

from agent_xfer.core.models import (
    InspectResult,
    NormalizedEvent,
    ProviderCapabilities,
    ReadSessionResult,
    SendResult,
)


class FakeAdapter:
    provider = "fake"
    id_kind = "session_id"
    capabilities = ProviderCapabilities(
        can_read_session=True,
        can_resume_target=True,
        can_send_prompt_to_target=True,
        can_emit_machine_readable_events=True,
        can_locate_local_transcripts=False,
        uses_official_api=False,
        uses_private_or_semiprivate_files=False,
        requires_auth=False,
        requires_local_cli=False,
    )

    def healthcheck(self, cwd: Path) -> dict:
        return {
            "provider": self.provider,
            "ok": True,
            "cwd": str(cwd),
            "requires_local_cli": False,
            "message": "fake adapter is available",
        }

    def _events(self, source_id: str, cwd: Path) -> list[NormalizedEvent]:
        now = "2026-06-11T00:00:00Z"
        return [
            NormalizedEvent(
                event_id=f"fake:{source_id}:0",
                provider=self.provider,
                source_id=source_id,
                sequence=0,
                created_at=now,
                role="user",
                kind="message",
                content_text="Implement the first agent-xfer milestone with a fake provider dry-run path.",
                cwd=str(cwd),
                status="ok",
            ),
            NormalizedEvent(
                event_id=f"fake:{source_id}:1",
                provider=self.provider,
                source_id=source_id,
                sequence=1,
                created_at=now,
                role="assistant",
                kind="summary",
                content_text="Created a deterministic fake session containing a goal, completed work, and pending work.",
                cwd=str(cwd),
                status="ok",
            ),
        ]

    def read_session(self, source_id: str, cwd: Path) -> ReadSessionResult:
        events = self._events(source_id, cwd)
        return ReadSessionResult(
            provider=self.provider,
            source_id=source_id,
            id_kind=self.id_kind,
            cwd=str(cwd),
            events=events,
            read_method="fake-static-events",
            created_at=events[0].created_at,
            updated_at=events[-1].created_at,
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
        )

    def send_handoff(self, target_id: str, prompt: str, cwd: Path, artifact_path: Path | None = None) -> SendResult:
        if artifact_path is not None:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(prompt, encoding="utf-8")
        return SendResult(
            provider=self.provider,
            target_id=target_id,
            sent=True,
            method="fake-file-send",
            artifact_path=str(artifact_path) if artifact_path else None,
        )
