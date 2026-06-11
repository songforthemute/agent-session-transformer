from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_xfer.core.models import NormalizedEvent


def _get_thread_id(payload: dict[str, Any], fallback: str) -> str:
    thread = payload.get("thread")
    if isinstance(thread, dict) and thread.get("id"):
        return str(thread["id"])
    if payload.get("thread_id"):
        return str(payload["thread_id"])
    if payload.get("id"):
        return str(payload["id"])
    return fallback


def _item_text(item: dict[str, Any]) -> str:
    for key in ("text", "content", "message"):
        value = item.get(key)
        if isinstance(value, str):
            return value.strip()
    payload = item.get("payload")
    if isinstance(payload, dict):
        for key in ("text", "content", "message"):
            value = payload.get(key)
            if isinstance(value, str):
                return value.strip()
    return ""


def _item_role_kind(item: dict[str, Any]) -> tuple[str, str]:
    item_type = str(item.get("type") or item.get("kind") or "").lower()
    role = str(item.get("role") or "").lower()
    if role in {"user", "assistant", "system", "tool"}:
        return role, "message" if role in {"user", "assistant", "system"} else "tool_result"
    if "user" in item_type:
        return "user", "message"
    if "agent" in item_type or "assistant" in item_type:
        return "assistant", "message"
    if "tool" in item_type:
        return "tool", "tool_result"
    return "unknown", "unknown"


def _event_id(source_id: str, sequence: int, item: dict[str, Any], text: str) -> str:
    basis = f"codex:{source_id}:{sequence}:{item.get('id')}:{item.get('type')}:{text}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"codex:{source_id}:{sequence}:{digest}"


def parse_codex_thread_read(payload: dict[str, Any], source_id: str, cwd: Path | str) -> list[NormalizedEvent]:
    """Parse Codex app-server `thread/read includeTurns`-style payloads."""
    resolved_source_id = _get_thread_id(payload, source_id)
    turns = payload.get("turns", [])
    if isinstance(payload.get("thread"), dict) and isinstance(payload["thread"].get("turns"), list):
        turns = payload["thread"]["turns"]
    events: list[NormalizedEvent] = []
    if not isinstance(turns, list):
        return events
    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        items = turn.get("items", [])
        if not isinstance(items, list):
            continue
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            text = _item_text(item)
            role, kind = _item_role_kind(item)
            if not text and kind != "unknown":
                continue
            sequence = len(events)
            events.append(
                NormalizedEvent(
                    event_id=_event_id(resolved_source_id, sequence, item, text),
                    provider="codex",
                    source_id=resolved_source_id,
                    sequence=sequence,
                    created_at=str(item.get("created_at") or turn.get("created_at") or "unknown"),
                    role=role,
                    kind=kind,
                    content_text=text,
                    content_json=item,
                    cwd=str(cwd),
                    status=str(item.get("status") or turn.get("status") or "unknown").lower(),
                    raw_ref={"format": "codex-thread-read", "turn_index": turn_index, "item_index": item_index},
                )
            )
    return events
