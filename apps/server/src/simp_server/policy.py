"""Which tool calls run without asking. The real walls are the sandbox's: no route out but the workspace store, a
read-only toolset, no root. These rules only (a) ask before outward MCP actions the user would want to see, and (b)
turn predictable dead ends (installs, curl) into an immediate reason the model can act on. Regexes are bypassable by
design and are not the security boundary; a false match is worse than a miss (it misleads the model or nags the user),
so a keyword counts only as the command word. ponytail: stopgap — narrow tools/env/instructions instead of more rules."""

from __future__ import annotations

import re
from typing import Literal

Verdict = Literal["allow", "ask", "deny"]

# command position: line start or after ; & | $( `  — optionally behind sudo / env A=1, and a path (/x/bin/pip)
_AT = r"(?:^|[;&|]\s*|\$\(\s*|`\s*)\s*(?:sudo\s+|env\s+(?:\w+=\S*\s+)*)?(?:\S*/)?"
INSTALL = re.compile(_AT + r"(?:pip3?\s+install|pipx|conda|apt|apt-get|npx|uv\s+(?:pip|add|tool)|"
                           r"npm\s+(?:i|install|add|ci)|python3?\s+-m\s+pip)\b")
BROWSE = re.compile(_AT + r"pip3?\s+(?:list|freeze|show)\b|" + _AT + r"(?:ls|find|tree|du)\s+[^;&|]*/opt/simp")
NET = re.compile(_AT + r"(?:curl|wget|nc|ncat|ssh|scp|sftp|rsync|telnet)\b")
# MCP tools whose name starts with a write verb are asked even when their server marks them read-only
MCP_WRITE = re.compile(r"^(?:send|delete|remove|trash|share|create|update|insert|append|move|reply|post|upload|"
                       r"write|add|set|modify|patch|rename|copy|archive)(?:_|$)", re.I)
NO_NET = ("The sandbox has no internet. Get web data only with web_search / web_fetch (raw=true for page source); "
          "save files (images, PDFs) with web_download, many in one call. If they fail, say so; do not try curl.")


def classify(call, mcp_write: bool, available: str, net_blocked: bool = True) -> tuple[Verdict, str]:
    """mcp_write: an MCP tool its server does not mark read-only. available: the preinstalled toolset (for the reason).
    net_blocked: the sandbox really has no network (E2B allowlist); else network commands just run."""
    if call.name == "bash":
        cmd = str(call.arguments.get("command", ""))
        if INSTALL.search(cmd):
            return "deny", f"packages cannot be installed; libraries are fixed. {available}"
        if BROWSE.search(cmd):
            return "deny", f"not available. {available}"
        if net_blocked and NET.search(cmd):
            return "deny", NO_NET
        return "allow", ""
    if "__" in call.name:  # MCP tools are named <app>__<tool>
        if mcp_write or MCP_WRITE.search(call.name.partition("__")[2]):
            return "ask", "changes data outside the sandbox"
    return "allow", ""


class Policy:
    """Session plugin: blocks `deny` calls with their reason (before any approval prompt)."""

    name = "policy"

    def __init__(self, verdict):
        self.verdict = verdict  # call -> (Verdict, reason)

    def tool_call(self, call):
        v, why = self.verdict(call)
        return {"block": why} if v == "deny" else None
