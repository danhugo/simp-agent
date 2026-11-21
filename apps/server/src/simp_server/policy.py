"""Which tool calls run without asking. The real walls are the sandbox's: no route out but the workspace store, a
read-only toolset, no root. These rules only (a) ask before outward actions the user would want to see, and (b) turn
predictable dead ends (installs, curl) into an immediate reason the model can act on. Regexes are bypassable by design;
nothing here is the security boundary."""

from __future__ import annotations

import re
from typing import Literal

Verdict = Literal["allow", "ask", "deny"]

INSTALL = re.compile(r"\bpip3?\b[^;&|]*\binstall\b|-m\s+pip\b|\buv\s+(pip|add|tool)\b|\bnpm\s+(i|install|add|ci)\b|"
                     r"\bnpx\b|\bpipx\b|\bconda\b|\bapt(-get)?\b")
BROWSE = re.compile(r"/opt/simp|\bpip3?\s+(list|freeze|show)\b")
NET = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|sftp|rsync|telnet)\b")
ASK_BASH = re.compile(r"\bgit\s+push\b")
# MCP tools named like a write are asked even when their server marks them read-only
MCP_WRITE = re.compile(r"send|delete|remove|trash|share|permission|create|update|insert|append|move|reply|post|draft",
                       re.I)
NO_NET = "the sandbox has no internet. Use web_search / web_fetch (raw=true for page source); if they fail, say so."


def classify(call, mcp_write: bool, available: str) -> tuple[Verdict, str]:
    """mcp_write: the call is an MCP tool its server does not mark read-only. available: the preinstalled toolset."""
    if call.name == "bash":
        cmd = str(call.arguments.get("command", ""))
        if INSTALL.search(cmd):
            return "deny", f"packages cannot be installed; libraries are fixed. {available}"
        if BROWSE.search(cmd):
            return "deny", f"not available. {available}"
        if NET.search(cmd):
            return "deny", NO_NET
        if ASK_BASH.search(cmd):
            return "ask", "pushes to a remote"
        return "allow", ""
    if "__" in call.name:  # MCP tools are named <app>__<tool>
        tool = call.name.partition("__")[2]
        if mcp_write or MCP_WRITE.search(tool):
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
