from __future__ import annotations

import json
from pathlib import Path

from agent_xfer.parsing.grok_trace import build_trace_archive, parse_grok_trace_archive
from agent_xfer.providers.grok import GrokAdapter


def test_parse_grok_trace_archive_chat_history(tmp_path: Path) -> None:
    archive = tmp_path / "grok-trace.tar.gz"
    build_trace_archive(
        archive,
        {
            "chat_history.jsonl": "\n".join(
                [
                    json.dumps(
                        {
                            "role": "human",
                            "content": "Trace user asks for GROK_TRACE_TOKEN.",
                            "created_at": "2026-06-10T08:00:00Z",
                        }
                    ),
                    json.dumps(
                        {
                            "role": "ai",
                            "content": [{"text": "GROK_TRACE_TOKEN"}],
                            "created_at": "2026-06-10T08:00:01Z",
                        }
                    ),
                ]
            )
        },
    )

    events, warnings = parse_grok_trace_archive(archive, "trace-session", "/repo")

    assert warnings == []
    assert [event.role for event in events] == ["user", "assistant"]
    assert events[0].raw_ref == {"format": "grok-trace", "member": "chat_history.jsonl", "index": 0}
    assert events[0].content_text == "Trace user asks for GROK_TRACE_TOKEN."
    assert events[1].content_text == "GROK_TRACE_TOKEN"


def test_parse_grok_trace_archive_falls_back_to_summary_markdown(tmp_path: Path) -> None:
    archive = tmp_path / "grok-summary-trace.tar.gz"
    build_trace_archive(
        archive,
        {
            "summary.json": json.dumps(
                {
                    "markdown": "## User\n\nContinue from summary.\n\n## Assistant\n\nSummary accepted.",
                }
            )
        },
    )

    events, warnings = parse_grok_trace_archive(archive, "trace-session", "/repo")

    assert warnings == []
    assert [event.role for event in events] == ["user", "assistant"]
    assert events[0].content_text == "Continue from summary."


def test_grok_adapter_reads_configured_trace_archive(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "grok-trace.tar.gz"
    build_trace_archive(
        archive,
        {
            "chat_history.jsonl": json.dumps(
                {
                    "role": "user",
                    "content": "Use configured trace archive instead of invoking grok export.",
                    "created_at": "2026-06-10T08:00:00Z",
                }
            )
        },
    )
    monkeypatch.setenv("AGENT_XFER_GROK_TRACE_ARCHIVE", str(archive))

    result = GrokAdapter().read_session("trace-session", tmp_path)

    assert result.read_method == "grok-trace-archive"
    assert result.raw_artifacts == [{"kind": "grok-trace", "path": str(archive), "redacted": False}]
    assert len(result.events) == 1
    assert result.events[0].content_text == "Use configured trace archive instead of invoking grok export."
