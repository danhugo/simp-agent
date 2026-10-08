"""Mask secrets in tool output (tool_result) and in everything sent to the LLM (context)."""

from __future__ import annotations

import dataclasses
import os
import re

PATTERNS = re.compile(
    r"sk-[A-Za-z0-9_-]{16,}"  # OpenAI / Anthropic style keys
    r"|eyJ[\w-]+\.[\w-]+\.[\w-]+"  # JWT
    r"|AKIA[0-9A-Z]{16}"  # AWS access key id
    r"|gh[pousr]_[A-Za-z0-9]{30,}"  # GitHub tokens
)
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.I)
MASK = "[REDACTED]"
SKIP = {"id", "signature", "type", "role"}  # opaque provider data: masking breaks it


class RedactSecrets:
    """config: secrets = extra known values; env = also mask values of *KEY*/*TOKEN*/*SECRET*/*PASSWORD* env vars."""

    name = "redact_secrets"

    def __init__(self):
        self.secrets: list[str] = []

    def setup(self, api, config: dict) -> None:
        values = list(config.get("secrets", []))
        if config.get("env", True):
            values += [v for k, v in os.environ.items() if SECRET_ENV.search(k)]
        self.secrets = sorted({v for v in values if len(v) >= 8}, key=len, reverse=True)  # longest first

    def mask(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, MASK)
        return PATTERNS.sub(MASK, text)

    def tool_result(self, call, result):
        masked = self.mask(result.content)
        return {"content": masked} if masked != result.content else None

    def tool_update(self, call, text: str) -> str:
        return self.mask(text)

    def deep(self, x):
        """Mask every string field (text, thinking, tool call args, nested lists/dicts). Returns copies."""
        if isinstance(x, str):
            return self.mask(x)
        if isinstance(x, list):
            return [self.deep(v) for v in x]
        if isinstance(x, dict):
            return {k: self.deep(v) for k, v in x.items()}
        if dataclasses.is_dataclass(x) and not isinstance(x, type):
            return dataclasses.replace(x, **{f.name: self.deep(getattr(x, f.name)) for f in dataclasses.fields(x)
                                             if f.init and f.name not in SKIP})
        return x

    def context(self, messages: list) -> list:  # copies only: history keeps the original
        return [self.deep(m) for m in messages]
