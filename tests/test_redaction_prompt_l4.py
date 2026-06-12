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


def test_redact_text_masks_standalone_provider_keys_and_export_env() -> None:
    text = "my key is sk-liveabcdefghijklmnopqrstuvwxyz and export OPENAI_API_KEY=sk-test-exported"
    redacted, state = redact_text(text, mode="secrets")

    assert "sk-live" not in redacted
    assert "sk-test-exported" not in redacted
    assert "export OPENAI_API_KEY=[REDACTED]" in redacted
    assert state.counts["provider_api_key"] == 1
    assert state.counts["env_var"] == 1


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


def test_redact_events_scrubs_structured_content_json() -> None:
    event = NormalizedEvent(
        event_id="e1",
        provider="fake",
        source_id="source",
        sequence=0,
        created_at="2026-06-11T00:00:00Z",
        role="tool",
        kind="tool_result",
        content_text="summary without secrets",
        content_json={
            "stdout": "TOKEN=supersecretvalue123456789",
            "nested": ["contact user@example.com", {"path": "/Users/alice/project"}],
        },
    )

    redacted, report = redact_events([event], mode="secrets")
    serialized_event = json.dumps(redacted[0].to_dict())
    serialized_report = json.dumps(report.to_dict())

    assert "supersecretvalue" not in serialized_event
    assert "user@example.com" not in serialized_event
    assert "/Users/alice" not in serialized_event
    assert "supersecretvalue" not in serialized_report
    assert redacted[0].content_json["stdout"] == "TOKEN=[REDACTED]"


def test_redact_events_drops_json_secret_fields_by_key() -> None:
    event = NormalizedEvent(
        event_id="e1",
        provider="fake",
        source_id="source",
        sequence=0,
        created_at="2026-06-11T00:00:00Z",
        role="tool",
        kind="tool_result",
        content_text="summary without secrets",
        content_json={
            "api_key": "short-secret",
            "password": "hunter2",
            "nested": {"client_secret": {"value": "nested-secret"}},
            "usage": {"total_tokens": 42, "prompt_tokens": 10},
        },
    )

    redacted, report = redact_events([event], mode="secrets")
    serialized_event = json.dumps(redacted[0].to_dict())
    serialized_report = json.dumps(report.to_dict())

    assert "short-secret" not in serialized_event
    assert "hunter2" not in serialized_event
    assert "nested-secret" not in serialized_event
    assert "short-secret" not in serialized_report
    assert redacted[0].content_json["api_key"] == "[REDACTED]"
    assert redacted[0].content_json["password"] == "[REDACTED]"
    assert redacted[0].content_json["nested"]["client_secret"] == "[REDACTED]"
    assert redacted[0].content_json["usage"] == {"total_tokens": 42, "prompt_tokens": 10}
    findings = {finding.kind: finding for finding in report.findings}
    assert findings["json_secret_field"].count == 3
    assert findings["json_secret_field"].sample_hash.startswith("sha256:")


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


def test_prompt_budget_participates_in_handoff_identity(tmp_path: Path) -> None:
    base_args = [
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
    ]
    truncated = subprocess.run(
        [*base_args, "--max-prompt-chars", "260"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    unbounded = subprocess.run(
        base_args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert truncated.returncode == 0, truncated.stderr + truncated.stdout
    assert unbounded.returncode == 0, unbounded.stderr + unbounded.stdout
    truncated_payload = json.loads(truncated.stdout)
    unbounded_payload = json.loads(unbounded.stdout)
    assert truncated_payload["handoff_id"] != unbounded_payload["handoff_id"]
    assert truncated_payload["artifact_dir"] != unbounded_payload["artifact_dir"]
