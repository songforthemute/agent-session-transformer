# agent-session-transformer

Design and implementation materials for `agent-xfer`, a cross-agent session handoff CLI. The MVP uses a Python core with a thin POSIX sh launcher; JavaScript/TypeScript packaging is deferred to a later roadmap phase.

## Documents

- [Cross-Agent Session Bridge investigation](docs/session-handoff-investigation.md)
- [agent-xfer PRD / design / roadmap](docs/agent-xfer-prd-design-roadmap.md)

## Milestone 1: local dry-run skeleton

The current implementation provides the first milestone skeleton with a fake provider. It does not call real provider CLIs or mutate real target sessions yet.

```bash
python3 -m agent_xfer doctor --cwd .
./bin/agent-xfer doctor --cwd .
python3 -m agent_xfer inspect --source fake:source-1 --cwd .
python3 -m agent_xfer dry-run --from fake:source-1 --to fake:target-1 --cwd .
python3 -m agent_xfer sync --from fake:source-1 --to fake:target-1 --cwd . --confirm
```

`dry-run` and fake `sync --confirm` write artifacts under `.agent-xfer/`, including `handoff.json`, `prompt.md`, and checkpoint files.

## Milestone 2: fixture parser MVP

The next milestone adds fixture-backed source parsers for provider transcript shapes without requiring real provider CLIs:

- Grok Build `grok export` Markdown transcripts.
- Antigravity `transcript_full.jsonl` / `transcript.jsonl` style JSONL events.
- Codex app-server `thread/read includeTurns` style JSON payloads.

Run the parser and skeleton tests with:

```bash
pytest -q
```

## Milestone 3: read-only provider inspect adapters

Read-only source adapters are now available for local inspection and dry-run flows:
- `grok:<session_id>` uses `grok export <session_id>` and parses Markdown output.
- `antigravity:<conversation_id>` reads transcript JSONL from `~/.gemini/antigravity-cli` or `AGENT_XFER_ANTIGRAVITY_HOME`.
- `codex:<thread_id>` currently supports a read-only `thread/read` JSON payload via `AGENT_XFER_CODEX_THREAD_READ_JSON` while live app-server wiring remains a later step.
These adapters do not send prompts to real target sessions in this milestone; `sync --confirm` remains limited to `fake:<target_id>`.

## Milestone 4: redaction and prompt budget

The handoff pipeline now applies stronger redaction before prompt rendering and records redaction findings with hashed samples rather than secret values. It also supports prompt budgeting:

```bash
python3 -m agent_xfer dry-run \
  --from fake:source-1 \
  --to fake:target-1 \
  --cwd . \
  --redact strict \
  --max-prompt-chars 1200
```

The generated `handoff.json` includes `redaction_report` and `prompt_budget` metadata.

## Milestone 5: target send adapters

`sync --confirm` can now invoke target resume commands for the MVP providers when their CLIs are available:

- `codex:<thread_id>` -> `codex exec resume <thread_id> <prompt>`
- `grok:<session_id>` -> `grok -r <session_id> -p <prompt> --cwd <cwd>`
- `antigravity:<conversation_id>` -> `agy --conversation <conversation_id> --print <prompt> --print-timeout 30s`
Tests use mocked executables; live provider smoke tests remain opt-in and are not required in cloud environments.

## Milestone 6: opt-in live smoke harness

Live provider smoke is now separated from the default test suite. By default, live tests are skipped and no real provider session is mutated.

Dry-run only:

```bash
AGENT_XFER_LIVE=1 AGENT_XFER_LIVE_CWD=/repo AGENT_XFER_LIVE_FROM=grok:<source_session_id> AGENT_XFER_LIVE_TO=codex:<target_thread_id> pytest -m live
```

Dry-run plus real target mutation:
```bash
AGENT_XFER_LIVE=1 AGENT_XFER_LIVE_CONFIRM_SYNC=1 AGENT_XFER_LIVE_CWD=/repo AGENT_XFER_LIVE_FROM=grok:<source_session_id> AGENT_XFER_LIVE_TO=codex:<target_thread_id> pytest -m live
```

A shell helper is also available:

```bash
scripts/live-smoke.sh --from grok:<source_session_id> --to codex:<target_thread_id> --cwd /repo
scripts/live-smoke.sh --from grok:<source_session_id> --to codex:<target_thread_id> --cwd /repo --sync
```

## Milestone 7: Claude optional adapter

Claude support is now wired as an experimental/optional adapter:

- `claude:<session_id>` source reads use `AGENT_XFER_CLAUDE_TRANSCRIPT` when set, otherwise a best-effort `CLAUDE_CONFIG_DIR` / `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` fallback.
- `claude:<target_session_id>` target sends invoke `claude --resume <target_session_id> -p <prompt>`.

The default tests use fixtures and mocked executables. Login-dependent Claude live smoke remains opt-in.

## Milestone 8: Grok trace archive source

Grok source reads now support an opt-in trace archive path for richer local artifacts without rerunning `grok trace` inside Cloud/test environments:

```bash
AGENT_XFER_GROK_TRACE_ARCHIVE=/path/to/grok-trace.tar.gz \
  python3 -m agent_xfer inspect --source grok:<session_id> --cwd /repo
```
When this environment variable is set, the Grok adapter parses `chat_history.jsonl` from the archive first and falls back to Markdown-like text in `summary.json`. Without the variable, the adapter keeps the existing `grok export <session_id>` behavior.

## Milestone 9: source range selection

`dry-run` and `sync` now accept `--range all|since-last`. The default `all` behavior is unchanged. `since-last` reads the last checkpoint for the exact source/target pair, includes only events after the checkpoint's `last_source_range.to_sequence`, and fails safely with `NO_NEW_EVENTS` when there is nothing new to hand off.

```bash
python3 -m agent_xfer --json dry-run \
  --from fake:source-1 --to fake:target-1 --cwd /repo --range since-last
```
Checkpoints now persist `last_source_range` so later incremental handoffs can be deterministic and duplicate-safe.

## Milestone 10: Antigravity resolver hardening

Antigravity sources now support convenience aliases for the current workspace mapping:

```bash
python3 -m agent_xfer --json inspect --source antigravity:last --cwd /repo
```
The aliases `last`, `cwd`, and `current` resolve through `cache/last_conversations.json` under `AGENT_XFER_ANTIGRAVITY_HOME` or the default `~/.gemini/antigravity-cli` home. Tests can also set `AGENT_XFER_ANTIGRAVITY_TRANSCRIPT=/path/to/transcript_full.jsonl` to exercise the parser without creating the full Antigravity directory tree.

## Milestone 11: Codex app-server command source

Codex source reads can now use an explicit app-server command instead of only a saved fixture payload:

```bash
AGENT_XFER_CODEX_APP_SERVER_COMMAND="codex app-server" \
  python3 -m agent_xfer --json inspect --source codex:<thread_id> --cwd /repo
```
The adapter sends a single JSON-RPC `thread/read` request with `includeTurns: true`, parses a line-delimited JSON response, and normalizes the returned payload with the existing Codex parser. `AGENT_XFER_CODEX_THREAD_READ_JSON` remains supported and takes precedence for deterministic fixture reads.

## Milestone 12: Python packaging entrypoint

The Python core can now be installed as a package using the repository `pyproject.toml`. The installed console script points at the same CLI implementation as `python3 -m agent_xfer` and the POSIX `bin/agent-xfer` shim:

```bash
python3 -m pip install -e .
agent-xfer doctor --cwd .
```
The sh launcher remains useful for checkout-only usage, while packaging gives follow-up milestones a standard Python distribution surface before any future JavaScript/TypeScript wrapper is considered.

## Milestone 13: schema constants and checkpoint range guard

Schema/version strings are now centralized in code and reported by `agent-xfer doctor` so downstream scripts can detect compatible artifact formats:

```bash
python3 -m agent_xfer --json doctor --cwd .
```
`--range since-last` now refuses legacy checkpoints that do not contain `last_source_range.to_sequence` and returns `CHECKPOINT_RANGE_UNAVAILABLE` instead of silently re-sending the full source range. Use `--range all` once to create a fresh range-aware checkpoint.

## Milestone 14: explicit export command

`agent-xfer export` now copies a generated handoff bundle to a caller-chosen path without sending anything to a target or writing a checkpoint:

```bash
python3 -m agent_xfer --json export \
  --from fake:source-1 \
  --cwd /repo \
  --out /tmp/handoff.json \
  --prompt-out /tmp/prompt.md
```
`--to` is optional for export and defaults to `fake:export-target` only as prompt-rendering context. Supplying a real `--to <provider>:<id>` is supported when the exported prompt should name a specific target session, but export still remains read-only.

## Discovery helpers

`agent-xfer sources` and `agent-xfer targets` provide lightweight discovery and availability hints:

```bash
python3 -m agent_xfer --json sources --cwd /repo
python3 -m agent_xfer --json targets --cwd /repo
```

Discovery is intentionally shallow: it reports fake defaults, CLI availability, environment-backed fixture paths, and Antigravity `last_conversations.json` cwd matches. Provider IDs should still be supplied explicitly for real sync flows.
