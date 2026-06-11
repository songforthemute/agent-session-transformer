from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from agent_xfer.parsing.claude import parse_claude_jsonl
from agent_xfer.providers.claude import ClaudeAdapter

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def test_parse_claude_jsonl_fixture() -> None:
    text = (FIXTURES / "claude" / "session.basic.jsonl").read_text(encoding="utf-8")
    events, warnings = parse_claude_jsonl(text, "claude-session", "/repo")
    assert warnings == []
    assert [event.role for event in events] == ["user", "assistant", "user", "assistant"]
    assert events[0].provider == "claude"
    assert "CLAUDE_BRIDGE_SMOKE_EPSILON" in events[0].content_text
    assert events[-1].content_text == "CLAUDE_BRIDGE_SMOKE_EPSILON"


def test_claude_adapter_reads_transcript_from_env(tmp_path: Path, monkeypatch) -> None:
    fixture = FIXTURES / "claude" / "session.basic.jsonl"
    monkeypatch.setenv("AGENT_XFER_CLAUDE_TRANSCRIPT", str(fixture))
    adapter = ClaudeAdapter()
    health = adapter.healthcheck(tmp_path)
    assert health["ok"] is True
    result = adapter.read_session("claude-session", tmp_path)
    assert result.read_method == "claude-jsonl"
    assert len(result.events) == 4
    assert result.raw_artifacts[0]["path"].endswith("session.basic.jsonl")


def test_claude_sender_invokes_resume_print(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "claude.json"
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(log_path)!r}, 'w').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_xfer",
            "--json",
            "sync",
            "--from",
            "fake:source-1",
            "--to",
            "claude:target-session",
            "--cwd",
            str(tmp_path),
            "--confirm",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    argv = json.loads(log_path.read_text(encoding="utf-8"))
    assert argv[0:3] == ["--resume", "target-session", "-p"]
    assert "# Agent Handoff" in argv[3]
    assert payload["send_result"]["method"] == "claude-resume-p"
