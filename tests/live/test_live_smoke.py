from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _live_enabled() -> bool:
    return os.environ.get("AGENT_XFER_LIVE") == "1"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is required for live smoke")
    return value


pytestmark = pytest.mark.live


@pytest.mark.skipif(not _live_enabled(), reason="set AGENT_XFER_LIVE=1 to run live smoke tests")
def test_live_dry_run_builds_artifact() -> None:
    cwd = Path(_required_env("AGENT_XFER_LIVE_CWD")).expanduser()
    source = _required_env("AGENT_XFER_LIVE_FROM")
    target = _required_env("AGENT_XFER_LIVE_TO")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_xfer",
            "--json",
            "dry-run",
            "--from",
            source,
            "--to",
            target,
            "--cwd",
            str(cwd),
            "--redact",
            os.environ.get("AGENT_XFER_LIVE_REDACT", "secrets"),
            "--max-prompt-chars",
            os.environ.get("AGENT_XFER_LIVE_MAX_PROMPT_CHARS", "4000"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    artifact_dir = Path(payload["artifact_dir"])
    assert (artifact_dir / "handoff.json").exists()
    assert (artifact_dir / "prompt.md").exists()


@pytest.mark.skipif(not _live_enabled(), reason="set AGENT_XFER_LIVE=1 to run live smoke tests")
def test_live_sync_confirm_when_explicitly_enabled() -> None:
    if os.environ.get("AGENT_XFER_LIVE_CONFIRM_SYNC") != "1":
        pytest.skip("set AGENT_XFER_LIVE_CONFIRM_SYNC=1 to mutate a real target session")
    cwd = Path(_required_env("AGENT_XFER_LIVE_CWD")).expanduser()
    source = _required_env("AGENT_XFER_LIVE_FROM")
    target = _required_env("AGENT_XFER_LIVE_TO")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_xfer",
            "--json",
            "sync",
            "--from",
            source,
            "--to",
            target,
            "--cwd",
            str(cwd),
            "--confirm",
            "--max-prompt-chars",
            os.environ.get("AGENT_XFER_LIVE_MAX_PROMPT_CHARS", "4000"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert Path(payload["checkpoint"]).exists()
    assert Path(payload["artifact_dir"], "target.prompt.md").exists()
