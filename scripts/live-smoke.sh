#!/bin/sh
set -eu

usage() {
  cat <<'USAGE'
Usage:
  scripts/live-smoke.sh --from <provider:id> --to <provider:id> --cwd <repo> [--sync]

Default mode runs dry-run only and does not mutate a target session.
Pass --sync to run sync --confirm after dry-run.

Examples:
  scripts/live-smoke.sh --from grok:<session_id> --to codex:<thread_id> --cwd /repo
  scripts/live-smoke.sh --from codex:<thread_id> --to antigravity:<conversation_id> --cwd /repo --sync
USAGE
}

FROM=""
TO=""
CWD=""
DO_SYNC=0
MAX_PROMPT_CHARS="${AGENT_XFER_LIVE_MAX_PROMPT_CHARS:-4000}"
PYTHON="${AGENT_XFER_PYTHON:-python3}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --from)
      FROM="${2:-}"; shift 2 ;;
    --to)
      TO="${2:-}"; shift 2 ;;
    --cwd)
      CWD="${2:-}"; shift 2 ;;
    --sync)
      DO_SYNC=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2 ;;
  esac
done

if [ -z "$FROM" ] || [ -z "$TO" ] || [ -z "$CWD" ]; then
  usage >&2
  exit 2
fi

set -x
"$PYTHON" -m agent_xfer --json dry-run \
  --from "$FROM" \
  --to "$TO" \
  --cwd "$CWD" \
  --max-prompt-chars "$MAX_PROMPT_CHARS"

if [ "$DO_SYNC" -eq 1 ]; then
  "$PYTHON" -m agent_xfer --json sync \
    --from "$FROM" \
    --to "$TO" \
    --cwd "$CWD" \
    --confirm \
    --max-prompt-chars "$MAX_PROMPT_CHARS"
fi
