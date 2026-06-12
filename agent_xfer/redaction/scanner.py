from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from agent_xfer.core.models import NormalizedEvent, RedactionFinding, RedactionReport

BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|refresh[_-]?token|oauth[_-]?token|secret|password)\b(\s*[=:]\s*)([^\s]+)",
    re.IGNORECASE,
)
ENV_ASSIGNMENT_RE = re.compile(r"^(export\s+)?([A-Z_][A-Z0-9_]{2,})(=)(.+)$", re.MULTILINE)
EXPORT_ENV_ASSIGNMENT_RE = re.compile(r"\b(export\s+)([A-Z_][A-Z0-9_]{2,})(=)([^\s]+)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATH_RE = re.compile(r"/(Users|home)/[^\s:]+")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)
HIGH_ENTROPY_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
PROVIDER_API_KEY_RE = re.compile(
    r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{12,}|xai-[A-Za-z0-9_-]{12,}|"
    r"ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AIza[0-9A-Za-z_-]{20,})\b"
)

SECRET_ENV_NAMES = {
    "API_KEY",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "OAUTH_TOKEN",
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
}

SECRET_JSON_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "bearer_token",
    "client_secret",
    "github_token",
    "oauth_token",
    "openai_api_key",
    "anthropic_api_key",
    "password",
    "passwd",
    "private_key",
    "refresh_token",
    "secret",
    "session_token",
    "token",
}

SAFE_TOKEN_COUNT_KEYS = {"completion_tokens", "prompt_tokens", "total_tokens"}



def _normalized_json_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def _is_secret_json_key(key: str) -> bool:
    normalized = _normalized_json_key(key)
    if normalized in SAFE_TOKEN_COUNT_KEYS:
        return False
    if normalized in SECRET_JSON_KEYS:
        return True
    return normalized.endswith(("_api_key", "_password", "_private_key", "_secret", "_token"))


def _record_json_secret_field(state: _RedactionState, key: str, value: Any) -> None:
    state.record("json_secret_field", "dropped", f"{key}={value!r}")


def _sample_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class _RedactionState:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.actions: dict[str, str] = {}
        self.samples: dict[str, str] = {}

    def record(self, kind: str, action: str, value: str) -> None:
        self.counts[kind] += 1
        self.actions[kind] = action
        self.samples.setdefault(kind, _sample_hash(value))

    def findings(self) -> list[RedactionFinding]:
        return [
            RedactionFinding(
                kind=kind,
                count=count,
                action=self.actions.get(kind, "masked"),
                sample_hash=self.samples.get(kind),
            )
            for kind, count in sorted(self.counts.items())
        ]


def _replace(
    pattern: re.Pattern[str],
    text: str,
    state: _RedactionState,
    kind: str,
    action: str,
    replacement: str | Callable[[re.Match[str]], str],
) -> str:
    def sub(match: re.Match[str]) -> str:
        state.record(kind, action, match.group(0))
        if callable(replacement):
            return replacement(match)
        return replacement

    return pattern.sub(sub, text)


def _redact_secret_assignment(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}[REDACTED]"


def _redact_env_assignment(match: re.Match[str], state: _RedactionState) -> str:
    export_prefix = match.group(1) or ""
    key = match.group(2)
    value = match.group(4)
    upper_key = key.upper()
    if upper_key in SECRET_ENV_NAMES or any(
        token in upper_key for token in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
    ):
        state.record("env_var", "dropped", value)
        return f"{export_prefix}{key}=[REDACTED]"
    return match.group(0)


def redact_text(text: str, mode: str = "secrets") -> tuple[str, _RedactionState]:
    state = _RedactionState()
    redacted = text
    redacted = _replace(
        PRIVATE_KEY_RE, redacted, state, "private_key", "dropped", "[REDACTED_PRIVATE_KEY]"
    )
    redacted = _replace(
        BEARER_RE, redacted, state, "oauth_token", "masked", "Bearer [REDACTED_TOKEN]"
    )
    redacted = _replace(
        SECRET_ASSIGNMENT_RE,
        redacted,
        state,
        "api_key",
        "masked",
        _redact_secret_assignment,
    )

    def env_sub(match: re.Match[str]) -> str:
        return _redact_env_assignment(match, state)

    redacted = EXPORT_ENV_ASSIGNMENT_RE.sub(env_sub, redacted)
    redacted = ENV_ASSIGNMENT_RE.sub(env_sub, redacted)
    redacted = _replace(
        PROVIDER_API_KEY_RE,
        redacted,
        state,
        "provider_api_key",
        "masked",
        "[REDACTED_PROVIDER_API_KEY]",
    )
    redacted = _replace(EMAIL_RE, redacted, state, "email", "masked", "[REDACTED_EMAIL]")
    redacted = _replace(
        HOME_PATH_RE, redacted, state, "internal_path", "masked", "~/[REDACTED_PATH]"
    )
    if mode == "strict":
        redacted = _replace(
            HIGH_ENTROPY_RE,
            redacted,
            state,
            "high_entropy",
            "masked",
            "[REDACTED_HIGH_ENTROPY]",
        )
    return redacted, state


def _merge_state(
    aggregate_counts: Counter[str],
    aggregate_actions: dict[str, str],
    aggregate_samples: dict[str, str],
    state: _RedactionState,
) -> None:
    aggregate_counts.update(state.counts)
    aggregate_actions.update(state.actions)
    for kind, sample in state.samples.items():
        aggregate_samples.setdefault(kind, sample)


def redact_json_value(value: Any, mode: str = "secrets") -> tuple[Any, _RedactionState]:
    state = _RedactionState()

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            redacted, item_state = redact_text(item, mode)
            state.counts.update(item_state.counts)
            state.actions.update(item_state.actions)
            for kind, sample in item_state.samples.items():
                state.samples.setdefault(kind, sample)
            return redacted
        if isinstance(item, list):
            return [walk(child) for child in item]
        if isinstance(item, dict):
            redacted_item: dict[Any, Any] = {}
            for key, child in item.items():
                if isinstance(key, str) and _is_secret_json_key(key):
                    _record_json_secret_field(state, key, child)
                    redacted_item[key] = "[REDACTED]"
                    continue
                redacted_item[key] = walk(child)
            return redacted_item
        return item

    return walk(value), state


def redact_events(
    events: list[NormalizedEvent], mode: str = "secrets"
) -> tuple[list[NormalizedEvent], RedactionReport]:
    if mode == "off":
        raise ValueError(
            "redaction mode 'off' requires an unsafe override that is intentionally not supported"
        )
    aggregate_counts: Counter[str] = Counter()
    aggregate_actions: dict[str, str] = {}
    aggregate_samples: dict[str, str] = {}
    redacted_events: list[NormalizedEvent] = []
    for event in events:
        text, text_state = redact_text(event.content_text, mode)
        content_json, json_state = redact_json_value(event.content_json, mode)
        _merge_state(aggregate_counts, aggregate_actions, aggregate_samples, text_state)
        _merge_state(aggregate_counts, aggregate_actions, aggregate_samples, json_state)
        redacted_events.append(
            NormalizedEvent(
                **{
                    **event.to_dict(),
                    "content_text": text,
                    "content_json": content_json,
                }
            )
        )
    findings = [
        RedactionFinding(
            kind=kind,
            count=count,
            action=aggregate_actions.get(kind, "masked"),
            sample_hash=aggregate_samples.get(kind),
        )
        for kind, count in sorted(aggregate_counts.items())
    ]
    notes = ["redaction completed before prompt rendering"]
    report = RedactionReport(mode=mode, findings=findings, notes=notes)
    return redacted_events, report
