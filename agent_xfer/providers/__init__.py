from __future__ import annotations

from agent_xfer.providers.antigravity import AntigravityAdapter
from agent_xfer.providers.claude import ClaudeAdapter
from agent_xfer.providers.codex import CodexAdapter
from agent_xfer.providers.fake import FakeAdapter
from agent_xfer.providers.grok import GrokAdapter


def get_adapter(provider: str):
    if provider == "fake":
        return FakeAdapter()
    if provider == "grok":
        return GrokAdapter()
    if provider == "antigravity":
        return AntigravityAdapter()
    if provider == "codex":
        return CodexAdapter()
    if provider == "claude":
        return ClaudeAdapter()
    raise NotImplementedError(
        f"provider '{provider}' is not implemented yet; supported providers: fake, grok, antigravity, codex, claude"
    )
