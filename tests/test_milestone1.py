from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_xfer", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )


def test_doctor_json(tmp_path: Path) -> None:
    result = run_cli(["--json", "doctor", "--cwd", str(tmp_path)], tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["milestone"] == "L1-local-dry-run-skeleton"
    assert payload["schema_versions"] == {
        "handoff": "agent-xfer.handoff.v1",
        "checkpoint": "agent-xfer.checkpoint.v1",
        "prompt_renderer": "agent-xfer.prompt.v1",
    }


def test_inspect_fake_source(tmp_path: Path) -> None:
    result = run_cli(["--json", "inspect", "--source", "fake:source-1", "--cwd", str(tmp_path)], tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["provider"] == "fake"
    assert payload["id_kind"] == "session_id"
    assert payload["event_count"] == 2


def test_dry_run_writes_handoff_artifacts(tmp_path: Path) -> None:
    result = run_cli(
        ["--json", "dry-run", "--from", "fake:source-1", "--to", "fake:target-1", "--cwd", str(tmp_path)],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    artifact_dir = Path(payload["artifact_dir"])
    assert (artifact_dir / "handoff.json").exists()
    assert (artifact_dir / "prompt.md").exists()
    bundle = json.loads((artifact_dir / "handoff.json").read_text())
    assert bundle["schema_version"] == "agent-xfer.handoff.v1"
    assert bundle["redaction_report"]["mode"] == "secrets"


def test_sync_requires_confirm(tmp_path: Path) -> None:
    result = run_cli(
        ["--json", "sync", "--from", "fake:source-1", "--to", "fake:target-1", "--cwd", str(tmp_path)],
        tmp_path,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["code"] == "CONFIRM_REQUIRED"


def test_sync_confirm_writes_checkpoint_and_blocks_duplicate(tmp_path: Path) -> None:
    args = [
        "--json",
        "sync",
        "--from",
        "fake:source-1",
        "--to",
        "fake:target-1",
        "--cwd",
        str(tmp_path),
        "--confirm",
    ]
    first = run_cli(args, tmp_path)
    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout)
    assert Path(payload["checkpoint"]).exists()
    assert Path(payload["artifact_dir"], "target.prompt.md").exists()

    second = run_cli(args, tmp_path)
    assert second.returncode == 2
    duplicate = json.loads(second.stdout)
    assert duplicate["code"] == "DUPLICATE_HANDOFF_BLOCKED"


def test_sh_wrapper_matches_python_module(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [str(root / "bin" / "agent-xfer"), "--json", "doctor", "--cwd", str(tmp_path)],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_dry_run_since_last_records_range_without_checkpoint(tmp_path: Path) -> None:
    result = run_cli(
        [
            "--json",
            "dry-run",
            "--from",
            "fake:source-1",
            "--to",
            "fake:target-1",
            "--cwd",
            str(tmp_path),
            "--range",
            "since-last",
        ],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    bundle = json.loads(Path(payload["artifact_dir"], "handoff.json").read_text(encoding="utf-8"))
    assert bundle["source"]["range"] == {"mode": "since-last", "from_sequence": 0, "to_sequence": 1, "event_count": 2}


def test_since_last_blocks_when_checkpoint_has_no_new_events(tmp_path: Path) -> None:
    first = run_cli(
        [
            "--json",
            "sync",
            "--from",
            "fake:source-1",
            "--to",
            "fake:target-1",
            "--cwd",
            str(tmp_path),
            "--confirm",
        ],
        tmp_path,
    )
    assert first.returncode == 0, first.stderr
    checkpoint = json.loads(Path(json.loads(first.stdout)["checkpoint"]).read_text(encoding="utf-8"))
    assert checkpoint["last_source_range"] == {"mode": "all", "from_sequence": 0, "to_sequence": 1, "event_count": 2}

    second = run_cli(
        [
            "--json",
            "dry-run",
            "--from",
            "fake:source-1",
            "--to",
            "fake:target-1",
            "--cwd",
            str(tmp_path),
            "--range",
            "since-last",
        ],
        tmp_path,
    )
    assert second.returncode == 2
    payload = json.loads(second.stdout)
    assert payload["code"] == "NO_NEW_EVENTS"


def test_since_last_rejects_legacy_checkpoint_without_range(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / ".agent-xfer" / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "fake__source-1__fake__target-1.json").write_text(
        json.dumps(
            {
                "schema_version": "agent-xfer.checkpoint.v1",
                "source": {"provider": "fake", "id": "source-1", "id_kind": "session_id"},
                "target": {"provider": "fake", "id": "target-1", "id_kind": "session_id"},
                "last_handoff_id": "sha256:legacy",
                "sent_at": "2026-06-10T00:00:00Z",
                "send_method": "fake-artifact-write",
                "artifact_dir": ".agent-xfer/handoffs/legacy",
            }
        ),
        encoding="utf-8",
    )

    result = run_cli(
        [
            "--json",
            "dry-run",
            "--from",
            "fake:source-1",
            "--to",
            "fake:target-1",
            "--cwd",
            str(tmp_path),
            "--range",
            "since-last",
        ],
        tmp_path,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["code"] == "CHECKPOINT_RANGE_UNAVAILABLE"


def test_export_writes_requested_bundle_and_prompt_paths_without_checkpoint(tmp_path: Path) -> None:
    out = tmp_path / "exports" / "handoff.json"
    prompt_out = tmp_path / "exports" / "prompt.md"
    result = run_cli(
        [
            "--json",
            "export",
            "--from",
            "fake:source-1",
            "--cwd",
            str(tmp_path),
            "--out",
            str(out),
            "--prompt-out",
            str(prompt_out),
        ],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["out"] == str(out)
    assert payload["prompt_out"] == str(prompt_out)
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert exported["schema_version"] == "agent-xfer.handoff.v1"
    assert exported["source"]["provider"] == "fake"
    assert exported["target"] == {
        "provider": "fake",
        "id": "export-target",
        "id_kind": "session_id",
        "cwd": str(tmp_path.resolve()),
        "send_method": "pending-send",
    }
    assert "# Agent Handoff" in prompt_out.read_text(encoding="utf-8")
    assert not (tmp_path / ".agent-xfer" / "checkpoints").exists()
