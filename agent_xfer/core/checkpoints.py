from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_xfer.core.ids import ProviderRef
from agent_xfer.core.models import utc_now
from agent_xfer.core.schema import CHECKPOINT_SCHEMA_VERSION


def canonical_digest(data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def checkpoint_path(cwd: Path, source: ProviderRef, target: ProviderRef) -> Path:
    return cwd / ".agent-xfer" / "checkpoints" / f"{source.key()}__{target.key()}.json"


def read_checkpoint(cwd: Path, source: ProviderRef, target: ProviderRef) -> dict[str, Any] | None:
    path = checkpoint_path(cwd, source, target)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_checkpoint(
    cwd: Path,
    source: ProviderRef,
    target: ProviderRef,
    handoff_id: str,
    artifact_dir: Path,
    send_method: str,
    source_range: dict[str, Any] | None = None,
) -> Path:
    path = checkpoint_path(cwd, source, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "source": {"provider": source.provider, "id": source.id, "id_kind": source.id_kind},
        "target": {"provider": target.provider, "id": target.id, "id_kind": target.id_kind},
        "last_handoff_id": handoff_id,
        "sent_at": utc_now(),
        "send_method": send_method,
        "artifact_dir": str(artifact_dir),
        "last_source_range": source_range or {"mode": "all", "from_sequence": None, "to_sequence": None, "event_count": None},
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
