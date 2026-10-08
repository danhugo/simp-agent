"""Mask secrets in tool output (tool_result) and in everything sent to the LLM (context)."""

from __future__ import annotations

import dataclasses
import os
import re

from ..ai import AssistantMessage, TextContent

PATTERNS = re.compile(
    r"sk-[A-Za-z0-9_-]{16,}"  # OpenAI / Anthropic style keys
    r"|eyJ[\w-]+\.[\w-]+\.[\w-]+"  # JWT
    r"|AKIA[0-9A-Z]{16}"  # AWS access key id
    r"|gh[pousr]_[A-Za-z0-9]{30,}"  # GitHub tokens
)
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.I)
MASK = "[REDACTED]"


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

    def context(self, messages: list) -> list:  # copies only: history keeps the original
        out = []
        for m in messages:
            if isinstance(m, AssistantMessage):
                content = [TextContent(self.mask(c.text), c.signature) if isinstance(c, TextContent) else c for c in m.content]
                m = dataclasses.replace(m, content=content)
            elif isinstance(getattr(m, "content", None), str):
                m = dataclasses.replace(m, content=self.mask(m.content))
            out.append(m)
        return out
