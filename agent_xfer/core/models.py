from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ProviderCapabilities:
    can_read_session: bool
    can_resume_target: bool
    can_send_prompt_to_target: bool
    can_emit_machine_readable_events: bool
    can_locate_local_transcripts: bool
    uses_official_api: bool
    uses_private_or_semiprivate_files: bool
    requires_auth: bool
    requires_local_cli: bool


@dataclass
class NormalizedEvent:
    event_id: str
    provider: str
    source_id: str
    sequence: int
    created_at: str
    role: str
    kind: str
    content_text: str
    content_json: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    command: str | None = None
    cwd: str | None = None
    status: str = "unknown"
    files: list[str] = field(default_factory=list)
    raw_ref: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReadSessionResult:
    provider: str
    source_id: str
    id_kind: str
    cwd: str
    events: list[NormalizedEvent]
    read_method: str
    created_at: str | None = None
    updated_at: str | None = None
    raw_artifacts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class InspectResult:
    provider: str
    source_id: str
    id_kind: str
    cwd: str
    can_read: bool
    read_method: str
    event_count: int
    created_at: str | None
    updated_at: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SendResult:
    provider: str
    target_id: str
    sent: bool
    method: str
    artifact_path: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class RedactionFinding:
    kind: str
    count: int
    action: str
    sample_hash: str | None = None


@dataclass
class RedactionReport:
    mode: str
    findings: list[RedactionFinding] = field(default_factory=list)
    dropped_raw_event_count: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data
