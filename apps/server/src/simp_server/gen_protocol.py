"""Regenerate apps/web/src/protocol.gen.ts from protocol.py. `--check` exits 1 on drift (CI)."""

import subprocess
import sys
from pathlib import Path

from simp_server.protocol import json_schema

OUT = Path(__file__).resolve().parents[4] / "apps/web/src/protocol.gen.ts"


def generate() -> str:
    cmd = ["npx", "--yes", "json-schema-to-typescript@15", "--bannerComment",
           "/* Generated from apps/server/src/simp_server/protocol.py. Do not edit; run gen_protocol. */",
           "--unreachableDefinitions"]
    return subprocess.run(cmd, input=json_schema(), capture_output=True, text=True, check=True).stdout


if __name__ == "__main__":
    ts = generate()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text() == ts else "protocol.gen.ts is stale: run gen_protocol")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(ts)
