"""Test fakes shared by every package: a scripted provider and a recording env."""

from __future__ import annotations

from .agent.env import LocalEnv


class FakeProvider:
    """A stream_fn that plays scripted replies in order. A reply may be a callable (ctx) -> message.
    Records each call: ctxs (the Context), messages (a copy of ctx.messages), api_keys, models."""

    def __init__(self, *replies):
        self.replies = iter(replies)
        self.ctxs, self.messages, self.api_keys, self.models = [], [], [], []

    async def __call__(self, model, ctx, api_key=None):
        self.ctxs.append(ctx)
        self.messages.append(list(ctx.messages))
        self.api_keys.append(api_key)
        self.models.append(model)
        msg = next(self.replies)
        msg = msg(ctx) if callable(msg) else msg
        yield {"type": "start", "partial": msg}
        yield {"type": "error" if msg.stop_reason == "error" else "done", "message": msg}


class FakeEnv(LocalEnv):
    """LocalEnv that records commands; programs in `missing` exit 127, `canned` returns fixed output."""

    def __init__(self, missing=(), canned=None, root=None):
        super().__init__(root)
        self.cmds, self.missing, self.canned = [], missing, canned or {}

    async def exec(self, command, cwd, timeout, cancel, on_output=None):
        self.cmds.append(command)
        prog = command.split()[0]
        if prog in self.missing:
            return 127, f"sh: {prog}: command not found"
        if prog in self.canned:
            return 0, self.canned[prog]
        return await super().exec(command, cwd, timeout, cancel, on_output)
