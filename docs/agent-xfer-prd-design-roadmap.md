# agent-xfer PRD / 설계 문서 / 로드맵

작성일: 2026-06-10

이 문서는 `agent-xfer`를 실제로 구현하기 위한 제품 요구사항(PRD), 기술 설계, 단계별 로드맵이다. 전제는 `docs/session-handoff-investigation.md`의 결론과 동일하다. 즉, provider 내부 세션 파일을 무손실 변환하거나 target 세션 파일을 직접 수정하지 않고, source 세션에서 작업 맥락을 읽어 redacted handoff bundle을 만든 뒤 target 세션의 공식 또는 검증된 resume 경로에 continuation prompt를 주입한다.

## 1. PRD

### 1.1 제품 한 줄 정의

`agent-xfer`는 Claude Code, Codex, Grok Build, Antigravity CLI 같은 로컬 coding agent의 특정 세션 작업 기록을 읽어, 다른 agent의 기존 세션으로 안전하게 인수인계하는 CLI 도구다.

### 1.2 문제 정의

개발자는 여러 coding agent를 상황에 따라 번갈아 사용한다. 하지만 각 agent는 고유한 세션 저장소, transcript schema, resume 명령, tool-call 표현을 갖고 있어 다음 문제가 생긴다.

- 한 agent에서 진행한 작업 맥락을 다른 agent에게 수동으로 요약해야 한다.
- transcript 전체를 복사하면 너무 길고 민감 정보가 섞일 수 있다.
- 내부 session file을 직접 수정하면 세션 손상, metadata 불일치, 중복 주입 위험이 있다.
- tool call을 그대로 replay하는 것은 provider별 schema 차이와 side effect 때문에 안전하지 않다.

### 1.3 목표

MVP의 목표는 다음이다.

1. `--from <provider>:<source_id>`로 source 세션을 읽는다.
2. provider별 transcript/export/app-server 결과를 `NormalizedEvent[]`로 정규화한다.
3. redaction pass로 secret, token, PII, 민감 path를 제거하거나 마스킹한다.
4. `HandoffBundle v1`과 target용 `generated_handoff_prompt`를 생성한다.
5. `--to <provider>:<target_id>`로 target 세션을 resume하고 continuation prompt를 1회 주입한다.
6. 같은 source range가 같은 target에 중복 주입되지 않도록 checkpoint를 남긴다.

### 1.4 비목표

MVP에서 하지 않을 일은 다음이다.

- provider 내부 session file 직접 수정.
- 무손실 transcript 변환.
- tool call replay.
- raw Responses API item injection으로 target model-visible history를 직접 grafting.
- Grok `import`를 cross-agent migration 수단으로 사용하는 것.
- Antigravity SQLite protobuf-like DB parsing.
- Claude Code 로그인/live smoke를 MVP blocker로 삼는 것.
- Cloud에서 사용자의 로컬 `~/.claude`, `~/.codex`, `~/.gemini/antigravity-cli`에 접근 가능하다고 가정하는 것.

### 1.5 사용자와 사용 시나리오

#### Persona A: 로컬 multi-agent 개발자

- Codex에서 구현을 시작했지만 Grok Build나 Antigravity로 이어서 검토하고 싶다.
- 원하는 명령:

```bash
agent-xfer sync \
  --from codex:<source_thread_id> \
  --to grok:<target_session_id> \
  --cwd /repo \
  --confirm
```

#### Persona B: provider별 강점을 나눠 쓰는 개발자

- Grok Build에서 큰 방향을 잡고 Codex에서 테스트/패치를 이어가고 싶다.
- 원하는 명령:

```bash
agent-xfer dry-run \
  --from grok:<source_session_id> \
  --to codex:<target_thread_id> \
  --cwd /repo
```

#### Persona C: 보안에 민감한 개발자

- transcript에 token이나 내부 path가 있을 수 있으므로 target prompt를 보내기 전에 redaction report를 보고 싶다.
- 원하는 명령:

```bash
agent-xfer dry-run \
  --from antigravity:<conversation_id> \
  --to codex:<thread_id> \
  --cwd /repo \
  --redact strict
```

### 1.6 MVP provider 범위

| Provider | Source | Target | MVP |
|---|---|---|---|
| Codex | app-server `thread/read includeTurns` | `codex exec resume <thread_id> <prompt>` | 포함 |
| Grok Build | `grok export <session_id>` | `grok -r <session_id> -p <prompt>` | 포함 |
| Antigravity CLI | transcript JSONL | `agy --conversation <conversation_id> --print <prompt>` | 포함 |
| Claude Code | SDK 또는 JSONL fallback | `claude --resume <session_id> -p <prompt>` | 2차/optional |

### 1.7 성공 기준

MVP가 성공했다고 판단하려면 다음을 만족해야 한다.

- fixture만으로 parser, redaction, prompt rendering, checkpoint 테스트가 통과한다.
- provider CLI가 없는 Cloud 환경에서도 unit/fixture/fake integration tests가 통과한다.
- 로컬 Mac에서 최소 3개 live smoke가 성공한다.
  - Grok -> Codex
  - Codex -> Antigravity
  - Antigravity -> Grok
- `dry-run`은 target 세션을 절대 변경하지 않는다.
- `sync --confirm` 없이 target에 prompt를 보내지 않는다.
- 같은 handoff hash를 같은 target에 두 번 보내면 기본 차단한다.
- target prompt에 raw private key, API key, bearer token, `.env` 값이 포함되지 않는다.

## 2. 기능 요구사항

### 2.1 CLI commands

#### `agent-xfer doctor`

환경을 점검한다.

```bash
agent-xfer doctor --cwd /repo
```

출력해야 할 정보:

- provider CLI 설치 여부.
- auth 상태를 확인할 수 있는 경우 auth 상태.
- Codex app-server 실행 가능 여부.
- Antigravity app data dir 접근 가능 여부.
- artifact/checkpoint directory write 가능 여부.
- redaction config 상태.

#### `agent-xfer inspect`

source 세션을 읽을 수 있는지 확인하고 요약 metadata를 출력한다.

```bash
agent-xfer inspect --source grok:<session_id> --cwd /repo
agent-xfer inspect --source antigravity:<conversation_id> --cwd /repo
agent-xfer inspect --source codex:<thread_id> --cwd /repo
```

출력해야 할 정보:

- provider, id, id_kind.
- read method.
- event count.
- first/last timestamp.
- cwd mismatch 여부.
- raw artifact reference.
- warning/error.

#### `agent-xfer dry-run`

source read, normalization, redaction, handoff bundle, prompt rendering까지 수행하되 target에 보내지 않는다.

```bash
agent-xfer dry-run \
  --from grok:<session_id> \
  --to codex:<thread_id> \
  --cwd /repo
```

생성물:

- `.agent-xfer/handoffs/<handoff_id>/handoff.json`
- `.agent-xfer/handoffs/<handoff_id>/prompt.md`
- `.agent-xfer/handoffs/<handoff_id>/source.redacted.jsonl` 또는 provider별 redacted artifact

#### `agent-xfer export`

source session을 읽고 redaction/prompt rendering까지 수행한 뒤, target mutation 없이 명시한 경로로 handoff bundle을 복사한다. `--to`는 optional이며 생략 시 prompt rendering context로 `fake:export-target`를 사용한다.

```bash
agent-xfer export \
  --from codex:<source_thread_id> \
  --cwd /repo \
  --out handoff.json \
  --prompt-out prompt.md
```

성공 시:

- `.agent-xfer/handoffs/<handoff_id>/handoff.json` artifact 생성.
- `--out` 경로에 handoff JSON 복사.
- `--prompt-out`이 있으면 prompt Markdown 복사.
- target send와 checkpoint write는 수행하지 않는다.

#### `agent-xfer sync`

`dry-run` pipeline을 수행한 뒤 target에 prompt를 보낸다. mutation이므로 `--confirm`이 필요하다.

```bash
agent-xfer sync \
  --from codex:<thread_id> \
  --to antigravity:<conversation_id> \
  --cwd /repo \
  --confirm
```

성공 시:

- target resume/send command 실행.
- checkpoint 기록.
- send result와 artifact path 출력.

#### `agent-xfer sources` / `agent-xfer targets`

cwd 기준으로 발견 가능한 source/target 후보 또는 availability hint를 나열한다.

```bash
agent-xfer sources --cwd /repo
agent-xfer targets --cwd /repo
```

현재 구현은 deep session listing이 아니라 shallow discovery다.

- `fake`: deterministic source/target id를 제공한다.
- Codex: `AGENT_XFER_CODEX_THREAD_READ_JSON`, `AGENT_XFER_CODEX_APP_SERVER_COMMAND` 설정 여부와 `codex` CLI availability를 표시한다.
- Grok: `grok` CLI availability를 표시하고 실제 session id는 사용자가 명시한다.
- Antigravity: `AGENT_XFER_ANTIGRAVITY_HOME` 또는 기본 app dir의 `cache/last_conversations.json`에서 cwd match를 찾는다.
- Claude: `AGENT_XFER_CLAUDE_TRANSCRIPT`, `CLAUDE_CONFIG_DIR`/`~/.claude`, `claude` CLI availability를 표시한다.

### 2.2 공통 옵션

```text
--cwd <path>                    repo/workspace path
--from <provider>:<id>          source session/thread/conversation
--to <provider>:<id>            target session/thread/conversation
--source <provider>:<id>        inspect용 source alias
--range all|since-last          source range
--redact secrets|strict|off     redaction mode
--max-prompt-chars <n>          target prompt budget
--out <path>                    export destination handoff JSON path
--prompt-out <path>             optional export prompt Markdown path
--include-raw                   redacted raw artifact 생성
--confirm                       target mutation 허용
--allow-duplicate               checkpoint duplicate guard 우회
--json                          machine-readable output
--verbose                       verbose diagnostics
```

### 2.3 에러 UX

에러는 사람이 읽을 수 있는 메시지와 machine-readable code를 함께 제공한다.

예시 code:

- `PROVIDER_CLI_NOT_FOUND`
- `PROVIDER_AUTH_REQUIRED`
- `SOURCE_NOT_FOUND`
- `SOURCE_READ_FAILED`
- `TARGET_SEND_FAILED`
- `CWD_MISMATCH`
- `REDACTION_UNSAFE_OFF_DENIED`
- `DUPLICATE_HANDOFF_BLOCKED`
- `PROMPT_BUDGET_EXCEEDED`

## 3. 비기능 요구사항

### 3.1 안전성

- target mutation은 `sync --confirm`에서만 발생한다.
- target provider의 transcript/session 파일을 직접 수정하지 않는다.
- source provider 파일은 read-only로만 접근한다.
- Python core의 subprocess 실행은 `shell=False`로 실행하고 prompt quoting 손상을 피한다.
- sh wrapper는 provider command를 직접 조합하지 않고 Python module에 argv를 전달하는 launcher로 제한한다.
- 가능한 경우 prompt는 argv보다 stdin/tempfile 경유를 지원하도록 provider별 adapter에서 선택한다.

### 3.2 보안

- redaction은 prompt 생성 전에 필수로 실행한다.
- secret 원문은 `redaction_report`에 남기지 않는다.
- raw transcript 전체를 target prompt에 inline하지 않는다.
- raw artifact는 redacted copy를 기본으로 저장한다.
- `--redact off`는 별도 unsafe flag 없이는 실패한다.

### 3.3 신뢰성과 관측성

- 모든 단계는 structured log event를 남긴다.
- `dry-run` artifact만으로 어떤 prompt가 전송될지 재현 가능해야 한다.
- checkpoint는 target send 성공 이후에만 기록한다.
- provider schema drift에 대비해 unknown event를 보존하고 warning으로 처리한다.

### 3.4 테스트 가능성

- provider CLI가 없어도 fixture tests는 통과해야 한다.
- provider adapter는 fake adapter로 대체 가능해야 한다.
- live smoke tests는 opt-in으로 분리한다.

## 4. 기술 설계

### 4.1 전체 아키텍처

```text
CLI Command
  |
  v
Command Orchestrator
  |
  +--> Provider Registry
  |      +--> CodexAdapter
  |      +--> GrokAdapter
  |      +--> AntigravityAdapter
  |      +--> ClaudeAdapter
  |
  +--> Source Reader
  |      +--> Provider raw read/export/app-server
  |      +--> NormalizedEvent[]
  |
  +--> Redaction Pipeline
  |      +--> secret scanner
  |      +--> PII/path scanner
  |      +--> redaction_report
  |
  +--> Handoff Builder
  |      +--> HandoffBundle v1
  |      +--> generated_handoff_prompt
  |      +--> git enrichment
  |
  +--> Artifact Store
  |      +--> handoff.json
  |      +--> prompt.md
  |      +--> source.redacted.*
  |
  +--> Checkpoint Store
  |      +--> duplicate guard
  |
  +--> Target Sender
         +--> provider resume command
```

### 4.2 Python core + sh wrapper layout 제안

MVP는 Python core를 source of truth로 두고, repo-local 실행성과 Unix/macOS 편의를 위해 얇은 POSIX sh wrapper를 함께 제공한다.

```text
bin/
  agent-xfer                  # POSIX sh launcher: python3 -m agent_xfer "$@"

agent_xfer/
  __init__.py
  cli.py
  commands/
    doctor.py
    inspect.py
    dry_run.py
    sync.py
    sources.py
    targets.py
  core/
    ids.py
    models.py
    orchestrator.py
    artifacts.py
    checkpoints.py
    git.py
    errors.py
  providers/
    base.py
    codex.py
    grok.py
    antigravity.py
    claude.py
    fake.py
  parsing/
    jsonl.py
    markdown_transcript.py
    antigravity.py
    codex_app_server.py
  redaction/
    scanner.py
    policies.py
    report.py
  rendering/
    handoff_prompt.py
    json_output.py
  subprocesses/
    runner.py
    app_server.py

scripts/
  smoke.sh                    # optional local smoke helper; core logic 없음

tests/
  fixtures/
  unit/
  integration/
  live/
```

### 4.3 ProviderAdapter interface

```python
class ProviderAdapter(Protocol):
    provider: str
    id_kind: Literal["thread_id", "session_id", "conversation_id"]
    capabilities: ProviderCapabilities

    def healthcheck(self, cwd: Path) -> HealthcheckResult: ...
    def inspect(self, source_id: str, cwd: Path) -> InspectResult: ...
    def read_session(self, source_id: str, cwd: Path) -> ReadSessionResult: ...
    def build_handoff(self, events: list[NormalizedEvent]) -> HandoffDraft: ...
    def send_handoff(self, target_id: str, prompt: str, cwd: Path) -> SendResult: ...
```

`ProviderCapabilities`:

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    can_read_session: bool
    can_resume_target: bool
    can_send_prompt_to_target: bool
    can_emit_machine_readable_events: bool
    can_locate_local_transcripts: bool
    uses_official_api: bool
    uses_private_or_semiprivate_files: bool
    requires_auth: bool
    requires_local_cli: bool
```

### 4.4 Core data models

#### `ProviderRef`

```json
{
  "provider": "codex",
  "id": "019eb0b6-3e60-76d1-a573-6f9da5937d36",
  "id_kind": "thread_id"
}
```

#### `NormalizedEvent`

```json
{
  "event_id": "sha256:...",
  "provider": "grok",
  "source_id": "019eb0b8-00df-7300-aeed-4fd7e2a4b7fd",
  "sequence": 0,
  "created_at": "2026-06-10T00:00:00Z",
  "role": "user|assistant|system|tool|unknown",
  "kind": "message|tool_call|tool_result|command|file_change|summary|metadata|error|unknown",
  "content_text": "...",
  "content_json": {},
  "tool_name": null,
  "command": null,
  "cwd": "/repo",
  "status": "ok|error|unknown",
  "files": [],
  "raw_ref": {
    "artifact_id": "source",
    "path": "...",
    "line_start": 1,
    "line_end": 1
  }
}
```

#### `HandoffBundle v1`

`HandoffBundle`는 다음 필드를 포함한다.

- `source.provider`
- `source.id`
- `source.id_kind`
- `source.cwd`
- `source.created_at`
- `source.updated_at`
- `target.provider`
- `target.id`
- `target.id_kind`
- `original_user_goal`
- `current_state`
- `completed_work`
- `pending_work`
- `decisions`
- `assumptions`
- `files_touched`
- `commands_run`
- `tests_and_verification`
- `blockers`
- `raw_artifact_references`
- `redaction_report`
- `generated_handoff_prompt`

### 4.5 sh wrapper의 역할과 제한

`sh` 지원은 가능하며 권장한다. 다만 역할을 명확히 제한한다.

권장 역할:

- `bin/agent-xfer`에서 `python3 -m agent_xfer "$@"` 실행.
- virtualenv가 있으면 자동 감지하고, 없으면 system `python3` 사용.
- `AGENT_XFER_PYTHON` 환경변수로 Python interpreter override 허용.
- local smoke helper와 bootstrap helper 제공.

금지/비권장 역할:

- JSONL/Markdown transcript parsing을 sh로 구현하지 않는다.
- redaction policy를 sh와 Python에 중복 구현하지 않는다.
- checkpoint/handoff hash 계산을 sh에서 하지 않는다.
- provider prompt quoting을 sh 문자열 조합에 의존하지 않는다.

예상 wrapper 형태:

```sh
#!/bin/sh
set -eu
PYTHON="${AGENT_XFER_PYTHON:-python3}"
exec "$PYTHON" -m agent_xfer "$@"
```

이 구조면 사용자는 설치 전에도 다음처럼 실행할 수 있다.

```bash
./bin/agent-xfer doctor --cwd /repo
python3 -m agent_xfer doctor --cwd /repo
```

### 4.6 Provider별 adapter 상세

#### CodexAdapter

Source read:

1. `codex app-server`를 stdio로 실행한다.
2. `thread/read`에 `includeTurns: true`로 요청한다.
3. `turns[]`와 `items[]`에서 user/assistant/tool/metadata event를 추출한다.
4. app-server 실패 시 rollout JSONL fallback은 후속 milestone로 둔다.

Target send:

```bash
codex exec resume <target_thread_id> "<handoff prompt>"
```

#### GrokAdapter

Source read:

1. `grok export <source_session_id>` 실행.
2. Markdown transcript를 `## User`, `## Assistant` heading으로 parsing한다.
3. optional enrich로 `grok trace --local --json`을 후속 지원한다.

Target send:

```bash
grok -r <target_session_id> -p "<handoff prompt>" --cwd <cwd>
```

#### AntigravityAdapter

Source read:

1. `~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/transcript_full.jsonl` 읽기.
2. 없으면 `transcript.jsonl` fallback.
3. `USER_INPUT`에서 `<USER_REQUEST>` 내부 content 추출.
4. `PLANNER_RESPONSE`를 assistant message로 변환.

Target send:

```bash
agy --conversation <target_conversation_id> --print "<handoff prompt>" --print-timeout 30s
```

#### ClaudeAdapter

Source read:

1. SDK `get_session_messages`/`get_session_info` 우선.
2. SDK unavailable 시 `~/.claude/projects/<encoded-project-path>/<session-id>.jsonl` fallback.

Target send:

```bash
claude --resume <target_session_id> -p "<handoff prompt>"
```

MVP에서는 interface와 fixture parser를 준비하고 live smoke는 2차로 둔다.

## 5. Redaction/security 설계

### 5.1 Redaction pipeline

```text
raw provider data
  -> parser
  -> NormalizedEvent[]
  -> redaction scanner
  -> redacted NormalizedEvent[]
  -> HandoffBundle
  -> generated_handoff_prompt
```

### 5.2 Scanner rules

MVP scanner는 다음을 찾는다.

- `Authorization: Bearer ...`
- `oauth_token`, `refresh_token`, `access_token`
- provider API key prefix와 일반 high-entropy token
- PEM private key block
- `.env` style `KEY=VALUE`
- email address
- home directory absolute path
- private git URL 후보

### 5.3 Redaction actions

| Finding | Action |
|---|---|
| API key/token | mask |
| Private key | drop block |
| `.env` value | keep key name, drop value |
| Email | mask or hash |
| Home path | replace with `~` or repo-relative path |
| Private repo URL | mask credential and host/org as configured |
| Long tool output | summarize and artifact-reference |

### 5.4 Redaction report

`redaction_report`는 다음을 포함한다.

- mode: `secrets`, `strict`, `off`
- finding kind별 count
- action
- sample hash
- dropped event count
- warnings

Secret 원문은 report에 절대 포함하지 않는다.

## 6. Checkpoint와 artifact 설계

### 6.1 Artifact layout

```text
.agent-xfer/
  handoffs/
    <handoff_id>/
      handoff.json
      prompt.md
      source.redacted.jsonl
      source.meta.json
  checkpoints/
    <from-provider>__<source-id>__<to-provider>__<target-id>.json
```

### 6.2 Handoff id

`handoff_id`는 다음 정보를 canonical JSON으로 만든 뒤 SHA-256으로 계산한다.

- source provider/id/id_kind
- target provider/id/id_kind
- source range
- normalized redacted event digest
- prompt renderer version

### 6.3 Checkpoint record

```json
{
  "schema_version": "agent-xfer.checkpoint.v1",
  "source": { "provider": "grok", "id": "...", "id_kind": "session_id" },
  "target": { "provider": "codex", "id": "...", "id_kind": "thread_id" },
  "last_handoff_id": "sha256:...",
  "last_source_range": { "mode": "all", "from_sequence": 0, "to_sequence": 12 },
  "sent_at": "2026-06-10T00:00:00Z",
  "send_method": "codex-exec-resume",
  "artifact_dir": ".agent-xfer/handoffs/sha256-..."
}
```

## 7. 마일스톤 단위 산정

### 7.1 수준별 분해

`agent-xfer`는 provider별 live 연동을 한 번에 구현하기보다, 검증 가능한 수준을 작게 쪼개는 것이 안전하다. 권장 수준은 다음과 같다.

| 수준 | 이름 | 목표 | target mutation | provider CLI 필요 | 완료 기준 |
|---|---|---|---|---|---|
| L0 | 문서/fixture | PRD, schema, fixture를 고정한다. | 없음 | 없음 | fixture와 schema가 리뷰 가능하다. |
| L1 | Local dry-run skeleton | fake provider로 `dry-run` artifact와 prompt를 만든다. | 없음 | 없음 | `python3 -m agent_xfer dry-run --from fake:a --to fake:b --cwd .`와 `./bin/agent-xfer ...`가 같은 결과를 낸다. |
| L2 | Source parser MVP | Grok export, Antigravity JSONL, Codex app-server response fixture를 `NormalizedEvent[]`로 파싱한다. | 없음 | 없음 | fixture 기반 parser/redaction/prompt tests가 통과한다. |
| L3 | Real inspect | 설치된 provider에 대해 read-only `inspect`를 수행한다. | 없음 | 일부 필요 | source metadata, event count, warnings를 출력한다. Grok/Antigravity/Codex read-only adapters started. |
| L4 | Controlled sync | 검증된 provider target에 continuation prompt를 보낸다. | 있음, `--confirm` 필요 | 필요 | fake target과 최소 1개 live target smoke가 성공한다. |
| L5 | Cross-provider MVP | Codex/Grok/Antigravity 사이 주요 방향을 지원한다. | 있음, `--confirm` 필요 | 필요 | Grok -> Codex, Codex -> Antigravity, Antigravity -> Grok smoke가 성공한다. |

### 7.2 첫 구현 마일스톤의 권장 목표 수준

첫 구현 마일스톤은 **L1: Local dry-run skeleton**으로 잡는 것이 적절하다. 이미 조사와 PRD가 있으므로 L0는 현재 문서 작업으로 충족된 것으로 보고, 첫 코드 마일스톤은 live provider 연동이 아니라 end-to-end shape를 고정하는 데 집중한다.

첫 구현 마일스톤에서 반드시 포함할 범위:

- Python package skeleton과 `bin/agent-xfer` POSIX sh wrapper.
- `ProviderRef` parser: `codex:<id>`, `grok:<id>`, `antigravity:<id>`, `claude:<id>`, `fake:<id>`.
- `ProviderAdapter` base protocol과 `FakeAdapter`.
- `doctor`, `inspect`, `dry-run` command의 최소 동작.
- `HandoffBundle v1` 최소 JSON 생성.
- `prompt.md` rendering.
- `.agent-xfer/handoffs/<handoff_id>/` artifact 생성.
- 기본 redaction scanner의 placeholder 또는 최소 구현.
- `sync` command는 존재하되 `--confirm` 없이는 실패하고, fake target 외 live target 전송은 아직 막는다.

첫 구현 마일스톤에서 제외할 범위:

- Codex app-server 실제 stdio lifecycle.
- Grok/Antigravity/Claude 실제 CLI 호출.
- 실제 target session mutation.
- 정교한 summarization.
- 완전한 secret scanner.
- `sources`/`targets`의 provider별 deep discovery.

### 7.3 첫 구현 마일스톤 acceptance criteria

첫 구현 마일스톤은 다음 명령이 provider CLI 없이 통과하면 완료로 본다.

```bash
python3 -m agent_xfer doctor --cwd .
./bin/agent-xfer doctor --cwd .
python3 -m agent_xfer inspect --source fake:source-1 --cwd .
python3 -m agent_xfer dry-run --from fake:source-1 --to fake:target-1 --cwd .
python3 -m agent_xfer sync --from fake:source-1 --to fake:target-1 --cwd .
python3 -m agent_xfer sync --from fake:source-1 --to fake:target-1 --cwd . --confirm
```

기대 결과:

- `doctor`는 Python runtime, cwd, artifact directory 상태를 출력한다.
- `inspect`는 fake source의 event count와 id_kind를 출력한다.
- `dry-run`은 `handoff.json`, `prompt.md`, redaction report를 생성한다.
- `sync`는 `--confirm` 없이는 `CONFIRM_REQUIRED`로 실패한다.
- `sync --confirm`은 fake target에만 prompt를 기록하고 checkpoint를 생성한다.
- 동일 handoff를 다시 `sync --confirm`하면 duplicate guard가 차단한다.
- `./bin/agent-xfer`와 `python3 -m agent_xfer`의 동작이 동일하다.

### 7.4 첫 구현 마일스톤 산정

| 작업 | 난이도 | 산정 | 비고 |
|---|---:|---:|---|
| Python package/CLI skeleton | 낮음 | 0.5~1일 | argparse 또는 typer 중 선택. |
| sh wrapper | 낮음 | 0.5일 | POSIX sh, `AGENT_XFER_PYTHON` override. |
| core models/schema | 중간 | 1일 | dataclass + JSON serialization. |
| fake adapter | 낮음 | 0.5일 | deterministic fixture events. |
| artifact/checkpoint store | 중간 | 1일 | canonical hash와 duplicate guard 포함. |
| minimal redaction/prompt renderer | 중간 | 1일 | 기본 token/email/path mask. |
| tests | 중간 | 1~2일 | unit + fake integration. |

권장 timebox는 **3~5일**이다. 산출물은 실제 provider 연동이 아니라, 이후 provider adapter를 꽂을 수 있는 안정적인 골격과 안전장치다.

## 8. 로드맵

### Milestone 0: 문서와 fixture 확정

목표:

- PRD/설계/로드맵 승인.
- fixture format 확정.
- `HandoffBundle v1` 필드 고정.

산출물:

- `tests/fixtures/grok/export-basic.md`
- `tests/fixtures/antigravity/transcript_full.basic.jsonl`
- `tests/fixtures/codex/thread_read_basic.json`
- `tests/fixtures/redaction/secrets.txt`

완료 기준:

- fixture에 실제 secret이 없음.
- 각 fixture가 어떤 provider behavior를 나타내는지 README에 설명됨.

### Milestone 1: CLI skeleton과 core model

목표:

- Python package skeleton.
- `bin/agent-xfer` POSIX sh wrapper.
- `agent-xfer doctor|inspect|dry-run|sync` command shape.
- provider registry와 fake adapter.

완료 기준:

- `agent-xfer dry-run --from fake:a --to fake:b --cwd .`가 handoff artifact를 생성한다.
- `sync`는 `--confirm` 없이는 실패한다.

### Milestone 2: Parser와 source adapters

목표:

- Grok Markdown export parser.
- Antigravity transcript JSONL parser.
- Codex app-server response parser.
- Claude JSONL fixture parser optional.

현재 구현 상태:

- Grok `grok export` Markdown fixture parser 추가.
- Antigravity `transcript_full.jsonl` fixture parser와 `<USER_REQUEST>` 추출 추가.
- Codex app-server `thread/read includeTurns` fixture parser 추가.
- malformed JSONL line을 fatal error가 아니라 warning으로 처리하는 tolerant JSONL parser 추가.

완료 기준:

- fixture 기반 parser tests 통과.
- `inspect`가 event count와 first/last timestamp를 출력한다.

### Milestone 3: Read-only provider inspect adapters

목표:

- Grok `grok export` 기반 read-only source adapter.
- Antigravity local transcript JSONL 기반 read-only source adapter.
- Codex app-server `thread/read` payload 기반 parser와 fixture/env read path.
- 실제 target mutation 없이 real/fake source를 `inspect`와 `dry-run`에 연결.

현재 구현 상태:

- `GrokAdapter`는 `grok export <session_id>` stdout을 Markdown parser로 정규화한다.
- `AntigravityAdapter`는 `AGENT_XFER_ANTIGRAVITY_HOME` 또는 `~/.gemini/antigravity-cli` 아래 transcript JSONL을 read-only로 읽는다.
- `CodexAdapter`는 `AGENT_XFER_CODEX_THREAD_READ_JSON`으로 지정한 `thread/read includeTurns` JSON payload를 read-only로 읽는다. live app-server lifecycle은 아직 후속 작업이다.
- real target send는 아직 비활성화되어 있고 `sync --confirm`은 fake target만 허용한다.

완료 기준:

- provider CLI나 local transcript를 mocked fixture로 대체한 adapter tests 통과.
- `dry-run --from grok:<id> --to fake:<id>`가 artifact를 생성한다.

### Milestone 4: Redaction과 prompt renderer

목표:

- mandatory redaction pass.
- `redaction_report` 생성.
- prompt budget 적용.
- target prompt template 구현.

현재 구현 상태:

- bearer token, API/access/refresh/oauth token, secret/password assignment, `.env` style secret values, email, home path, private key block을 redaction한다.
- `strict` mode에서는 high-entropy token 후보도 추가로 마스킹한다.
- `redaction_report.findings[]`에는 finding kind, count, action, `sample_hash`만 남기고 원문 secret 값은 남기지 않는다.
- `--max-prompt-chars` 옵션을 `dry-run`과 `sync`에 추가했고, `handoff.json`에 `prompt_budget` metadata를 기록한다.

완료 기준:

- redaction fixture에서 secret 원문이 prompt에 남지 않는다.
- `handoff.json`과 `prompt.md`가 생성된다.
- prompt budget을 지정하면 generated prompt가 제한 길이를 넘지 않는다.

### Milestone 5: Target send adapters

목표:

- `codex exec resume` sender.
- `grok -r -p` sender.
- `agy --conversation --print` sender.
- fake sender integration test.

현재 구현 상태:

- `CodexAdapter.send_handoff`는 `codex exec resume <target_thread_id> <prompt>`를 `shell=False` subprocess로 호출한다.
- `GrokAdapter.send_handoff`는 `grok -r <target_session_id> -p <prompt> --cwd <cwd>`를 호출한다.
- `AntigravityAdapter.send_handoff`는 `agy --conversation <target_conversation_id> --print <prompt> --print-timeout 30s`를 호출한다.
- 모든 sender는 전송 prompt를 `.agent-xfer/handoffs/<handoff_id>/target.prompt.md`에도 저장한다.
- tests는 mocked executable로 argv shape를 검증하며, 실제 provider live smoke는 Milestone 6에 남긴다.

완료 기준:

- fake sender로 `sync --confirm` integration test 통과.
- mocked provider sender tests 통과.
- live sender tests는 opt-in marker로 분리된다.

### Milestone 6: Local live smoke

목표:

- 검증된 로컬 Mac에서 cross-provider smoke 실행.

현재 구현 상태:

- `tests/live/test_live_smoke.py`는 `AGENT_XFER_LIVE=1`일 때만 실행되는 opt-in pytest smoke harness다.
- 기본 live smoke는 `dry-run`만 수행하고 target session을 mutate하지 않는다.
- 실제 target mutation은 `AGENT_XFER_LIVE_CONFIRM_SYNC=1`을 추가로 설정해야 실행된다.
- `scripts/live-smoke.sh`는 같은 흐름을 shell에서 실행하는 helper이며, `--sync`를 명시하지 않으면 dry-run만 수행한다.

우선순위:

1. Grok -> Codex
2. Codex -> Antigravity
3. Antigravity -> Grok
4. Codex -> Grok
5. Grok -> Antigravity
6. Antigravity -> Codex

완료 기준:

- target session이 handoff prompt를 받고 source 작업 맥락을 회수할 수 있다.
- checkpoint가 중복 sync를 차단한다.
- live smoke는 cloud/default test run에서 skip되어야 한다.

### Milestone 7: Claude optional support

목표:

- Claude 로그인 환경에서 SDK/JSONL source read 검증.
- `claude --resume -p` target send 검증.

현재 구현 상태:

- `ClaudeAdapter`는 `AGENT_XFER_CLAUDE_TRANSCRIPT`가 있으면 해당 JSONL을 read-only로 읽고, 없으면 `CLAUDE_CONFIG_DIR` 또는 `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`을 best-effort fallback으로 찾는다.
- Claude JSONL parser는 common top-level/nested `message.role`과 `message.content` shape를 tolerant하게 `NormalizedEvent[]`로 변환한다.
- `ClaudeAdapter.send_handoff`는 `claude --resume <target_session_id> -p <prompt>`를 호출한다.
- tests는 fixture JSONL과 mocked `claude` executable로 검증하며, 로그인된 실제 Claude live smoke는 계속 opt-in으로 남긴다.

완료 기준:

- Claude -> Codex 또는 Codex -> Claude smoke 1개 이상 성공.
- 실패 시 Claude adapter는 experimental flag 뒤에 둔다.

## 9. 테스트 전략

### 8.1 Unit tests

- provider ref parser.
- Markdown transcript parser.
- JSONL streaming parser.
- Antigravity `<USER_REQUEST>` extraction.
- Codex app-server response parser.
- redaction scanner.
- prompt renderer.
- checkpoint hash canonicalization.

### 8.2 Integration tests

- fake source + fake target으로 `dry-run` artifact 생성.
- `sync --confirm` target send 호출 검증.
- duplicate checkpoint 차단.
- `--allow-duplicate` 우회.
- `--redact off` unsafe guard.

### 8.3 Live tests

Live tests는 로컬에서만 실행한다. Cloud 환경에서 Grok/Antigravity/Claude CLI 부재를 실패로 처리하지 않는다.

```bash
pytest -m live_codex
pytest -m live_grok
pytest -m live_antigravity
pytest -m live_claude
```

`scripts/live-smoke.sh --matrix <file>`는 `<from> <to> <cwd> [sync]` 형식의 matrix row를 순차 실행한다. `sync`가 없는 row는 dry-run만 수행해 target mutation을 피한다.

### 8.4 Security tests

- prompt에 private key block이 남지 않는지 검사.
- bearer token이 mask되는지 검사.
- `.env` 값이 제거되는지 검사.
- redaction report에 원문 secret이 없는지 검사.
- raw transcript 전체가 prompt에 inline되지 않는지 검사.

## 10. 릴리스 계획

### v0.1.0: Local dry-run MVP

- fake, Grok export fixture, Antigravity JSONL fixture, Codex app-server fixture.
- `doctor`, `inspect`, `dry-run`.
- handoff artifact 생성.
- redaction 기본 구현.

### v0.2.0: First sync MVP

- Codex, Grok, Antigravity target send.
- `sync --confirm`.
- checkpoint duplicate guard. 현재 checkpoint는 `last_source_range`를 기록해 `--range since-last` incremental handoff의 기준점으로 사용된다.
- local live smoke 문서화. 현재 단일 case와 matrix file(`scripts/live-smoke.sh --matrix`)을 지원한다.
- target prompt argv guard. 현재 `AGENT_XFER_PROMPT_ARG_MAX`를 초과하면 provider CLI 호출 전 안전하게 실패한다.

### v0.3.0: Robust provider support

- Codex app-server lifecycle 안정화. 현재 `AGENT_XFER_CODEX_APP_SERVER_COMMAND`가 설정된 경우 JSON-RPC `thread/read` 요청을 실행해 app-server response를 직접 읽고, fixture path(`AGENT_XFER_CODEX_THREAD_READ_JSON`)는 우선순위 높은 deterministic fallback으로 유지한다. Timeout/retry는 `AGENT_XFER_CODEX_APP_SERVER_TIMEOUT`/`AGENT_XFER_CODEX_APP_SERVER_RETRIES`로 제어한다.
- Grok trace optional enrich. 현재는 `AGENT_XFER_GROK_TRACE_ARCHIVE=/path/to/trace.tar.gz`가 설정된 경우 `chat_history.jsonl`을 우선 파싱하고, 없으면 `summary.json`의 Markdown-like summary로 fallback하는 source path를 지원한다.
- Antigravity path resolver 강화. 현재 `antigravity:last|cwd|current` alias를 `cache/last_conversations.json`의 cwd mapping으로 해석하고, `AGENT_XFER_ANTIGRAVITY_TRANSCRIPT` fixture override를 지원한다.
- sources/targets command 개선. 현재는 shallow discovery로 fake defaults, CLI availability, env-backed paths, Antigravity last_conversations cwd match를 제공한다. `sources --deep`은 Grok `sessions --json`과 Antigravity brain transcripts를 추가로 탐색한다.
- Incremental range selection. 현재 `dry-run`/`sync`에서 `--range all|since-last`를 지원하며, `since-last`는 같은 source/target checkpoint 이후의 event만 포함하고 새 event가 없으면 `NO_NEW_EVENTS`로 중단한다.

### v0.4.0: Claude experimental

- Claude SDK source adapter.
- Claude JSONL fallback.
- Claude target send smoke.

### v0.5.0: Python packaging and JavaScript/TypeScript packaging 검토

- Python packaging: 현재 `pyproject.toml`이 `agent-xfer` package metadata와 `agent-xfer = agent_xfer.cli:main` console script를 제공한다.
- npm wrapper 또는 TypeScript CLI 재구현 타당성 검토.
- Python core를 유지할지, TS wrapper가 Python module을 호출할지 결정.
- JS 생태계 배포가 실제 사용자 설치 경험을 개선하는지 검증.

### v1.0.0: 안정화

- schema versioning. 현재 handoff/checkpoint/prompt renderer schema constants를 `agent_xfer.core.schema`에서 관리하고 `doctor` JSON에 노출한다.
- backward-compatible checkpoint migration. 현재 `last_source_range`가 없는 legacy checkpoint에서 `--range since-last`를 요청하면 `CHECKPOINT_RANGE_UNAVAILABLE`로 안전하게 중단하고, `--range all`로 fresh checkpoint를 만들도록 유도한다.
- robust docs. 현재 `export` 명령을 포함한 read-only artifact export 흐름을 README/PRD에 문서화했다.
- install/packaging 정리. 현재 Python package metadata와 console script entrypoint는 추가되었고, 배포 자동화/릴리스 절차는 후속 작업이다.

## 11. 의사결정 기록

| 결정 | 선택 | 이유 |
|---|---|---|
| target 세션 파일 직접 수정 | 하지 않음 | 세션 손상과 metadata 불일치 방지 |
| tool call replay | 하지 않음 | side effect와 provider schema 차이 방지 |
| MVP 언어 | Python core + POSIX sh wrapper | Python은 JSONL/Markdown/redaction/checkpoint에 적합하고, sh는 설치 없는 launcher와 smoke helper에 적합 |
| MVP provider | Codex/Grok/Antigravity | 로컬 검증이 강함 |
| Claude | optional/2차 | 로그인 환경 live smoke 미완료 |
| Antigravity source | transcript JSONL | export CLI 없음, 로컬 path 검증됨 |
| Grok source | export 우선 | Markdown으로 단순하고 검증됨 |
| Codex source | app-server 우선 | `thread/read includeTurns` 구조화 read 검증됨 |

## 12. 남은 질문

- Codex app-server protocol을 CLI에서 장시간 띄울 때 timeout/retry 정책은 어떻게 둘 것인가? 현재 one-shot command read에 `AGENT_XFER_CODEX_APP_SERVER_TIMEOUT`/`AGENT_XFER_CODEX_APP_SERVER_RETRIES`를 제공한다.
- target prompt를 argv로 넘길 때 길이 제한에 걸리면 provider별 stdin/tempfile 대체 경로가 있는가? 현재는 `AGENT_XFER_PROMPT_ARG_MAX` guard로 provider CLI 호출 전 실패시킨다.
- redaction strict mode에서 내부 path를 어디까지 보존할 것인가?
- `sources`/`targets` command가 provider별 session list를 어느 깊이까지 지원해야 하는가? 현재 `sources --deep`은 Grok `sessions --json`과 Antigravity brain transcript directory를 지원한다.
- Claude SDK의 실제 method 이름과 auth behavior를 구현 시점에 어떤 version에 pin할 것인가?
- Antigravity transcript schema 변경을 감지하기 위한 healthcheck signature를 어떻게 정의할 것인가?
