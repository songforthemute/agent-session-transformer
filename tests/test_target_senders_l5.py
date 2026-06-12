from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_xfer.providers.codex import CodexAdapter
from agent_xfer.subprocesses.prompt_transport import ensure_prompt_fits_argv

ROOT = Path(__file__).resolve().parents[1]


def _write_recorder(path: Path, command_name: str, log_path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"assert sys.argv[0].endswith({command_name!r})\n"
        f"open({str(log_path)!r}, 'w').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_sync(tmp_path: Path, executable: str, target_ref: str) -> tuple[dict, list[str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    log_path = tmp_path / f"{executable}.json"
    _write_recorder(fake_bin / executable, executable, log_path)
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
            target_ref,
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
    return json.loads(result.stdout), json.loads(log_path.read_text(encoding="utf-8"))


def test_codex_sender_invokes_exec_resume(tmp_path: Path) -> None:
    payload, argv = _run_sync(tmp_path, "codex", "codex:thread-1")
    assert argv[:3] == ["exec", "resume", "thread-1"]
    assert "# Agent Handoff" in argv[3]
    assert payload["send_result"]["method"] == "codex-exec-resume"
    assert Path(payload["artifact_dir"], "target.prompt.md").exists()


def test_grok_sender_invokes_resume_prompt_with_cwd(tmp_path: Path) -> None:
    payload, argv = _run_sync(tmp_path, "grok", "grok:session-1")
    assert argv[0:3] == ["-r", "session-1", "-p"]
    assert "# Agent Handoff" in argv[3]
    assert argv[-2:] == ["--cwd", str(tmp_path)]
    assert payload["send_result"]["method"] == "grok-resume-p"


def test_antigravity_sender_invokes_conversation_print(tmp_path: Path) -> None:
    payload, argv = _run_sync(tmp_path, "agy", "antigravity:conversation-1")
    assert argv[0:2] == ["--conversation", "conversation-1"]
    assert argv[2] == "--print"
    assert "# Agent Handoff" in argv[3]
    assert argv[-2:] == ["--print-timeout", "30s"]
    assert payload["send_result"]["method"] == "agy-conversation-print"


def test_sender_blocks_oversized_argv_prompt_before_invoking_provider(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "codex.json"
    _write_recorder(fake_bin / "codex", "codex", log_path)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["AGENT_XFER_PROMPT_ARG_MAX"] = "10"
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
            "codex:thread-1",
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
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["code"] == "OPERATION_FAILED"
    assert "AGENT_XFER_PROMPT_ARG_MAX=10" in payload["message"]
    assert not log_path.exists()


def test_prompt_argv_guard_counts_utf8_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_XFER_PROMPT_ARG_MAX", "5")

    with pytest.raises(RuntimeError) as exc_info:
        ensure_prompt_fits_argv("한글", provider="codex")

    assert "6 bytes" in str(exc_info.value)
    assert "AGENT_XFER_PROMPT_ARG_MAX=5" in str(exc_info.value)


def test_codex_sender_guard_includes_argv_overhead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "codex.json"
    _write_recorder(fake_bin / "codex", "codex", log_path)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("AGENT_XFER_PROMPT_ARG_MAX", "9")

    with pytest.raises(RuntimeError) as exc_info:
        CodexAdapter().send_handoff("thread-1", "ok", tmp_path, tmp_path / "target.prompt.md")

    assert "argv is" in str(exc_info.value)
    assert "prompt is 2 bytes" in str(exc_info.value)
    assert "AGENT_XFER_PROMPT_ARG_MAX=9" in str(exc_info.value)
    assert not log_path.exists()
