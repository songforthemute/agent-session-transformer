#!/bin/sh
set -eu

usage() {
  cat <<'USAGE'
Usage:
  scripts/live-smoke.sh --from <provider:id> --to <provider:id> --cwd <repo> [--sync]
  scripts/live-smoke.sh --matrix <file>

Default mode runs dry-run only and does not mutate a target session.
Pass --sync to run sync --confirm after dry-run.

Matrix file format is whitespace-separated, one case per line:
  <from> <to> <cwd> [sync]
Blank lines and lines starting with # are ignored.

Examples:
  scripts/live-smoke.sh --from grok:<session_id> --to codex:<thread_id> --cwd /repo
  scripts/live-smoke.sh --from codex:<thread_id> --to antigravity:<conversation_id> --cwd /repo --sync
  scripts/live-smoke.sh --matrix work/live-matrix.txt
USAGE
}

FROM=""
TO=""
CWD=""
MATRIX=""
DO_SYNC=0
MAX_PROMPT_CHARS="${AGENT_XFER_LIVE_MAX_PROMPT_CHARS:-4000}"
PYTHON="${AGENT_XFER_PYTHON:-python3}"

run_one() {
  from_ref="$1"
  to_ref="$2"
  cwd_path="$3"
  sync_flag="$4"
  set -x
  "$PYTHON" -m agent_xfer --json dry-run \
    --from "$from_ref" \
    --to "$to_ref" \
    --cwd "$cwd_path" \
    --max-prompt-chars "$MAX_PROMPT_CHARS"
  set +x

  if [ "$sync_flag" -eq 1 ]; then
    set -x
    "$PYTHON" -m agent_xfer --json sync \
      --from "$from_ref" \
      --to "$to_ref" \
      --cwd "$cwd_path" \
      --confirm \
      --max-prompt-chars "$MAX_PROMPT_CHARS"
    set +x
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --from)
      FROM="${2:-}"; shift 2 ;;
    --to)
      TO="${2:-}"; shift 2 ;;
    --cwd)
      CWD="${2:-}"; shift 2 ;;
    --matrix)
      MATRIX="${2:-}"; shift 2 ;;
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

if [ -n "$MATRIX" ]; then
  if [ ! -f "$MATRIX" ]; then
    echo "Matrix file not found: $MATRIX" >&2
    exit 2
  fi
  while read -r matrix_from matrix_to matrix_cwd matrix_mode rest; do
    case "${matrix_from:-}" in
      ""|\#*) continue ;;
    esac
    if [ -z "${matrix_to:-}" ] || [ -z "${matrix_cwd:-}" ]; then
      echo "Invalid matrix row: $matrix_from ${matrix_to:-} ${matrix_cwd:-}" >&2
      exit 2
    fi
    row_sync=0
    if [ "${matrix_mode:-}" = "sync" ]; then
      row_sync=1
    fi
    run_one "$matrix_from" "$matrix_to" "$matrix_cwd" "$row_sync"
  done < "$MATRIX"
  exit 0
fi

if [ -z "$FROM" ] || [ -z "$TO" ] || [ -z "$CWD" ]; then
  usage >&2
  exit 2
fi

run_one "$FROM" "$TO" "$CWD" "$DO_SYNC"
