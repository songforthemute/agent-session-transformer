from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable

from agent_xfer.core.models import NormalizedEvent, RedactionFinding, RedactionReport

BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|refresh[_-]?token|oauth[_-]?token|secret|password)\b(\s*[=:]\s*)([^\s]+)",
    re.IGNORECASE,
)
ENV_ASSIGNMENT_RE = re.compile(r"^([A-Z_][A-Z0-9_]{2,})(=)(.+)$", re.MULTILINE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATH_RE = re.compile(r"/(Users|home)/[^\s:]+")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)
HIGH_ENTROPY_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")

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


def _replace(pattern: re.Pattern[str], text: str, state: _RedactionState, kind: str, action: str, replacement: str | Callable[[re.Match[str]], str]) -> str:
    def sub(match: re.Match[str]) -> str:
        state.record(kind, action, match.group(0))
        if callable(replacement):
            return replacement(match)
        return replacement

    return pattern.sub(sub, text)


def _redact_secret_assignment(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}[REDACTED]"


def _redact_env_assignment(match: re.Match[str], state: _RedactionState) -> str:
    key = match.group(1)
    value = match.group(3)
    upper_key = key.upper()
    if upper_key in SECRET_ENV_NAMES or any(token in upper_key for token in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
        state.record("env_var", "dropped", value)
        return f"{key}=[REDACTED]"
    return match.group(0)


def redact_text(text: str, mode: str = "secrets") -> tuple[str, _RedactionState]:
    state = _RedactionState()
    redacted = text
    redacted = _replace(PRIVATE_KEY_RE, redacted, state, "private_key", "dropped", "[REDACTED_PRIVATE_KEY]")
    redacted = _replace(BEARER_RE, redacted, state, "oauth_token", "masked", "Bearer [REDACTED_TOKEN]")
    redacted = _replace(SECRET_ASSIGNMENT_RE, redacted, state, "api_key", "masked", _redact_secret_assignment)

    def env_sub(match: re.Match[str]) -> str:
        return _redact_env_assignment(match, state)

    redacted = ENV_ASSIGNMENT_RE.sub(env_sub, redacted)
    redacted = _replace(EMAIL_RE, redacted, state, "email", "masked", "[REDACTED_EMAIL]")
    redacted = _replace(HOME_PATH_RE, redacted, state, "internal_path", "masked", "~/[REDACTED_PATH]")
    if mode == "strict":
        redacted = _replace(HIGH_ENTROPY_RE, redacted, state, "high_entropy", "masked", "[REDACTED_HIGH_ENTROPY]")
    return redacted, state


def redact_events(events: list[NormalizedEvent], mode: str = "secrets") -> tuple[list[NormalizedEvent], RedactionReport]:
    if mode == "off":
        raise ValueError("redaction mode 'off' requires an unsafe override that is intentionally not supported")
    aggregate_counts: Counter[str] = Counter()
    aggregate_actions: dict[str, str] = {}
    aggregate_samples: dict[str, str] = {}
    redacted_events: list[NormalizedEvent] = []
    for event in events:
        text, state = redact_text(event.content_text, mode)
        aggregate_counts.update(state.counts)
        aggregate_actions.update(state.actions)
        for kind, sample in state.samples.items():
            aggregate_samples.setdefault(kind, sample)
        redacted_events.append(NormalizedEvent(**{**event.to_dict(), "content_text": text}))
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
