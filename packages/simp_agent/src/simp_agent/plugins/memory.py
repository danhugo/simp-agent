"""Memory: the agent saves facts/lessons with tools; core text from store.load() goes into the prompt each turn."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Protocol

from ..agent import AgentTool

RULES = """# Memory
You have long-term memory. Scopes: "global" = facts and preferences about the USER; "agent" = lessons you learned doing tasks.
- Save with memory_save when you learn a lasting user fact/preference (global) or a useful task lesson (agent). Keep each item short.
- Use memory_search when past facts or lessons may help, before asking the user again.
- NEVER save secrets, passwords, API keys, tokens or other sensitive data, unless the user explicitly asks."""


class MemoryStore(Protocol):
    """Item = {"id", "scope", "content", "created"}. scope is a plain string ("global", "agent", ...)."""

    def load(self) -> str: ...
    def search(self, query: str, scope: str | None = None, limit: int = 10) -> list[dict]: ...
    def save(self, content: str, scope: str) -> str: ...
    def delete(self, id: str) -> bool: ...


class FileMemoryStore:
    """One JSONL file per scope under dir. load() = newest items up to max_chars."""

    def __init__(self, dir: str | Path, max_chars: int = 2000):
        self.dir, self.max_chars = Path(dir).expanduser(), max_chars

    def _file(self, scope: str) -> Path:
        if not scope or "/" in scope or "\\" in scope or scope.startswith("."):
            raise ValueError(f"bad scope {scope!r}")
        return self.dir / f"{scope}.jsonl"

    @staticmethod
    def _parse(line: str) -> dict | None:
        try:
            item = json.loads(line)
        except ValueError:
            return None
        ok = isinstance(item, dict) and all(isinstance(item.get(k), str) for k in ("id", "scope", "content"))
        return item if ok and isinstance(item.get("created"), (int, float)) else None

    def _items(self, scope: str | None = None) -> list[dict]:
        files = [self._file(scope)] if scope else sorted(self.dir.glob("*.jsonl"))
        items = [i for f in files if f.exists() for line in f.read_text(errors="replace").splitlines() if (i := self._parse(line))]
        return sorted(items, key=lambda i: i["created"], reverse=True)  # newest first

    def load(self) -> str:
        lines, used = [], 0
        for i in self._items():
            line = f"- [{i['scope']}] {i['content']}"
            if used + len(line) > self.max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    def search(self, query: str, scope: str | None = None, limit: int = 10) -> list[dict]:
        words = query.lower().split()  # ponytail: keyword match, swap in a real index if memory grows big
        return [i for i in self._items(scope) if all(w in i["content"].lower() for w in words)][:limit]

    def save(self, content: str, scope: str) -> str:
        path = self._file(scope)
        item = {"id": uuid.uuid4().hex[:12], "scope": scope, "content": content, "created": time.time()}
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(item) + "\n")
        return item["id"]

    def delete(self, id: str) -> bool:
        for f in self.dir.glob("*.jsonl"):
            lines = f.read_text(errors="replace").splitlines()
            keep = [l for l in lines if l.strip() and (self._parse(l) or {}).get("id") != id]
            if len(keep) != len([l for l in lines if l.strip()]):
                f.write_text("".join(l + "\n" for l in keep))
                return True
        return False


def _obj(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required}


class Memory:
    """config (via build_plugins): dir (default ~/.simp_agent/memory), max_chars. Or pass your own store."""

    name = "memory"

    def __init__(self, store: MemoryStore | None = None):
        self.store = store

    def setup(self, api, config: dict) -> None:
        if self.store is None:
            self.store = FileMemoryStore(config.get("dir", "~/.simp_agent/memory"), config.get("max_chars", 2000))
        api.add_prompt_section(self.name, self.prompt, 500)
        s = {"type": "string"}
        api.register_tool(AgentTool("memory_search", "Search long-term memory. Returns matching items as JSON.",
                                    _obj({"query": s, "scope": {**s, "description": "global | agent (optional)"}}, ["query"]),
                                    self._search))
        api.register_tool(AgentTool("memory_save", "Save one short fact (scope global) or lesson (scope agent). Never secrets.",
                                    _obj({"content": s, "scope": {**s, "description": "global | agent"}}, ["content", "scope"]),
                                    self._save))
        api.register_tool(AgentTool("memory_delete", "Delete a memory item by id.", _obj({"id": s}, ["id"]), self._delete))

    def prompt(self, ctx=None) -> str:  # callable section: rebuilt every turn, so new saves show up
        core = self.store.load()
        return f"{RULES}\n\n## Remembered\n{core}" if core else RULES

    async def _search(self, args, ctx) -> str:
        return json.dumps(self.store.search(args["query"], args.get("scope") or None), ensure_ascii=False)

    async def _save(self, args, ctx) -> str:
        return f"saved {self.store.save(args['content'], args['scope'])}"

    async def _delete(self, args, ctx) -> str:
        return "deleted" if self.store.delete(args["id"]) else "not found"
