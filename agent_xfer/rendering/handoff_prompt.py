from __future__ import annotations

from agent_xfer.core.ids import ProviderRef
from agent_xfer.core.models import NormalizedEvent

TRUNCATION_NOTICE = "[agent-xfer: prompt truncated to respect --max-prompt-chars]"


def _apply_budget(prompt: str, max_chars: int | None) -> str:
    if max_chars is None or max_chars <= 0 or len(prompt) <= max_chars:
        return prompt
    if max_chars <= len(TRUNCATION_NOTICE) + 1:
        return TRUNCATION_NOTICE[:max_chars]
    keep = max_chars - len(TRUNCATION_NOTICE) - 2
    return prompt[:keep].rstrip() + "\n\n" + TRUNCATION_NOTICE


def render_prompt(source: ProviderRef, target: ProviderRef, cwd: str, events: list[NormalizedEvent], max_chars: int | None = None) -> str:
    user_messages = [event.content_text for event in events if event.role == "user"]
    assistant_messages = [event.content_text for event in events if event.role == "assistant"]
    original_goal = user_messages[0] if user_messages else "Unknown. Inspect source artifacts for details."
    current_state = assistant_messages[-1] if assistant_messages else "No assistant summary was available."
    prompt = "\n".join(
        [
            "# Agent Handoff",
            "",
            "You are resuming work that was started in another coding agent.",
            "Do not assume this is a lossless transcript conversion. Treat it as a task handoff summary.",
            "Do not replay tool calls. Continue from the current repository state.",
            "",
            "## Source",
            f"- Provider: {source.provider}",
            f"- Source id: {source.id}",
            f"- Source id kind: {source.id_kind}",
            f"- CWD: {cwd}",
            "",
            "## Target",
            f"- Provider: {target.provider}",
            f"- Target id: {target.id}",
            f"- Target id kind: {target.id_kind}",
            "",
            "## Original user goal",
            original_goal,
            "",
            "## Current state",
            current_state,
            "",
            "## Pending work",
            "- Inspect the repository state before editing.",
            "- Continue from the current state and avoid repeating completed work unless verification requires it.",
            "",
            "## Event summary",
            *[f"- [{event.role}/{event.kind}] {event.content_text}" for event in events],
            "",
        ]
    )
    return _apply_budget(prompt, max_chars)
