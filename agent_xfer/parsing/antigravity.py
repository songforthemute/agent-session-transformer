from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from agent_xfer.core.models import NormalizedEvent
from agent_xfer.parsing.jsonl import parse_jsonl_lines

_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)


def extract_user_request(content: str) -> str:
    match = _USER_REQUEST_RE.search(content)
    if match:
        return match.group(1).strip()
    return content.strip()


def _event_id(source_id: str, sequence: int, item: dict[str, Any]) -> str:
    basis = f"antigravity:{source_id}:{sequence}:{item.get('step_index')}:{item.get('content', '')}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"antigravity:{source_id}:{sequence}:{digest}"


def parse_antigravity_transcript_jsonl(jsonl_text: str, source_id: str, cwd: Path | str) -> tuple[list[NormalizedEvent], list[str]]:
    objects, warnings = parse_jsonl_lines(jsonl_text.splitlines())
    events: list[NormalizedEvent] = []
    for item in objects:
        event_type = str(item.get("type", ""))
        source = str(item.get("source", ""))
        content = str(item.get("content", "") or "")
        role = "unknown"
        kind = "metadata"
        content_text = content.strip()
        if event_type == "USER_INPUT" or source == "USER_EXPLICIT":
            role = "user"
            kind = "message"
            content_text = extract_user_request(content)
        elif event_type in {"PLANNER_RESPONSE", "MODEL_RESPONSE"} or source == "MODEL":
            role = "assistant"
            kind = "message"
        elif event_type == "CONVERSATION_HISTORY":
            role = "system"
            kind = "metadata"
        if not content_text and kind != "metadata":
            continue
        sequence = len(events)
        events.append(
            NormalizedEvent(
                event_id=_event_id(source_id, sequence, item),
                provider="antigravity",
                source_id=source_id,
                sequence=sequence,
                created_at=str(item.get("created_at") or "unknown"),
                role=role,
                kind=kind,
                content_text=content_text,
                content_json=item,
                cwd=str(cwd),
                status=str(item.get("status") or "unknown").lower(),
                raw_ref={"format": "antigravity-transcript-jsonl", "step_index": item.get("step_index")},
            )
        )
    return events, warnings
