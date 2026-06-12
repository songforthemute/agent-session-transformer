from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent_xfer.core.discovery import discover_sources, discover_targets
from agent_xfer.core.ids import ProviderRef
from agent_xfer.core.orchestrator import AgentXferError, build_handoff, doctor, inspect, sync


def _print(data: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            print(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
        else:
            print(f"{key}: {value}")


def _provider_ref(value: str) -> ProviderRef:
    try:
        return ProviderRef.parse(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _copy_text(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-xfer", description="Cross-agent session handoff CLI")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor_parser = sub.add_parser("doctor", help="check local agent-xfer environment")
    doctor_parser.add_argument("--cwd", type=Path, default=Path.cwd())

    inspect_parser = sub.add_parser("inspect", help="inspect a source session")
    inspect_parser.add_argument("--source", required=True, type=_provider_ref)
    inspect_parser.add_argument("--cwd", type=Path, default=Path.cwd())

    dry_run_parser = sub.add_parser("dry-run", help="build a handoff bundle without target mutation")
    dry_run_parser.add_argument("--from", dest="source", required=True, type=_provider_ref)
    dry_run_parser.add_argument("--to", dest="target", required=True, type=_provider_ref)
    dry_run_parser.add_argument("--cwd", type=Path, default=Path.cwd())
    dry_run_parser.add_argument("--redact", choices=["secrets", "strict"], default="secrets")
    dry_run_parser.add_argument("--max-prompt-chars", type=int, default=None, help="maximum generated prompt size")
    dry_run_parser.add_argument("--range", choices=["all", "since-last"], default="all", help="source event range to include")

    export_parser = sub.add_parser("export", help="build and copy a handoff bundle to an explicit output path")
    export_parser.add_argument("--from", dest="source", required=True, type=_provider_ref)
    export_parser.add_argument("--to", dest="target", type=_provider_ref, default=ProviderRef.parse("fake:export-target"), help="target context for prompt rendering; defaults to fake:export-target")
    export_parser.add_argument("--cwd", type=Path, default=Path.cwd())
    export_parser.add_argument("--out", required=True, type=Path, help="destination handoff JSON path")
    export_parser.add_argument("--prompt-out", type=Path, default=None, help="optional destination prompt Markdown path")
    export_parser.add_argument("--redact", choices=["secrets", "strict"], default="secrets")
    export_parser.add_argument("--max-prompt-chars", type=int, default=None, help="maximum generated prompt size")
    export_parser.add_argument("--range", choices=["all", "since-last"], default="all", help="source event range to include")

    sync_parser = sub.add_parser("sync", help="send a handoff prompt to a target session")
    sync_parser.add_argument("--from", dest="source", required=True, type=_provider_ref)
    sync_parser.add_argument("--to", dest="target", required=True, type=_provider_ref)
    sync_parser.add_argument("--cwd", type=Path, default=Path.cwd())
    sync_parser.add_argument("--confirm", action="store_true", help="allow target mutation")
    sync_parser.add_argument("--allow-duplicate", action="store_true", help="bypass duplicate checkpoint guard")
    sync_parser.add_argument("--max-prompt-chars", type=int, default=None, help="maximum generated prompt size")
    sync_parser.add_argument("--range", choices=["all", "since-last"], default="all", help="source event range to include")

    sources_parser = sub.add_parser("sources", help="list discoverable source sessions or hints")
    sources_parser.add_argument("--cwd", type=Path, default=Path.cwd())
    sources_parser.add_argument("--deep", action="store_true", help="attempt provider-specific local session discovery")

    targets_parser = sub.add_parser("targets", help="list target providers or hints")
    targets_parser.add_argument("--cwd", type=Path, default=Path.cwd())

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            _print(doctor(args.cwd), args.json)
        elif args.command == "inspect":
            _print(inspect(args.source, args.cwd), args.json)
        elif args.command == "dry-run":
            bundle = build_handoff(args.source, args.target, args.cwd, args.redact, args.max_prompt_chars, args.range)
            _print({"ok": True, "handoff_id": bundle["handoff_id"], "artifact_dir": bundle["artifact_dir"]}, args.json)
        elif args.command == "export":
            bundle = build_handoff(args.source, args.target, args.cwd, args.redact, args.max_prompt_chars, args.range)
            artifact_dir = Path(bundle["artifact_dir"])
            _copy_text(artifact_dir / "handoff.json", args.out)
            prompt_out = None
            if args.prompt_out is not None:
                _copy_text(artifact_dir / "prompt.md", args.prompt_out)
                prompt_out = str(args.prompt_out)
            _print({"ok": True, "handoff_id": bundle["handoff_id"], "artifact_dir": bundle["artifact_dir"], "out": str(args.out), "prompt_out": prompt_out}, args.json)
        elif args.command == "sync":
            _print(sync(args.source, args.target, args.cwd, args.confirm, args.allow_duplicate, args.max_prompt_chars, args.range), args.json)
        elif args.command == "sources":
            _print({"ok": True, "sources": discover_sources(args.cwd, args.deep)}, args.json)
        elif args.command == "targets":
            _print({"ok": True, "targets": discover_targets(args.cwd)}, args.json)
        else:
            parser.error(f"unknown command {args.command}")
    except AgentXferError as exc:
        payload = {"ok": False, "code": exc.code, "message": exc.message}
        _print(payload, args.json)
        return 2
    except NotImplementedError as exc:
        payload = {"ok": False, "code": "PROVIDER_NOT_IMPLEMENTED", "message": str(exc)}
        _print(payload, args.json)
        return 2
    except ValueError as exc:
        payload = {"ok": False, "code": "INVALID_INPUT", "message": str(exc)}
        _print(payload, args.json)
        return 2
    except FileNotFoundError as exc:
        payload = {"ok": False, "code": "LOCAL_TRANSCRIPT_NOT_FOUND", "message": str(exc)}
        _print(payload, args.json)
        return 2
    except OSError as exc:
        payload = {"ok": False, "code": "LOCAL_IO_ERROR", "message": str(exc)}
        _print(payload, args.json)
        return 2
    except RuntimeError as exc:
        payload = {"ok": False, "code": "OPERATION_FAILED", "message": str(exc)}
        _print(payload, args.json)
        return 2
    return 0
