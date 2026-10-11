"""JSON logs and backups for running the server as a long-lived service on one machine."""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

_STD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {"ts": round(r.created, 3), "level": r.levelname, "msg": r.getMessage()}
        d.update({k: v for k, v in vars(r).items() if k not in _STD})
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)


def backup(data_dir: Path, dest: Path, keep: int = 0) -> Path:
    data_dir, dest = Path(data_dir), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"simp-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(out, "w:gz") as tar:
        if (data_dir / "simp.db").exists():
            snap = Path(tmp) / "simp.db"
            src, dst = sqlite3.connect(data_dir / "simp.db"), sqlite3.connect(snap)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            tar.add(snap, "simp.db")
        for name in ("settings.toml", "workspaces", "sandboxes"):
            if (data_dir / name).exists():
                tar.add(data_dir / name, name)
    if keep > 0:  # names sort by time
        for old in sorted(dest.glob("simp-*.tar.gz"))[:-keep]:
            old.unlink()
    return out
