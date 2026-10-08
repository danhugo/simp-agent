"""Plan mode: block write/edit/bash and tell the model to plan only. State is a custom entry, so it survives resume."""

from __future__ import annotations

from ..ai import CustomEntry

BLOCKED = {"write", "edit", "bash"}
PROMPT = "PLAN MODE is on: plan only. Read and explore, then describe the plan. Do not change files or run commands."


class PlanMode:
    name = "plan_mode"

    def __init__(self):
        self.enabled, self.api = False, None

    def setup(self, api, config: dict) -> None:
        self.api = api
        last = next((m for m in reversed(api.get_messages()) if isinstance(m, CustomEntry) and m.type == self.name), None)
        self._apply(last.data["enabled"] if last else bool(config.get("enabled", False)))

    def _apply(self, on: bool) -> None:
        self.enabled = on
        if on:
            self.api.add_prompt_section(self.name, PROMPT, 1000)
        else:
            self.api.remove_prompt_section(self.name)

    async def set_enabled(self, on: bool) -> None:
        self._apply(on)
        await self.api.append_entry(self.name, {"enabled": on})

    def tool_call(self, call):
        if self.enabled and call.name in BLOCKED:
            return {"block": "plan mode is on (read-only)"}
        return None
