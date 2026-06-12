from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_xfer import __version__
from agent_xfer.core.artifacts import write_json, write_text
from agent_xfer.core.checkpoints import canonical_digest, read_checkpoint, write_checkpoint
from agent_xfer.core.ids import ProviderRef
from agent_xfer.core.models import NormalizedEvent, ReadSessionResult, utc_now
from agent_xfer.core.schema import CHECKPOINT_SCHEMA_VERSION, HANDOFF_SCHEMA_VERSION, PROMPT_RENDERER_VERSION
from agent_xfer.providers import get_adapter
from agent_xfer.redaction.scanner import redact_events
from agent_xfer.rendering.handoff_prompt import TRUNCATION_NOTICE, render_prompt


class AgentXferError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _artifact_base(cwd: Path, handoff_id: str) -> Path:
    safe = handoff_id.replace(":", "-")
    return cwd / ".agent-xfer" / "handoffs" / safe


def doctor(cwd: Path) -> dict[str, Any]:
    cwd = cwd.resolve()
    return {
        "ok": True,
        "version": __version__,
        "python": sys.executable,
        "cwd": str(cwd),
        "artifact_root": str(cwd / ".agent-xfer"),
        "milestone": "L1-local-dry-run-skeleton",
        "schema_versions": {
            "handoff": HANDOFF_SCHEMA_VERSION,
            "checkpoint": CHECKPOINT_SCHEMA_VERSION,
            "prompt_renderer": PROMPT_RENDERER_VERSION,
        },
    }


def inspect(source: ProviderRef, cwd: Path) -> dict[str, Any]:
    adapter = get_adapter(source.provider)
    return adapter.inspect(source.id, cwd.resolve()).to_dict()


def _range_from_events(events: list[NormalizedEvent], mode: str) -> dict[str, Any]:
    if not events:
        return {"mode": mode, "from_sequence": None, "to_sequence": None, "event_count": 0}
    return {
        "mode": mode,
        "from_sequence": events[0].sequence,
        "to_sequence": events[-1].sequence,
        "event_count": len(events),
    }


def _select_events(
    events: list[NormalizedEvent],
    range_mode: str,
    checkpoint: dict[str, Any] | None,
) -> tuple[list[NormalizedEvent], dict[str, Any]]:
    if range_mode not in {"all", "since-last"}:
        raise AgentXferError("INVALID_RANGE", f"unsupported range mode: {range_mode}")
    if range_mode == "all" or not checkpoint:
        return events, _range_from_events(events, range_mode)

    last_range = checkpoint.get("last_source_range") if isinstance(checkpoint, dict) else None
    last_to = last_range.get("to_sequence") if isinstance(last_range, dict) else None
    if not isinstance(last_to, int):
        raise AgentXferError(
            "CHECKPOINT_RANGE_UNAVAILABLE",
            "checkpoint does not contain last_source_range.to_sequence; run with --range all or create a fresh checkpoint",
        )

    selected = [event for event in events if event.sequence > last_to]
    if not selected:
        raise AgentXferError("NO_NEW_EVENTS", "source has no events after the last checkpoint for this target")
    return selected, _range_from_events(selected, range_mode)


def build_handoff(
    source: ProviderRef,
    target: ProviderRef,
    cwd: Path,
    redact_mode: str = "secrets",
    max_prompt_chars: int | None = None,
    range_mode: str = "all",
) -> dict[str, Any]:
    cwd = cwd.resolve()
    adapter = get_adapter(source.provider)
    read_result: ReadSessionResult = adapter.read_session(source.id, cwd)
    resolved_source = ProviderRef(source.provider, read_result.source_id, read_result.id_kind)
    selected_events, source_range = _select_events(
        read_result.events, range_mode, read_checkpoint(cwd, resolved_source, target)
    )
    redacted_events, redaction_report = redact_events(selected_events, redact_mode)
    prompt = render_prompt(resolved_source, target, str(cwd), redacted_events, max_prompt_chars)
    prompt_budget = {
        "max_chars": max_prompt_chars,
        "actual_chars": len(prompt),
        "truncated": TRUNCATION_NOTICE in prompt,
    }
    digest_payload = {
        "source": {
            "provider": resolved_source.provider,
            "id": resolved_source.id,
            "id_kind": resolved_source.id_kind,
            "range": source_range,
        },
        "target": {"provider": target.provider, "id": target.id, "id_kind": target.id_kind},
        "events": [event.to_dict() for event in redacted_events],
        "prompt_renderer": PROMPT_RENDERER_VERSION,
        "prompt_budget": prompt_budget,
    }
    handoff_id = canonical_digest(digest_payload)
    artifact_dir = _artifact_base(cwd, handoff_id)
    bundle = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "created_at": utc_now(),
        "handoff_id": handoff_id,
        "source": {
            "provider": resolved_source.provider,
            "id": resolved_source.id,
            "id_kind": resolved_source.id_kind,
            "cwd": str(cwd),
            "created_at": read_result.created_at,
            "updated_at": read_result.updated_at,
            "read_method": read_result.read_method,
            "range": source_range,
        },
        "target": {
            "provider": target.provider,
            "id": target.id,
            "id_kind": target.id_kind,
            "cwd": str(cwd),
            "send_method": "pending-send",
        },
        "original_user_goal": next((event.content_text for event in redacted_events if event.role == "user"), "Unknown"),
        "current_state": next((event.content_text for event in reversed(redacted_events) if event.role == "assistant"), "Unknown"),
        "completed_work": [],
        "pending_work": ["Inspect the repository state before editing."],
        "decisions": [],
        "assumptions": ["Milestone 1 uses fake providers only for target send."],
        "files_touched": [],
        "commands_run": [],
        "tests_and_verification": [],
        "blockers": [],
        "raw_artifact_references": read_result.raw_artifacts,
        "redaction_report": redaction_report.to_dict(),
        "generated_handoff_prompt": prompt,
        "prompt_budget": prompt_budget,
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifact_dir / "handoff.json", bundle)
    write_text(artifact_dir / "prompt.md", prompt)
    write_json(artifact_dir / "source.redacted.jsonl", {"events": [event.to_dict() for event in redacted_events]})
    bundle["artifact_dir"] = str(artifact_dir)
    return bundle


def sync(
    source: ProviderRef,
    target: ProviderRef,
    cwd: Path,
    confirm: bool,
    allow_duplicate: bool = False,
    max_prompt_chars: int | None = None,
    range_mode: str = "all",
) -> dict[str, Any]:
    if not confirm:
        raise AgentXferError("CONFIRM_REQUIRED", "sync mutates the target and requires --confirm")
    bundle = build_handoff(source, target, cwd, max_prompt_chars=max_prompt_chars, range_mode=range_mode)
    cwd = cwd.resolve()
    checkpoint_source = ProviderRef(
        bundle["source"]["provider"], bundle["source"]["id"], bundle["source"]["id_kind"]
    )
    existing = read_checkpoint(cwd, checkpoint_source, target)
    if existing and existing.get("last_handoff_id") == bundle["handoff_id"] and not allow_duplicate:
        raise AgentXferError("DUPLICATE_HANDOFF_BLOCKED", "this handoff was already sent to the target")
    target_adapter = get_adapter(target.provider)
    artifact_dir = Path(bundle["artifact_dir"])
    send_result = target_adapter.send_handoff(
        target.id, bundle["generated_handoff_prompt"], cwd, artifact_dir / "target.prompt.md"
    )
    checkpoint = write_checkpoint(
        cwd,
        checkpoint_source,
        target,
        bundle["handoff_id"],
        artifact_dir,
        send_result.method,
        bundle["source"]["range"],
    )
    return {
        "ok": True,
        "handoff_id": bundle["handoff_id"],
        "artifact_dir": bundle["artifact_dir"],
        "checkpoint": str(checkpoint),
        "send_result": asdict(send_result),
    }
