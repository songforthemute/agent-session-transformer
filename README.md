# agent-session-transformer

`agent-xfer` is a Python-core, POSIX-shell-launchable CLI for safe cross-agent session handoff between local coding agents. It reads a source session, normalizes events, redacts sensitive content, renders a continuation prompt, and can optionally resume a target session through provider adapters.

## Documents

- [Cross-Agent Session Bridge investigation](docs/session-handoff-investigation.md)
- [agent-xfer PRD / design / roadmap](docs/agent-xfer-prd-design-roadmap.md)

## Quick start

Run from a checkout without installing:

```bash
python3 -m agent_xfer --json doctor --cwd .
./bin/agent-xfer --json doctor --cwd .
```

Build a local handoff without target mutation:

```bash
python3 -m agent_xfer --json dry-run \
  --from fake:source-1 \
  --to fake:target-1 \
  --cwd .
```

Export a redacted handoff bundle to explicit paths:

```bash
python3 -m agent_xfer --json export \
  --from fake:source-1 \
  --cwd . \
  --out /tmp/handoff.json \
  --prompt-out /tmp/prompt.md
```

Run a guarded fake sync:

```bash
python3 -m agent_xfer --json sync \
  --from fake:source-1 \
  --to fake:target-1 \
  --cwd . \
  --confirm
```

## Implemented scope

- CLI commands: `doctor`, `inspect`, `dry-run`, `export`, `sync`, `sources`, and `targets`.
- Provider adapters: `fake`, `grok`, `codex`, `antigravity`, and optional `claude`.
- Parsers: Grok Markdown/trace archives, Codex `thread/read`, Antigravity JSONL, Claude JSONL, and tolerant JSONL utilities.
- Safety features: mandatory redaction, prompt budgeting, duplicate checkpoint guard, source ranges, schema constants, and prompt-argv size guard.
- Tooling: `pyproject.toml` console script metadata, `bin/agent-xfer`, fixture tests, and opt-in live smoke helpers.

## Discovery and live smoke

Use shallow or best-effort deep source discovery:

```bash
python3 -m agent_xfer --json sources --cwd .
python3 -m agent_xfer --json sources --cwd . --deep
python3 -m agent_xfer --json targets --cwd .
```

Live smoke remains opt-in. A matrix file row is `<from> <to> <cwd> [sync]`; rows without `sync` stay read-only:

```bash
scripts/live-smoke.sh --matrix work/live-matrix.txt
```

## Development checks

```bash
python3 -m compileall -q agent_xfer
pytest -q
sh -n scripts/live-smoke.sh
git diff --check
```

## Conflict note

This README is intentionally concise to reduce PR conflicts. Detailed milestone history, release planning, and provider-specific design notes live in the linked docs.
