# Cross-Agent Session Bridge 최종 설계안

작성일: 2026-06-10

이 문서는 Claude Code, Codex, Grok Build, Antigravity CLI 사이에서 특정 세션 단위 작업 기록을 이전하는 `agent-xfer` CLI의 최종 설계안이다. Grok Build와 Antigravity CLI에 대해서는 사용자의 로컬 Mac에서 이미 완료된 검증 결과를 신뢰된 입력값으로 사용한다. Cloud 환경에서 `grok`, `agy`, `antigravity`, `claude` CLI를 재실행해 재검증하지 않는다.

## 1. 결론

### 1.1 최종 판단

`agent-xfer`는 **구현 가능**하다. 단, 목표는 각 provider의 내부 세션 파일을 완전히 변환하거나 tool call을 replay하는 것이 아니다. 현실적인 목표는 다음 파이프라인이다.

```text
source_session_id
  -> source transcript/export/read
  -> normalized event model
  -> handoff bundle
  -> target_session_id resume
  -> continuation prompt injection
```

핵심 원칙은 다음과 같다.

- **source는 읽기 전용**으로만 접근한다.
- **target은 공식 또는 로컬에서 검증된 resume 경로**로만 이어받는다.
- provider 내부 세션 파일, SQLite DB, transcript 파일을 **직접 수정하지 않는다**.
- tool call 자체를 재실행하거나 target history에 raw tool call로 주입하지 않는다.
- target에는 “이어 작업 가능한 continuation prompt”를 넣는다.
- raw transcript 전체를 target context에 무조건 붙이지 않고, redaction된 요약과 artifact reference 중심으로 전달한다.

### 1.2 Provider별 MVP 포함 판단

| Provider | Source Read | Target Resume | MVP 판단 | 비고 |
|---|---|---|---|---|
| Codex | 강함 | 강함 | **포함** | app-server `thread/read includeTurns`, `codex exec resume` 검증됨 |
| Grok Build | 강함 | 강함 | **포함** | `grok export`, `grok trace`, `grok -r -p` 검증됨 |
| Antigravity CLI | 가능 | 가능 | **포함** | source는 semi-private transcript JSONL 기반, target은 `agy --conversation --print` 검증됨 |
| Claude Code | 설계상 가능 | 설계상 가능 | **2차/optional** | SDK/JSONL/CLI resume 경로는 있으나 로그인 이슈로 content smoke test 미완료 |

### 1.3 구현 방향

- **MVP 구현은 Python core + POSIX sh wrapper의 이중 진입점**을 추천한다. Python은 parsing/redaction/checkpoint 핵심 로직을 맡고, sh는 설치 없이 실행 가능한 얇은 orchestration/launcher 역할만 맡는다.
- MVP provider는 **Codex, Grok Build, Antigravity CLI**로 시작한다.
- Claude Code adapter는 interface와 fixture parser까지 준비하되, live smoke는 로그인된 로컬 환경에서 2차로 검증한다.
- MVP의 핵심 성공 기준은 `dry-run`에서 handoff bundle을 만들고, `sync --confirm`에서 target session에 continuation prompt를 1회 안전하게 주입하는 것이다.

## 2. 로컬 검증 완료 사실

이 섹션의 내용은 이미 사용자의 로컬 Mac에서 검증된 사실로 취급한다.

### 2.1 검증 환경과 버전

| 도구 | 버전 | 용도 |
|---|---:|---|
| Claude Code | 2.1.170 | 설계상 source/target 후보. 로그인 미완료로 live content smoke는 optional |
| Codex CLI | 0.139.0 | MVP 핵심 provider |
| Grok Build | 0.2.3 | MVP 핵심 provider |
| Antigravity CLI | 1.0.7 | MVP 핵심 provider |
| Gemini CLI | 0.45.2 | Antigravity 저장소 구조 보조 비교 |

### 2.2 Codex 검증 결과

Codex는 source와 target 양쪽 모두 강하게 검증됐다.

확인된 target resume 경로:

```bash
codex exec resume <thread_id> "<prompt>"
```

실제 smoke test:

- 생성된 thread id: `019eb0b6-3e60-76d1-a573-6f9da5937d36`
- 첫 프롬프트: `Bridge smoke test. Remember token CODEX_BRIDGE_SMOKE_BETA. Reply with exactly: CODEX_BRIDGE_SMOKE_BETA`
- 첫 응답: `CODEX_BRIDGE_SMOKE_BETA`
- 이후 `codex exec resume 019eb0b6-3e60-76d1-a573-6f9da5937d36 ...` 실행 시 이전 token을 정확히 회수했다.

확인된 source read 경로:

- Codex app-server `thread/read includeTurns`
- `thread/read includeTurns`가 해당 thread의 `turns[]`와 `items[]`를 구조화해서 반환했다.
- `userMessage`와 `agentMessage`가 모두 읽혔다.

Codex app-server schema에서 확인된 내용:

- `ThreadReadParams.includeTurns`: `true`일 때 rollout history의 turns/items 포함.
- `ThreadResumeParams`: thread id, history, path로 resume 가능하며 가능한 경우 thread id 사용 권장.
- `ThreadInjectItemsParams.items`: raw Responses API items를 model-visible history에 append 가능.

Codex 설계 판단:

- MVP source read 1순위는 **app-server `thread/read includeTurns`**다.
- target write 1순위는 **`codex exec resume <thread_id> "<handoff prompt>"`**다.
- `thread/inject_items`는 raw history injection이므로 MVP에서는 쓰지 않는다.
- app-server `turn/start`는 장기적으로 좋은 target injection 경로지만, MVP에서는 CLI resume이 더 단순하다.

### 2.3 Grok Build 검증 결과

Grok Build는 source와 target 양쪽 모두 검증됐다.

확인된 CLI 기능:

- `-p, --single <PROMPT>`
- `-r, --resume [<SESSION_ID>]`
- `-c, --continue`
- `--cwd <CWD>`
- `--output-format plain|json|streaming-json`
- `export`
- `import`
- `trace`
- `sessions`
- `agent stdio`

실제 smoke test:

- 생성된 session id: `019eb0b8-00df-7300-aeed-4fd7e2a4b7fd`
- 첫 프롬프트: `Bridge smoke test. Remember token GROK_BRIDGE_SMOKE_GAMMA. Reply with exactly: GROK_BRIDGE_SMOKE_GAMMA`
- 첫 응답: `GROK_BRIDGE_SMOKE_GAMMA`
- 이후 `grok -r 019eb0b8-00df-7300-aeed-4fd7e2a4b7fd -p ...` 실행 시 이전 token을 정확히 회수했다.

확인된 source export:

```bash
grok export 019eb0b8-00df-7300-aeed-4fd7e2a4b7fd
```

export 결과는 다음 형태의 Markdown transcript였다.

```md
## User

Bridge smoke test. Remember token GROK_BRIDGE_SMOKE_GAMMA. Reply with exactly: GROK_BRIDGE_SMOKE_GAMMA

## Assistant

GROK_BRIDGE_SMOKE_GAMMA

## User

What exact token were you asked to remember in the previous turn? Reply with only the token.

## Assistant

GROK_BRIDGE_SMOKE_GAMMA
```

확인된 trace export:

```bash
grok trace --local --json -o work/grok-smoke-trace.tar.gz 019eb0b8-00df-7300-aeed-4fd7e2a4b7fd
```

archive 내부 파일:

- `summary.json`
- `updates.jsonl`
- `system_prompt.txt`
- `prompt_context.json`
- `events.jsonl`
- `rewind_points.jsonl`
- `chat_history.jsonl`
- `signals.json`
- `trace_config.json`
- `export_metadata.json`

Grok 설계 판단:

- source adapter 1순위는 **`grok export <source_session_id>`**다.
- 이유: 단순하고 Markdown transcript로 즉시 parsing 가능하다.
- source adapter 2순위는 **`grok trace --local --json`**이다.
- 이유: 더 풍부하지만 archive 처리와 schema drift 대응이 필요하다.
- target adapter는 **`grok -r <target_session_id> -p "<handoff prompt>"`**를 우선한다.
- `grok import`는 Grok 내부 세션 import일 가능성이 높으므로 cross-agent migration MVP에서는 제외한다.
- `grok agent stdio`/ACP는 장기적으로 검토하되 MVP에서는 CLI resume보다 복잡하므로 제외한다.

### 2.4 Antigravity CLI 검증 결과

Antigravity CLI도 source와 target 양쪽 모두 검증됐다. 다만 source read는 CLI help에 노출된 공식 export가 아니라 로컬 transcript JSONL 기반이다.

설치/실행 정보:

- Homebrew cask: `antigravity-cli`
- 실행 alias: `agy`
- 버전: `1.0.7`
- Homebrew 설명: `Terminal interface for Antigravity agents`
- product page: `https://antigravity.google/product/antigravity-cli`

`agy --help`에서 확인된 기능:

- `--continue`
- `--conversation`
- `--print`
- `--prompt`
- `--prompt-interactive`
- `--log-file`
- `--model`
- `--sandbox`
- `--add-dir`
- `plugin` subcommand

`agy plugin --help`에서 확인된 기능:

- `plugin import [source]`: gemini 또는 claude plugin import 가능.
- 단, 이것은 plugin import이지 session import가 아니다.

중요한 관찰:

- `agy --help`에는 session list/export/import 명령이 보이지 않았다.
- 따라서 Antigravity source adapter는 CLI export가 아니라 local transcript JSONL 기반으로 설계한다.

실제 smoke test:

- 첫 일반 실행은 sandbox 때문에 실패했다.
- 실패 원인: `mkdir /Users/joeylee/.gemini/antigravity-cli: operation not permitted`
- 권한 상승 후 다음 명령이 성공했다.

```bash
agy --print "Bridge smoke test. Reply with exactly: AGY_BRIDGE_SMOKE_DELTA" --print-timeout 30s --log-file work/agy-smoke-escalated.log
```

- 응답: `AGY_BRIDGE_SMOKE_DELTA`
- 로그와 cache에서 확인된 conversation id: `9d61b187-4b6d-4e4d-b286-08a3a30454e5`

확인된 target resume 경로:

```bash
agy --conversation 9d61b187-4b6d-4e4d-b286-08a3a30454e5 --print "What exact token did you output in the previous turn? Reply with only the token." --print-timeout 30s
```

- 응답: `AGY_BRIDGE_SMOKE_DELTA`
- stdout에는 같은 토큰이 두 번 찍혔지만, transcript 기준으로 resume은 정상 동작했다.

Antigravity 로컬 상태:

- app data dir: `~/.gemini/antigravity-cli`
- workspace -> last conversation mapping: `~/.gemini/antigravity-cli/cache/last_conversations.json`
- project mapping: `~/.gemini/antigravity-cli/cache/projects.json`
- conversation DB: `~/.gemini/antigravity-cli/conversations/<conversation-id>.db`
- DB는 SQLite이지만 주요 payload가 protobuf-like blob이므로 MVP source로 쓰지 않는다.

확인된 Antigravity transcript path:

- `~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/transcript_full.jsonl`
- `~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/transcript.jsonl`

실제 transcript JSONL event shape:

```json
{"step_index":0,"source":"USER_EXPLICIT","type":"USER_INPUT","status":"DONE","created_at":"2026-06-10T08:49:52Z","content":"<USER_REQUEST>\nBridge smoke test. Reply with exactly: AGY_BRIDGE_SMOKE_DELTA\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nThe current local time is: 2026-06-10T17:49:52+09:00.\n</ADDITIONAL_METADATA>"}
{"step_index":2,"source":"MODEL","type":"PLANNER_RESPONSE","status":"DONE","created_at":"2026-06-10T08:49:52Z","content":"AGY_BRIDGE_SMOKE_DELTA"}
```

Antigravity 설계 판단:

- source adapter 1순위는 `transcript_full.jsonl`이다.
- source adapter 2순위는 `transcript.jsonl`이다.
- SQLite DB parsing은 MVP에서 제외한다.
- target adapter는 **`agy --conversation <target_conversation_id> --print "<handoff prompt>"`**다.
- 새 conversation 생성이 필요하면 `agy --print "<handoff prompt>" --log-file <path>` 실행 후 log 또는 `cache/last_conversations.json`에서 conversation id를 회수한다.
- provider 이름은 `antigravity`로 두되, local path resolver는 Gemini 계열 경로인 `~/.gemini/antigravity-cli`를 알아야 한다.

### 2.5 Claude Code 참고

이번 로컬 환경에서는 Claude Code가 로그인되지 않아 content smoke test는 실패했다.

- 오류: `Not logged in · Please run /login`

하지만 CLI help와 공식 문서 기준으로 다음 경로가 있다.

- `claude --resume [value]`
- `claude --session-id <uuid>`
- `claude --continue`
- `claude --fork-session`
- `claude -p/--print`
- `--output-format text|json|stream-json`
- `--input-format text|stream-json`
- `--no-session-persistence`

로컬 transcript path:

```text
~/.claude/projects/<encoded-project-path>/<session-id>.jsonl
```

Claude Agent SDK 후보:

- `list_sessions`
- `get_session_messages`
- `get_session_info`

Claude 설계 판단:

- source adapter는 SDK 우선, JSONL fallback으로 설계한다.
- target adapter는 `claude --resume <target_session_id> -p "<handoff prompt>"`로 설계한다.
- MVP live test에서는 optional로 두고, 로그인된 로컬 환경에서 재검증한다.

## 3. Provider별 adapter 설계

### 3.1 공통 개념

각 provider adapter는 다음 세 계층을 담당한다.

1. **Discovery/health:** CLI 설치 여부, auth 상태, 로컬 transcript 접근 가능 여부, 버전 확인.
2. **Source read:** `source_id`와 `cwd`로 원본 세션 기록을 읽어 provider-neutral `NormalizedEvent[]`로 변환.
3. **Target send:** `target_id`, `cwd`, `handoff prompt`를 사용해 target session/conversation/thread에 continuation prompt 주입.

### 3.2 ProviderAdapter interface

언어 중립적인 interface 초안은 다음과 같다.

```text
ProviderAdapter:
  provider: "codex" | "grok" | "antigravity" | "claude"
  id_kind: "thread_id" | "session_id" | "conversation_id"

  capabilities:
    can_read_session: boolean
    can_resume_target: boolean
    can_send_prompt_to_target: boolean
    can_emit_machine_readable_events: boolean
    can_locate_local_transcripts: boolean
    uses_official_api: boolean
    uses_private_or_semiprivate_files: boolean
    requires_auth: boolean
    requires_local_cli: boolean

  methods:
    read_session(source_id, cwd) -> ReadSessionResult
    build_handoff(events) -> HandoffDraft
    send_handoff(target_id, prompt, cwd) -> SendResult
    inspect(source_id, cwd) -> InspectResult
    healthcheck(cwd) -> HealthcheckResult
```

### 3.3 NormalizedEvent model

Provider별 transcript 형태가 다르므로 공통 event model은 좁고 보수적으로 잡는다.

```json
{
  "event_id": "provider-local-id-or-derived-hash",
  "provider": "codex|grok|antigravity|claude",
  "source_id": "...",
  "sequence": 0,
  "created_at": "2026-06-10T00:00:00Z",
  "role": "user|assistant|system|tool|unknown",
  "kind": "message|tool_call|tool_result|command|file_change|summary|metadata|error|unknown",
  "content_text": "...",
  "content_json": {},
  "tool_name": "shell|edit|read|...",
  "command": "pytest",
  "cwd": "/repo",
  "status": "ok|error|unknown",
  "files": ["src/example.ts"],
  "raw_ref": {
    "artifact_id": "...",
    "path": "...",
    "line_start": 1,
    "line_end": 10
  }
}
```

정규화 원칙:

- role/kind를 확정할 수 없으면 `unknown`으로 두고 raw_ref를 남긴다.
- provider-specific field는 `content_json`에 보존하되 handoff prompt에는 바로 넣지 않는다.
- command, files, test result는 가능한 경우만 추출한다.
- prompt 생성은 `NormalizedEvent[]` 전체 raw content가 아니라 redaction과 summarization 이후의 bundle을 사용한다.

### 3.4 Capability matrix

| Provider | id_kind | read_session | send_handoff | machine readable | local transcript | official/observed API | semi-private files |
|---|---|---|---|---|---|---|---|
| codex | `thread_id` | app-server `thread/read includeTurns` | `codex exec resume` | 예 | rollout fallback 가능 | 공식/검증 | fallback에서만 가능성 |
| grok | `session_id` | `grok export`, `trace` | `grok -r -p` | trace는 예, export는 Markdown | trace archive | 관찰/검증 CLI | 아니오 또는 낮음 |
| antigravity | `conversation_id` | transcript JSONL | `agy --conversation --print` | 예 | `~/.gemini/antigravity-cli/brain/...` | target은 관찰/검증 CLI | **예** |
| claude | `session_id` | SDK 또는 JSONL | `claude --resume -p` | SDK/JSONL | `~/.claude/projects/...` | 설계상 공식 | JSONL fallback 시 예 |

### 3.5 Adapter별 구현 세부안

#### CodexAdapter

- `provider`: `codex`
- `id_kind`: `thread_id`
- `read_session(source_id, cwd)`:
  1. `codex app-server`를 stdio로 실행.
  2. `thread/read`에 `includeTurns: true`로 요청.
  3. `turns[]`와 `items[]`를 `NormalizedEvent[]`로 변환.
  4. 실패 시 rollout JSONL fallback은 2차로 둔다.
- `send_handoff(target_id, prompt, cwd)`:
  - `codex exec resume <target_id> <prompt>` 실행.
- `inspect`:
  - thread metadata, turns/items count, first/last timestamp, cwd mismatch 여부, source size 추정.
- `healthcheck`:
  - `codex --version`, app-server launch 가능 여부, `cwd` 존재 여부 확인.

#### GrokAdapter

- `provider`: `grok`
- `id_kind`: `session_id`
- `read_session(source_id, cwd)`:
  1. `grok export <source_id>` 실행.
  2. Markdown heading `## User`, `## Assistant` 기준으로 turn parsing.
  3. 필요 시 `grok trace --local --json -o <tmp>.tar.gz <source_id>`를 optional enrich로 실행.
- `send_handoff(target_id, prompt, cwd)`:
  - `grok -r <target_id> -p <prompt> --cwd <cwd>` 실행.
- `inspect`:
  - export 가능 여부, turn 수, Markdown parse 가능 여부, trace 사용 가능 여부.
- `healthcheck`:
  - `grok --version`, `grok sessions` 가능 여부, auth failure 여부.

#### AntigravityAdapter

- `provider`: `antigravity`
- `id_kind`: `conversation_id`
- `read_session(source_id, cwd)`:
  1. `~/.gemini/antigravity-cli/brain/<source_id>/.system_generated/logs/transcript_full.jsonl` 탐색.
  2. 없으면 `transcript.jsonl` fallback.
  3. `USER_INPUT`은 `<USER_REQUEST>...</USER_REQUEST>` 내부를 우선 추출.
  4. `PLANNER_RESPONSE` 등 model response를 assistant event로 변환.
  5. `CONVERSATION_HISTORY` 같은 metadata-only event는 metadata/summary로 낮은 우선순위 처리.
- `send_handoff(target_id, prompt, cwd)`:
  - `agy --conversation <target_id> --print <prompt> --print-timeout <duration>` 실행.
- `inspect`:
  - transcript path, line count, first/last event time, `last_conversations.json` cwd mapping과 입력 `cwd` 일치 여부.
- `healthcheck`:
  - `agy --version` 또는 `agy --help`, app data dir 접근 가능 여부 확인.

#### ClaudeAdapter

- `provider`: `claude`
- `id_kind`: `session_id`
- `read_session(source_id, cwd)`:
  1. SDK 사용 가능 시 `get_session_messages`/`get_session_info` 우선.
  2. SDK unavailable 또는 auth issue 시 `~/.claude/projects/<encoded-project-path>/<session-id>.jsonl` read-only fallback.
- `send_handoff(target_id, prompt, cwd)`:
  - `claude --resume <target_id> -p <prompt>` 실행.
- `inspect`:
  - SDK session info 또는 JSONL path 존재 여부, line count, auth 상태.
- `healthcheck`:
  - `claude --version`, login status, SDK import 가능 여부.

## 4. CLI UX

### 4.1 기본 command set

```bash
agent-xfer inspect --source grok:<session_id> --cwd /repo
agent-xfer inspect --source antigravity:<conversation_id> --cwd /repo
agent-xfer inspect --source codex:<thread_id> --cwd /repo
agent-xfer inspect --source claude:<session_id> --cwd /repo

agent-xfer dry-run \
  --from grok:<session_id> \
  --to codex:<thread_id> \
  --cwd /repo

agent-xfer sync \
  --from codex:<thread_id> \
  --to antigravity:<conversation_id> \
  --cwd /repo \
  --confirm

agent-xfer sources --cwd /repo
agent-xfer targets --cwd /repo
agent-xfer doctor --cwd /repo
```

### 4.2 Sync 예시

```bash
agent-xfer sync \
  --from grok:019eb0b8-00df-7300-aeed-4fd7e2a4b7fd \
  --to codex:<target_thread_id> \
  --cwd /path/to/repo \
  --confirm
```

```bash
agent-xfer sync \
  --from antigravity:9d61b187-4b6d-4e4d-b286-08a3a30454e5 \
  --to grok:<target_session_id> \
  --cwd /path/to/repo \
  --confirm
```

```bash
agent-xfer dry-run \
  --from codex:<source_thread_id> \
  --to antigravity:<target_conversation_id> \
  --cwd /path/to/repo
```

### 4.3 옵션 초안

```text
Global:
  --cwd <path>                  repo/workspace path
  --config <path>               optional config file
  --verbose                     verbose logs
  --json                        machine-readable command output

Read/summarize:
  --range all|since-last        source range selection
  --since-checkpoint <id>       explicit checkpoint
  --include-raw                 write raw redacted artifacts, never inline all raw by default
  --max-prompt-chars <n>        target prompt budget
  --redact secrets|strict|off   redaction mode; off requires explicit unsafe flag

Write/sync:
  --confirm                     required for target mutation
  --dry-run                     build bundle and prompt, do not send
  --checkpoint                  write checkpoint after successful send
  --no-checkpoint               skip checkpoint write
  --allow-duplicate             bypass duplicate handoff hash guard
```

### 4.4 Command behavior

- `inspect`: source session을 읽을 수 있는지, event 수, created/updated time, cwd mismatch, raw artifact path를 보여준다.
- `dry-run`: source read, normalization, redaction, handoff prompt 생성까지 수행하지만 target에 보내지 않는다.
- `sync`: `dry-run` pipeline 후 `--confirm`이 있을 때만 target에 prompt를 주입한다.
- `sources`: cwd 기준으로 provider별 최근 source 후보를 나열한다. Codex/Grok은 CLI/API, Antigravity는 `last_conversations.json`, Claude는 SDK/JSONL을 사용한다.
- `targets`: resume 가능한 target 후보를 provider별로 나열한다. 없는 provider는 reason을 표시한다.
- `doctor`: CLI 설치, auth, transcript directory, app-server availability, write permission, redaction config를 점검한다.

### 4.5 Default safety UX

- `sync`는 기본적으로 target mutation을 막고 `--confirm`을 요구한다.
- target prompt 전송 전 handoff hash를 계산해 checkpoint와 비교한다.
- 같은 source range와 target id 조합이 이미 전송된 경우 기본 차단한다.
- redaction `off`는 `--allow-unsafe-redaction-off` 같은 별도 explicit flag 없이는 허용하지 않는다.

## 5. Handoff bundle schema

### 5.1 JSON schema 초안

```json
{
  "schema_version": "agent-xfer.handoff.v1",
  "created_at": "2026-06-10T00:00:00Z",
  "handoff_id": "sha256:...",
  "source": {
    "provider": "codex|grok|antigravity|claude",
    "id": "...",
    "id_kind": "thread_id|session_id|conversation_id",
    "cwd": "/repo",
    "created_at": "2026-06-10T00:00:00Z",
    "updated_at": "2026-06-10T00:10:00Z",
    "read_method": "app-server-thread-read|grok-export|grok-trace|antigravity-jsonl|claude-sdk|claude-jsonl",
    "range": {
      "mode": "all|since-last",
      "from_sequence": 0,
      "to_sequence": 100,
      "checkpoint_id": "..."
    }
  },
  "target": {
    "provider": "codex|grok|antigravity|claude",
    "id": "...",
    "id_kind": "thread_id|session_id|conversation_id",
    "cwd": "/repo",
    "send_method": "codex-exec-resume|grok-resume-p|agy-conversation-print|claude-resume-p"
  },
  "original_user_goal": "...",
  "current_state": "...",
  "completed_work": ["..."],
  "pending_work": ["..."],
  "decisions": ["..."],
  "assumptions": ["..."],
  "files_touched": [
    {
      "path": "src/example.py",
      "operation": "read|modified|created|deleted|unknown",
      "evidence": "event ids or git status"
    }
  ],
  "commands_run": [
    {
      "command": "pytest",
      "cwd": "/repo",
      "status": "passed|failed|unknown",
      "exit_code": 0,
      "summary": "...",
      "event_refs": ["..."]
    }
  ],
  "tests_and_verification": [
    {
      "name": "unit tests",
      "command": "pytest",
      "result": "passed|failed|not_run|unknown",
      "notes": "..."
    }
  ],
  "blockers": ["..."],
  "git": {
    "branch": "feature/session-bridge",
    "head": "abc123",
    "status_porcelain": "...",
    "diff_summary": "...",
    "untracked_files": ["..."]
  },
  "raw_artifact_references": [
    {
      "kind": "source-transcript|export|trace|redacted-copy|bundle",
      "path": "/path/to/artifact",
      "redacted": true,
      "sha256": "...",
      "notes": "Do not paste entire artifact into target prompt by default."
    }
  ],
  "redaction_report": {
    "mode": "secrets|strict|off",
    "started_at": "2026-06-10T00:00:00Z",
    "completed_at": "2026-06-10T00:00:01Z",
    "findings": [
      {
        "kind": "api_key|oauth_token|email|internal_path|env_var|private_key|high_entropy|unknown",
        "count": 1,
        "action": "masked|dropped|hashed|kept",
        "sample_hash": "sha256:..."
      }
    ],
    "dropped_raw_event_count": 0,
    "notes": ["..."]
  },
  "generated_handoff_prompt": "..."
}
```

### 5.2 Generated handoff prompt 구성

Target에 실제로 보내는 prompt는 다음 섹션을 갖는다.

```md
# Agent Handoff

You are resuming work that was started in another coding agent.
Do not assume this is a lossless transcript conversion. Treat it as a task handoff summary.
Do not replay tool calls. Continue from the current repository state.

## Source
- Provider: grok
- Source session id: ...
- CWD: /repo

## Original user goal
...

## Current state
...

## Completed work
- ...

## Pending work
- ...

## Decisions and assumptions
- ...

## Files touched
- ...

## Commands/tests
- ...

## Blockers/errors
- ...

## Git state
- Branch: ...
- HEAD: ...
- Status summary: ...

## Raw artifacts
- Redacted bundle: /path/to/handoff.json
- Source transcript reference: /path/to/redacted-transcript.md

## Instructions for you
1. First inspect the repo state before editing.
2. Respect the target session's existing instructions.
3. Continue the pending work; do not repeat completed work unless verification requires it.
```

## 6. Redaction/security 설계

### 6.1 Threat model

Transcript와 tool result에는 다음 민감 정보가 섞일 수 있다.

- OAuth token, refresh token, bearer token.
- API key, provider-specific key prefix.
- `.env` dump, shell environment variables.
- 사용자 이메일, username, 내부 hostname.
- 회사 내부 path, private repository URL.
- command output에 포함된 secret.
- tool result 안의 file content, 로그, stack trace.

### 6.2 Redaction pipeline

```text
raw events
  -> structural parser
  -> secret scanner
  -> PII/path scanner
  -> policy action(mask/drop/hash)
  -> redacted normalized events
  -> handoff summarizer
  -> generated_handoff_prompt
```

Redaction은 handoff prompt 생성 **전**에 반드시 수행한다.

### 6.3 Redaction policy

| Finding | 기본 action | 설명 |
|---|---|---|
| API key/token | `masked` | prefix와 마지막 4자 정도만 보존하거나 전체 mask |
| Private key block | `dropped` | prompt에 포함 금지 |
| `.env` dump | `dropped` 또는 key name만 보존 | 값은 제거 |
| Email | `masked` | strict mode에서는 hash만 남김 |
| Internal absolute path | `masked` | repo-relative path는 보존, home path는 `~` 또는 hash |
| Private repo URL | `masked` | host/org/repo 일부 정책화 |
| High entropy string | `masked` | false positive는 report에 기록 |
| Tool result raw output | `summarized` | 긴 출력은 요약, 원문은 redacted artifact reference로만 |

### 6.4 Redaction report

- 모든 redaction finding은 `redaction_report.findings[]`에 종류와 count를 남긴다.
- 실제 secret 값은 report에 남기지 않는다.
- 필요 시 `sample_hash`로 같은 secret이 여러 번 등장했는지 확인한다.
- `--redact off`는 기본 금지이며, 별도 unsafe flag와 terminal warning을 요구한다.

### 6.5 Raw artifact handling

- raw artifact path는 target prompt에 reference로 넣을 수 있다.
- 민감한 원문 전체를 target prompt에 inline하지 않는다.
- artifact는 기본적으로 redacted copy를 만들고, original path는 local-only metadata로만 보존한다.
- `agent-xfer` artifact directory 예시:

```text
.agent-xfer/
  handoffs/<handoff_id>/handoff.json
  handoffs/<handoff_id>/prompt.md
  handoffs/<handoff_id>/source.redacted.jsonl
  checkpoints/<from>__<to>.json
```

## 7. 구현 언어 추천

### 7.1 비교표

| 후보 | JSONL parsing | Markdown parsing | subprocess 관리 | cross-platform | packaging | 테스트 | adapter 확장성 | 판단 |
|---|---|---|---|---|---|---|---|---|
| Python core | 강함 | 충분히 강함 | 강함 | 좋음 | 보통 | 매우 좋음 | 좋음 | **MVP 핵심 구현 추천** |
| POSIX sh wrapper | 약함 | 약함 | 단순 호출은 쉬움 | Unix/macOS에서 좋음 | 매우 단순 | 제한적 | 낮음 | **얇은 launcher/doctor/smoke 용도 추천** |
| Node.js/TypeScript | 강함 | 강함 | 좋음 | 좋음 | 매우 좋음 | 좋음 | 매우 좋음 | 이후 로드맵 후보 |
| Shell-only | 약함 | 약함 | 단순 호출은 쉬움 | 약함 | 약함 | 약함 | 약함 | 단독 구현 부적합 |

### 7.2 Python + sh 이중 진입점 추천 이유

MVP는 **Python core + POSIX sh wrapper**가 가장 현실적이다.

- Python은 JSONL streaming parser, Markdown transcript parser, redaction, checkpoint, artifact, app-server client 같은 상태 있는 로직에 적합하다.
- `subprocess.run`, timeout, stdout/stderr capture, exit code handling이 안정적이다.
- `sqlite3`, `tarfile`, `json`, `pathlib`, `hashlib`, `re` 등 표준 라이브러리만으로 초기 PoC가 가능하다.
- `pytest` fixture 기반으로 provider parser를 빠르게 검증할 수 있다.
- sh wrapper는 `python3 -m agent_xfer "$@"`를 호출하는 얇은 launcher로 두면 설치 전에도 repo checkout 상태에서 실행할 수 있다.
- sh는 provider CLI 존재 여부 확인, smoke command 안내, bootstrap 같은 부가 작업에는 유용하지만 JSONL/Markdown parsing, redaction, checkpoint의 source of truth가 되면 안 된다.
- Cloud/로컬 모두에서 provider CLI가 없어도 Python fixture test는 돌릴 수 있고, sh wrapper는 최소 smoke만 검증하면 된다.

장기적으로 npm global install과 JS ecosystem 통합을 중시한다면 TypeScript CLI wrapper 또는 재구현을 후속 로드맵으로 둘 수 있다. 다만 MVP에서는 JS를 범위 밖으로 두고, Python core의 안정화와 sh wrapper 호환성을 먼저 확보한다.

## 8. MVP 구현 순서

### Phase 0: 문서/fixture 고정

- 이 설계를 기준으로 `HandoffBundle v1` schema를 고정한다.
- provider별 fixture를 만든다.
- 실제 secret이 들어간 transcript를 fixture에 넣지 않는다.

### Phase 1: Core model과 CLI skeleton

- `agent-xfer doctor`
- `agent-xfer inspect`
- `agent-xfer dry-run`
- `agent-xfer sync --confirm`
- provider string parser: `<provider>:<id>`
- artifact directory와 checkpoint store 구현.

### Phase 2: Parser/source adapters

1. `GrokAdapter.read_session`:
   - `grok export` Markdown parser.
   - optional trace archive parser는 뒤로 미룬다.
2. `AntigravityAdapter.read_session`:
   - `transcript_full.jsonl` -> `transcript.jsonl` fallback.
   - `USER_REQUEST` XML-like wrapper extraction.
3. `CodexAdapter.read_session`:
   - app-server `thread/read includeTurns` client.
   - app-server launch/stdio lifecycle 관리.
4. `ClaudeAdapter.read_session`:
   - 2차. SDK or JSONL fallback.

### Phase 3: Redaction and summarization

- secret scanner.
- redaction report.
- event summarizer.
- prompt budget trimming.
- git enricher: branch, HEAD, status, diff summary.

### Phase 4: Target adapters

1. `CodexAdapter.send_handoff`: `codex exec resume`.
2. `GrokAdapter.send_handoff`: `grok -r -p --cwd`.
3. `AntigravityAdapter.send_handoff`: `agy --conversation --print --print-timeout`.
4. `ClaudeAdapter.send_handoff`: `claude --resume -p` optional.

### Phase 5: Safety and checkpoint

- duplicate handoff hash guard.
- `--dry-run` default path.
- `--confirm` required for mutation.
- `--range all|since-last`.
- checkpoint update only after successful target send.

### Phase 6: Live smoke matrix

검증된 로컬 환경에서 다음 matrix를 수행한다.

| From | To | MVP smoke |
|---|---|---|
| Codex | Grok | 포함 |
| Codex | Antigravity | 포함 |
| Grok | Codex | 포함 |
| Grok | Antigravity | 포함 |
| Antigravity | Codex | 포함 |
| Antigravity | Grok | 포함 |
| Claude | Codex/Grok/Antigravity | 2차 |
| Codex/Grok/Antigravity | Claude | 2차 |

## 9. 테스트 전략

### 9.1 Unit tests

- provider id parser:
  - `codex:<uuid>` -> provider `codex`, id_kind `thread_id`.
  - `grok:<uuid>` -> provider `grok`, id_kind `session_id`.
  - `antigravity:<uuid>` -> provider `antigravity`, id_kind `conversation_id`.
- Grok Markdown parser:
  - `## User`/`## Assistant` turn extraction.
  - multiline content preservation.
- Antigravity JSONL parser:
  - `USER_INPUT` extraction.
  - `<USER_REQUEST>` content extraction.
  - `PLANNER_RESPONSE` assistant mapping.
- Codex app-server response parser:
  - `turns[]`/`items[]` -> `NormalizedEvent[]`.
- Redaction scanner:
  - API key, bearer token, email, `.env`, private key, absolute home path.
- Prompt renderer:
  - required sections present.
  - max prompt char budget respected.

### 9.2 Fixture tests

Fixture directory proposal:

```text
tests/fixtures/
  grok/export-basic.md
  grok/trace-basic.tar.gz.fake/
  antigravity/transcript_full.basic.jsonl
  antigravity/transcript.basic.jsonl
  codex/thread_read_basic.json
  claude/session.basic.jsonl
  redaction/secrets.jsonl
```

Cloud에서 provider CLI가 없어도 fixture tests는 통과해야 한다.

### 9.3 Integration tests with fake adapters

- fake source adapter가 deterministic events를 반환한다.
- fake target adapter가 prompt를 file에 기록한다.
- `dry-run`은 target file을 만들지 않는다.
- `sync --confirm`은 target file을 만들고 checkpoint를 기록한다.
- 같은 handoff를 두 번 보내면 duplicate guard가 차단한다.

### 9.4 Live smoke tests

실제 로컬 Mac에서만 실행한다. Cloud에서는 Grok/Antigravity/Claude 재검증을 시도하지 않는다.

```bash
agent-xfer doctor --cwd /repo
agent-xfer inspect --source grok:019eb0b8-00df-7300-aeed-4fd7e2a4b7fd --cwd /repo
agent-xfer inspect --source antigravity:9d61b187-4b6d-4e4d-b286-08a3a30454e5 --cwd /repo
agent-xfer inspect --source codex:019eb0b6-3e60-76d1-a573-6f9da5937d36 --cwd /repo
agent-xfer dry-run --from grok:019eb0b8-00df-7300-aeed-4fd7e2a4b7fd --to codex:<target_thread_id> --cwd /repo
agent-xfer sync --from codex:<source_thread_id> --to antigravity:<target_conversation_id> --cwd /repo --confirm
```

### 9.5 Security tests

- prompt에 raw private key가 포함되지 않는지 검사한다.
- `.env` 값이 제거되는지 검사한다.
- redaction off가 기본적으로 실패하는지 검사한다.
- target prompt에는 artifact path만 있고 raw transcript 전체가 inline되지 않는지 검사한다.

## 10. 제외 범위와 남은 리스크

### 10.1 MVP 제외 범위

- Provider 내부 session file 직접 수정.
- 무손실 transcript 변환.
- tool call replay.
- raw Responses API item injection (`thread/inject_items`)을 통한 history grafting.
- Grok `import`를 cross-agent migration 수단으로 사용하는 것.
- Grok `agent stdio`/ACP integration.
- Antigravity SQLite protobuf-like DB parsing.
- Claude live smoke를 MVP blocker로 삼는 것.
- web/cloud 환경에서 사용자의 로컬 `~/.claude`, `~/.codex`, `~/.gemini/antigravity-cli` 접근을 가정하는 것.

### 10.2 남은 리스크

| 리스크 | 영향 | 완화 |
|---|---|---|
| Provider schema drift | parser 실패 또는 정보 누락 | tolerant parser, fixture versioning, `unknown` event 보존 |
| Context window 초과 | target이 handoff를 소화하지 못함 | prompt budget, 요약 우선, artifact reference 사용 |
| Secret/token 유출 | 보안 사고 | mandatory redaction, report, raw inline 금지 |
| 중복 sync | target session 혼란 | handoff hash checkpoint, duplicate guard |
| source compact/summary | 세부 정보 손실 | git/status enrichment, raw artifact reference, pending TODO 강조 |
| target 세션 기존 context와 충돌 | 잘못된 continuation | prompt에 “먼저 repo 상태 inspect” 지시, cwd mismatch warning |
| Antigravity source가 semi-private path | 버전 변경 시 깨짐 | path resolver fallback, healthcheck, parser fixture |
| Claude auth/login | live adapter 실패 | Claude optional/2차, SDK/JSONL fallback |
| app-server lifecycle | Codex read 불안정 | timeout/retry, fallback rollout parser 계획 |
| subprocess quoting | prompt 손상 | stdin/tempfile 전달 옵션 검토, shell=False 사용 |

### 10.3 최종 권고

바로 전체 cross-provider migration을 만들기보다, 다음 작은 실험 순서로 진행한다.

1. fixture 기반 parser와 `HandoffBundle v1` 생성.
2. `dry-run`에서 redacted `prompt.md`와 `handoff.json` 생성.
3. fake target으로 duplicate checkpoint 검증.
4. 로컬 Mac에서 Grok -> Codex, Codex -> Antigravity, Antigravity -> Grok live smoke.
5. Codex app-server read 안정화.
6. Claude 로그인 환경에서 Claude source/target adapter 재검증.
