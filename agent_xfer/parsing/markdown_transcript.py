from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agent_xfer.core.models import NormalizedEvent

_HEADING_RE = re.compile(r"^##\s+(User|Assistant)\s*$", re.IGNORECASE | re.MULTILINE)


def _event_id(provider: str, source_id: str, sequence: int, content: str) -> str:
    digest = hashlib.sha256(f"{provider}:{source_id}:{sequence}:{content}".encode("utf-8")).hexdigest()[:16]
    return f"{provider}:{source_id}:{sequence}:{digest}"


def parse_grok_export_markdown(markdown: str, source_id: str, cwd: Path | str) -> list[NormalizedEvent]:
    """Parse `grok export` Markdown transcript headings into normalized message events."""
    matches = list(_HEADING_RE.finditer(markdown))
    events: list[NormalizedEvent] = []
    for index, match in enumerate(matches):
        role_label = match.group(1).lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()
        if not content:
            continue
        sequence = len(events)
        events.append(
            NormalizedEvent(
                event_id=_event_id("grok", source_id, sequence, content),
                provider="grok",
                source_id=source_id,
                sequence=sequence,
                created_at="unknown",
                role="user" if role_label == "user" else "assistant",
                kind="message",
                content_text=content,
                cwd=str(cwd),
                status="ok",
                raw_ref={"format": "grok-export-markdown", "heading": match.group(0)},
            )
        )
    return events
