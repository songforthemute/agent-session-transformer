from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent_xfer.core.models import InspectResult, ProviderCapabilities, ReadSessionResult, SendResult


class ProviderAdapter(Protocol):
    provider: str
    id_kind: str
    capabilities: ProviderCapabilities

    def healthcheck(self, cwd: Path) -> dict: ...
    def inspect(self, source_id: str, cwd: Path) -> InspectResult: ...
    def read_session(self, source_id: str, cwd: Path) -> ReadSessionResult: ...
    def send_handoff(self, target_id: str, prompt: str, cwd: Path, artifact_path: Path | None = None) -> SendResult: ...
