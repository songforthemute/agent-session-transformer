from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

from agent_xfer.core.models import NormalizedEvent
from agent_xfer.parsing.jsonl import parse_jsonl_lines
from agent_xfer.parsing.markdown_transcript import parse_grok_export_markdown


CHAT_HISTORY = "chat_history.jsonl"
SUMMARY = "summary.json"


def _read_member_text(archive: tarfile.TarFile, name: str) -> str | None:
    try:
        member = archive.getmember(name)
    except KeyError:
        return None
    fileobj = archive.extractfile(member)
    if fileobj is None:
        return None
    return fileobj.read().decode("utf-8", errors="replace")


def _content_text(value: Any) -> str:
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
        return _content_text(value.get("text") or value.get("content") or value.get("message"))
    return ""


def _event_from_chat_item(item: dict[str, Any], source_id: str, sequence: int, cwd: Path | str) -> NormalizedEvent | None:
    role = str(item.get("role") or item.get("speaker") or item.get("type") or "unknown").lower()
    if role in {"human", "user_message"}:
        role = "user"
    elif role in {"ai", "assistant_message", "model"}:
        role = "assistant"
    if role not in {"user", "assistant", "system", "tool"}:
        role = "unknown"
    text = _content_text(item.get("content") or item.get("text") or item.get("message"))
    if not text:
        return None
    return NormalizedEvent(
        event_id=f"grok-trace:{source_id}:{sequence}",
        provider="grok",
        source_id=source_id,
        sequence=sequence,
        created_at=str(item.get("created_at") or item.get("timestamp") or "unknown"),
        role=role,
        kind="message" if role in {"user", "assistant", "system"} else "tool_result",
        content_text=text,
        content_json=item,
        cwd=str(cwd),
        status=str(item.get("status") or "ok").lower(),
        raw_ref={"format": "grok-trace", "member": CHAT_HISTORY, "index": sequence},
    )


def parse_grok_trace_archive(path: Path, source_id: str, cwd: Path | str) -> tuple[list[NormalizedEvent], list[str]]:
    """Parse a `grok trace --local --json` tar.gz archive.

    The preferred member is `chat_history.jsonl`. If unavailable, this function falls
    back to a Markdown-ish `summary.json` string field when present.
    """
    warnings: list[str] = []
    with tarfile.open(path, mode="r:gz") as archive:
        chat_text = _read_member_text(archive, CHAT_HISTORY)
        if chat_text is not None:
            objects, jsonl_warnings = parse_jsonl_lines(chat_text.splitlines())
            warnings.extend(jsonl_warnings)
            events: list[NormalizedEvent] = []
            for item in objects:
                event = _event_from_chat_item(item, source_id, len(events), cwd)
                if event is not None:
                    events.append(event)
            if events:
                return events, warnings
            warnings.append("grok trace chat_history.jsonl contained no parseable message events")

        summary_text = _read_member_text(archive, SUMMARY)
        if summary_text is None:
            warnings.append("grok trace archive does not contain chat_history.jsonl or summary.json")
            return [], warnings
        try:
            summary = json.loads(summary_text)
        except json.JSONDecodeError as exc:
            warnings.append(f"summary.json invalid JSON: {exc.msg}")
            return [], warnings
        markdown = _content_text(summary.get("markdown") or summary.get("summary") or summary.get("text"))
        if not markdown:
            warnings.append("summary.json did not contain a parseable summary string")
            return [], warnings
        return parse_grok_export_markdown(markdown, source_id, cwd), warnings


def build_trace_archive(path: Path, members: dict[str, str]) -> None:
    """Test/helper utility for creating trace archives without touching provider CLIs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, mode="w:gz") as archive:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
