"""Replay a session's first <cut> entries into the summarizer and print the summary.
Usage: uv run scripts/replay_compaction.py <session.jsonl> <cut> [--profile NAME]. Model from ~/.simp-agent/settings.json, key from env."""

import argparse
import asyncio
import json
from pathlib import Path

from simp_agent import ai
from simp_agent.agent.compaction import CompactionSettings, file_lists, format_files, summarize
from simp_agent.cli import SETTINGS, build_model, resolve_config


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("session")
    p.add_argument("cut", type=int)
    p.add_argument("--profile")
    a = p.parse_args()
    flags = argparse.Namespace(profile=a.profile, api=None, model=None, base_url=None, context_window=None, max_tokens=None,
                               max_tokens_field=None, reasoning_effort=None, no_include_usage=False)
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    model = build_model(resolve_config(settings, flags))
    lines = [ln for ln in Path(a.session).read_text().splitlines() if ln.strip()][: a.cut]
    old = [m for m in map(ai.from_dict, map(json.loads, lines)) if not isinstance(m, ai.CompactionEntry)]
    summary = await summarize(ai.stream, model, old, None, CompactionSettings().reserve_tokens)
    print(summary + format_files(*file_lists(old, None)))


asyncio.run(main())
