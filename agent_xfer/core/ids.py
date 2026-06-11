from __future__ import annotations

from dataclasses import dataclass

ID_KINDS = {
    "codex": "thread_id",
    "grok": "session_id",
    "antigravity": "conversation_id",
    "claude": "session_id",
    "fake": "session_id",
}


@dataclass(frozen=True)
class ProviderRef:
    provider: str
    id: str
    id_kind: str

    @classmethod
    def parse(cls, value: str) -> "ProviderRef":
        if ":" not in value:
            raise ValueError("provider ref must be in '<provider>:<id>' form")
        provider, ident = value.split(":", 1)
        provider = provider.strip().lower()
        ident = ident.strip()
        if not provider or not ident:
            raise ValueError("provider ref requires both provider and id")
        if provider not in ID_KINDS:
            known = ", ".join(sorted(ID_KINDS))
            raise ValueError(f"unknown provider '{provider}' (known: {known})")
        return cls(provider=provider, id=ident, id_kind=ID_KINDS[provider])

    def key(self) -> str:
        safe_id = self.id.replace("/", "_").replace(":", "_")
        return f"{self.provider}__{safe_id}"
