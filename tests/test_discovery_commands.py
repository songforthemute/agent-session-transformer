from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_json(args: list[str], tmp_path: Path, env: dict[str, str] | None = None) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "agent_xfer", "--json", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def test_sources_lists_fake_and_env_backed_providers(tmp_path: Path, monkeypatch) -> None:
    codex_payload = tmp_path / "thread.json"
    codex_payload.write_text("{}", encoding="utf-8")
    claude_transcript = tmp_path / "claude.jsonl"
    claude_transcript.write_text("", encoding="utf-8")
    ag_home = tmp_path / "agy"
    cache = ag_home / "cache"
    cache.mkdir(parents=True)
    (cache / "last_conversations.json").write_text(json.dumps({str(tmp_path): "agy-conversation"}), encoding="utf-8")
    monkeypatch.setenv("AGENT_XFER_CODEX_THREAD_READ_JSON", str(codex_payload))
    monkeypatch.setenv("AGENT_XFER_CLAUDE_TRANSCRIPT", str(claude_transcript))
    monkeypatch.setenv("AGENT_XFER_ANTIGRAVITY_HOME", str(ag_home))

    payload = _run_json(["sources", "--cwd", str(tmp_path)], tmp_path, os.environ.copy())
    sources = {item["provider"]: item for item in payload["sources"]}
    assert sources["fake"]["id"] == "source-1"
    assert sources["codex"]["available"] is True
    assert sources["claude"]["available"] is True
    assert sources["antigravity"]["id"] == "agy-conversation"


def test_targets_reports_cli_availability_from_path(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ["codex", "grok", "agy", "claude"]:
        path = fake_bin / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    payload = _run_json(["targets", "--cwd", str(tmp_path)], tmp_path, env)
    targets = {item["provider"]: item for item in payload["targets"]}
    assert targets["fake"]["available"] is True
    assert targets["codex"]["available"] is True
    assert targets["grok"]["available"] is True
    assert targets["antigravity"]["available"] is True
    assert targets["claude"]["available"] is True


def test_sources_reports_codex_app_server_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_XFER_CODEX_THREAD_READ_JSON", raising=False)
    monkeypatch.setenv("AGENT_XFER_CODEX_APP_SERVER_COMMAND", "python fake-codex-server.py")

    payload = _run_json(["sources", "--cwd", str(tmp_path)], tmp_path, os.environ.copy())
    sources = {item["provider"]: item for item in payload["sources"]}
    assert sources["codex"]["available"] is True
    assert sources["codex"]["path"] == "python fake-codex-server.py"
    assert sources["codex"]["reason"] == "AGENT_XFER_CODEX_APP_SERVER_COMMAND is set"


def test_sources_deep_discovers_grok_sessions_from_cli_json(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    grok = fake_bin / "grok"
    grok.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "assert sys.argv[1:] == ['sessions', '--json']\n"
        "print(json.dumps({'sessions': [{'id': 'grok-session-a'}, {'session_id': 'grok-session-b'}]}))\n",
        encoding="utf-8",
    )
    grok.chmod(grok.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    payload = _run_json(["sources", "--cwd", str(tmp_path), "--deep"], tmp_path, env)
    grok_sources = [item for item in payload["sources"] if item["provider"] == "grok"]
    assert [item["id"] for item in grok_sources] == ["grok-session-a", "grok-session-b"]


def test_sources_deep_discovers_antigravity_brain_transcripts(tmp_path: Path, monkeypatch) -> None:
    ag_home = tmp_path / "agy"
    logs = ag_home / "brain" / "conversation-deep" / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    transcript = logs / "transcript_full.jsonl"
    transcript.write_text("", encoding="utf-8")
    monkeypatch.setenv("AGENT_XFER_ANTIGRAVITY_HOME", str(ag_home))

    payload = _run_json(["sources", "--cwd", str(tmp_path), "--deep"], tmp_path, os.environ.copy())
    ag_sources = [item for item in payload["sources"] if item["provider"] == "antigravity" and item["id"] == "conversation-deep"]
    assert ag_sources[0]["path"] == str(transcript)
