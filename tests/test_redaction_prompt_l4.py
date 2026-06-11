from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_xfer.core.ids import ProviderRef
from agent_xfer.core.models import NormalizedEvent
from agent_xfer.redaction.scanner import redact_events, redact_text
from agent_xfer.rendering.handoff_prompt import TRUNCATION_NOTICE, render_prompt

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def test_redact_text_masks_common_secret_shapes() -> None:
    text = (FIXTURES / "redaction" / "secrets.txt").read_text(encoding="utf-8")
    redacted, state = redact_text(text, mode="strict")

    assert "abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "sk-test-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "hunter2" not in redacted
    assert "user@example.com" not in redacted
    assert "/Users/alice" not in redacted
    assert "secret-private-key-material" not in redacted
    assert "abcdefghijklmnopqrstuvwxyzABCDEF1234567890" not in redacted
    assert state.counts["oauth_token"] == 1
    assert state.counts["api_key"] >= 1
    assert state.counts["env_var"] >= 1
    assert state.counts["email"] == 1
    assert state.counts["internal_path"] == 1
    assert state.counts["private_key"] == 1
    assert state.counts["high_entropy"] >= 1


def test_redaction_report_uses_hash_samples_not_secret_values() -> None:
    event = NormalizedEvent(
        event_id="e1",
        provider="fake",
        source_id="source",
        sequence=0,
        created_at="2026-06-11T00:00:00Z",
        role="user",
        kind="message",
        content_text="TOKEN=supersecretvalue123456789 user@example.com",
    )
    redacted, report = redact_events([event], mode="secrets")
    data = report.to_dict()
    serialized = json.dumps(data)

    assert "supersecretvalue" not in redacted[0].content_text
    assert "user@example.com" not in redacted[0].content_text
    assert "supersecretvalue" not in serialized
    assert all(finding.get("sample_hash", "").startswith("sha256:") for finding in data["findings"])


def test_render_prompt_respects_max_prompt_chars() -> None:
    events = [
        NormalizedEvent(
            event_id="e1",
            provider="fake",
            source_id="source",
            sequence=0,
            created_at="2026-06-11T00:00:00Z",
            role="user",
            kind="message",
            content_text="x" * 500,
        )
    ]
    prompt = render_prompt(
        ProviderRef.parse("fake:source"),
        ProviderRef.parse("fake:target"),
        "/repo",
        events,
        max_chars=240,
    )
    assert len(prompt) <= 240
    assert TRUNCATION_NOTICE in prompt


def test_cli_dry_run_writes_budget_metadata(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_xfer",
            "--json",
            "dry-run",
            "--from",
            "fake:source-1",
            "--to",
            "fake:target-1",
            "--cwd",
            str(tmp_path),
            "--max-prompt-chars",
            "260",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    bundle = json.loads((Path(payload["artifact_dir"]) / "handoff.json").read_text(encoding="utf-8"))
    prompt = (Path(payload["artifact_dir"]) / "prompt.md").read_text(encoding="utf-8")
    assert len(prompt) <= 260
    assert bundle["prompt_budget"]["max_chars"] == 260
    assert bundle["prompt_budget"]["actual_chars"] == len(prompt)
