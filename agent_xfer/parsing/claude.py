from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_xfer.core.models import NormalizedEvent
from agent_xfer.parsing.jsonl import parse_jsonl_lines


def _event_id(source_id: str, sequence: int, item: dict[str, Any], text: str) -> str:
    basis = f"claude:{source_id}:{sequence}:{item.get('uuid')}:{item.get('type')}:{text}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"claude:{source_id}:{sequence}:{digest}"


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    if isinstance(value, dict):
        return _extract_text(value.get("content") or value.get("text") or value.get("message"))
    return ""


def _message_payload(item: dict[str, Any]) -> dict[str, Any]:
    message = item.get("message")
    if isinstance(message, dict):
        return message
    return item


def parse_claude_jsonl(jsonl_text: str, source_id: str, cwd: Path | str) -> tuple[list[NormalizedEvent], list[str]]:
    """Parse Claude Code JSONL transcript-ish events into conservative message events.

    The Claude Code transcript schema can vary by version, so this parser is deliberately
    tolerant: it extracts role/content from common top-level or nested `message` shapes and
    preserves the raw JSON object in `content_json`.
    """
    objects, warnings = parse_jsonl_lines(jsonl_text.splitlines())
    events: list[NormalizedEvent] = []
    for item in objects:
        payload = _message_payload(item)
        role = str(payload.get("role") or item.get("role") or item.get("type") or "unknown").lower()
        if role == "assistant_message":
            role = "assistant"
        elif role == "user_message":
            role = "user"
        if role not in {"user", "assistant", "system", "tool"}:
            if item.get("type") in {"user", "assistant", "system"}:
                role = str(item["type"])
            else:
                role = "unknown"
        text = _extract_text(payload.get("content") or payload.get("text") or item.get("content") or item.get("text"))
        if not text and role != "system":
            continue
        sequence = len(events)
        events.append(
            NormalizedEvent(
                event_id=_event_id(source_id, sequence, item, text),
                provider="claude",
                source_id=source_id,
                sequence=sequence,
                created_at=str(item.get("timestamp") or item.get("created_at") or "unknown"),
                role=role,
                kind="message" if role in {"user", "assistant", "system"} else "tool_result",
                content_text=text,
                content_json=item,
                cwd=str(cwd),
                status="ok",
                raw_ref={"format": "claude-jsonl", "index": sequence},
            )
        )
    return events, warnings
