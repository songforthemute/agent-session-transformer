from __future__ import annotations

import json
from pathlib import Path

from agent_xfer.parsing.antigravity import extract_user_request, parse_antigravity_transcript_jsonl
from agent_xfer.parsing.codex_app_server import parse_codex_thread_read
from agent_xfer.parsing.jsonl import parse_jsonl_lines
from agent_xfer.parsing.markdown_transcript import parse_grok_export_markdown

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_grok_export_markdown() -> None:
    text = (FIXTURES / "grok" / "export-basic.md").read_text(encoding="utf-8")
    events = parse_grok_export_markdown(text, "019eb0b8-00df-7300-aeed-4fd7e2a4b7fd", "/repo")
    assert [event.role for event in events] == ["user", "assistant", "user", "assistant"]
    assert events[0].provider == "grok"
    assert "GROK_BRIDGE_SMOKE_GAMMA" in events[0].content_text
    assert events[-1].content_text == "GROK_BRIDGE_SMOKE_GAMMA"


def test_extract_antigravity_user_request() -> None:
    wrapped = "<USER_REQUEST>\nhello\n</USER_REQUEST>\n<ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>"
    assert extract_user_request(wrapped) == "hello"


def test_parse_antigravity_transcript_jsonl() -> None:
    text = (FIXTURES / "antigravity" / "transcript_full.basic.jsonl").read_text(encoding="utf-8")
    events, warnings = parse_antigravity_transcript_jsonl(text, "9d61b187-4b6d-4e4d-b286-08a3a30454e5", "/repo")
    assert warnings == []
    message_events = [event for event in events if event.kind == "message"]
    assert [event.role for event in message_events] == ["user", "assistant", "user", "assistant"]
    assert message_events[0].content_text == "Bridge smoke test. Reply with exactly: AGY_BRIDGE_SMOKE_DELTA"
    assert message_events[-1].content_text == "AGY_BRIDGE_SMOKE_DELTA"


def test_parse_codex_thread_read() -> None:
    payload = json.loads((FIXTURES / "codex" / "thread_read_basic.json").read_text(encoding="utf-8"))
    events = parse_codex_thread_read(payload, "fallback", "/repo")
    assert [event.role for event in events] == ["user", "assistant", "user", "assistant"]
    assert events[0].source_id == "019eb0b6-3e60-76d1-a573-6f9da5937d36"
    assert events[1].content_text == "CODEX_BRIDGE_SMOKE_BETA"


def test_parse_jsonl_lines_keeps_warnings_non_fatal() -> None:
    objects, warnings = parse_jsonl_lines(['{"ok": true}', 'not json', '[1, 2]'])
    assert objects == [{"ok": True}]
    assert len(warnings) == 2
