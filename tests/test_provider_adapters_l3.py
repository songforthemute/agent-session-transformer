from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from agent_xfer.providers.antigravity import AntigravityAdapter
from agent_xfer.providers.codex import CodexAdapter
from agent_xfer.providers.grok import GrokAdapter

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def test_grok_adapter_reads_export_from_cli(tmp_path: Path, monkeypatch) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fixture = FIXTURES / "grok" / "export-basic.md"
    grok = fake_bin / "grok"
    grok.write_text(f"#!/bin/sh\ncat {fixture}\n", encoding="utf-8")
    grok.chmod(grok.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    adapter = GrokAdapter()
    health = adapter.healthcheck(tmp_path)
    assert health["ok"] is True
    result = adapter.read_session("grok-session", tmp_path)
    assert result.read_method == "grok-export"
    assert len(result.events) == 4
    assert result.events[0].role == "user"


def test_antigravity_adapter_reads_transcript_from_configured_home(tmp_path: Path, monkeypatch) -> None:
    conversation_id = "9d61b187-4b6d-4e4d-b286-08a3a30454e5"
    logs = tmp_path / "brain" / conversation_id / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    transcript = FIXTURES / "antigravity" / "transcript_full.basic.jsonl"
    (logs / "transcript_full.jsonl").write_text(transcript.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("AGENT_XFER_ANTIGRAVITY_HOME", str(tmp_path))

    adapter = AntigravityAdapter()
    health = adapter.healthcheck(tmp_path)
    assert health["ok"] is True
    result = adapter.read_session(conversation_id, tmp_path)
    assert result.read_method == "antigravity-transcript-jsonl"
    assert len([event for event in result.events if event.kind == "message"]) == 4
    assert result.raw_artifacts[0]["path"].endswith("transcript_full.jsonl")



def test_antigravity_adapter_resolves_last_alias_from_cwd_mapping(tmp_path: Path, monkeypatch) -> None:
    conversation_id = "9d61b187-4b6d-4e4d-b286-08a3a30454e5"
    logs = tmp_path / "brain" / conversation_id / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    transcript = FIXTURES / "antigravity" / "transcript_full.basic.jsonl"
    (logs / "transcript_full.jsonl").write_text(transcript.read_text(encoding="utf-8"), encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "last_conversations.json").write_text(json.dumps({str(tmp_path.resolve()): conversation_id}), encoding="utf-8")
    monkeypatch.setenv("AGENT_XFER_ANTIGRAVITY_HOME", str(tmp_path))

    adapter = AntigravityAdapter()
    result = adapter.read_session("last", tmp_path)

    assert result.source_id == conversation_id
    assert result.read_method == "antigravity-transcript-jsonl"
    assert len([event for event in result.events if event.kind == "message"]) == 4


def test_antigravity_adapter_reads_env_transcript_override(tmp_path: Path, monkeypatch) -> None:
    transcript = tmp_path / "override.jsonl"
    transcript.write_text((FIXTURES / "antigravity" / "transcript_full.basic.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("AGENT_XFER_ANTIGRAVITY_TRANSCRIPT", str(transcript))

    result = AntigravityAdapter().read_session("conversation-from-env", tmp_path)

    assert result.source_id == "conversation-from-env"
    assert result.raw_artifacts[0]["path"] == str(transcript)

def test_codex_adapter_reads_thread_read_json_from_env(tmp_path: Path, monkeypatch) -> None:
    fixture = FIXTURES / "codex" / "thread_read_basic.json"
    monkeypatch.setenv("AGENT_XFER_CODEX_THREAD_READ_JSON", str(fixture))

    adapter = CodexAdapter()
    health = adapter.healthcheck(tmp_path)
    assert health["ok"] is True
    result = adapter.read_session("fallback", tmp_path)
    assert result.read_method == "codex-thread-read-json"
    assert len(result.events) == 4
    assert result.events[0].source_id == "019eb0b6-3e60-76d1-a573-6f9da5937d36"


def test_cli_dry_run_with_grok_source_and_fake_target(tmp_path: Path, monkeypatch) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fixture = FIXTURES / "grok" / "export-basic.md"
    grok = fake_bin / "grok"
    grok.write_text(f"#!/bin/sh\ncat {fixture}\n", encoding="utf-8")
    grok.chmod(grok.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_xfer",
            "--json",
            "dry-run",
            "--from",
            "grok:grok-session",
            "--to",
            "fake:target",
            "--cwd",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    artifact_dir = Path(payload["artifact_dir"])
    bundle = json.loads((artifact_dir / "handoff.json").read_text(encoding="utf-8"))
    assert bundle["source"]["provider"] == "grok"
    assert bundle["source"]["read_method"] == "grok-export"


def test_codex_adapter_reads_thread_via_app_server_command(tmp_path: Path, monkeypatch) -> None:
    server = tmp_path / "codex-app-server.py"
    request_log = tmp_path / "request.json"
    payload = json.loads((FIXTURES / "codex" / "thread_read_basic.json").read_text(encoding="utf-8"))
    server.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "request = json.loads(sys.stdin.readline())\n"
        f"open({str(request_log)!r}, 'w').write(json.dumps(request, sort_keys=True))\n"
        f"payload = {json.dumps(payload)!r}\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), 'result': json.loads(payload)}))\n",
        encoding="utf-8",
    )
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("AGENT_XFER_CODEX_THREAD_READ_JSON", raising=False)
    monkeypatch.setenv("AGENT_XFER_CODEX_APP_SERVER_COMMAND", f"{sys.executable} {server}")

    result = CodexAdapter().read_session("019eb0b6-3e60-76d1-a573-6f9da5937d36", tmp_path)

    request = json.loads(request_log.read_text(encoding="utf-8"))
    assert request["method"] == "thread/read"
    assert request["params"] == {"threadId": "019eb0b6-3e60-76d1-a573-6f9da5937d36", "includeTurns": True, "path": str(tmp_path)}
    assert result.read_method == "codex-app-server-thread-read"
    assert result.raw_artifacts[0]["kind"] == "codex-app-server-thread-read"
    assert len(result.events) == 4


def test_codex_app_server_retries_after_transient_failure(tmp_path: Path, monkeypatch) -> None:
    server = tmp_path / "retrying-codex-app-server.py"
    marker = tmp_path / "attempted"
    payload = json.loads((FIXTURES / "codex" / "thread_read_basic.json").read_text(encoding="utf-8"))
    server.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "request = json.loads(sys.stdin.readline())\n"
        "if not marker.exists():\n"
        "    marker.write_text('1')\n"
        "    print('transient failure', file=sys.stderr)\n"
        "    raise SystemExit(3)\n"
        f"payload = {json.dumps(payload)!r}\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), 'result': json.loads(payload)}))\n",
        encoding="utf-8",
    )
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("AGENT_XFER_CODEX_THREAD_READ_JSON", raising=False)
    monkeypatch.setenv("AGENT_XFER_CODEX_APP_SERVER_COMMAND", f"{sys.executable} {server}")
    monkeypatch.setenv("AGENT_XFER_CODEX_APP_SERVER_RETRIES", "1")

    result = CodexAdapter().read_session("019eb0b6-3e60-76d1-a573-6f9da5937d36", tmp_path)

    assert result.read_method == "codex-app-server-thread-read"
    assert len(result.events) == 4
