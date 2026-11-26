"""JSON logs and backups for running the server as a long-lived service on one machine."""

from __future__ import annotations

import json
import os
import re
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
        for name in ("settings.toml", "workspaces", "sandboxes", "skills"):
            if (data_dir / name).exists():
                tar.add(data_dir / name, name)
    if keep > 0:  # names sort by time
        for old in sorted(dest.glob("simp-*.tar.gz"))[:-keep]:
            old.unlink()
    return out


def env_value(data_dir: str, name: str) -> str:
    """name from the process env, else from <data_dir>/.env ("" if unset)."""
    if os.environ.get(name):
        return os.environ[name]
    f = Path(data_dir) / ".env"
    for line in f.read_text().splitlines() if f.exists() else ():
        k, sep, v = line.partition("=")
        if sep and k.strip() == name and not line.lstrip().startswith("#"):
            return v.strip().strip("'\"")
    return ""


_SECRETISH = re.compile(r"(?i)(authorization|cookie|token|secret|key|password|dsn|credential)")


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: "[Filtered]" if isinstance(k, str) and _SECRETISH.search(k) else _scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    if isinstance(obj, str):
        return re.sub(r"\b(sk-[\w-]{8,}|e2b_\w{8,}|Bearer\s+\S+|[A-Za-z0-9_-]{32,})", "[Filtered]", obj)
    return obj


def setup_sentry(data_dir: str) -> bool:
    """Error reporting to Sentry, only when SENTRY_DSN is set (env or <data_dir>/.env). No PII, keys scrubbed."""
    dsn = env_value(data_dir, "SENTRY_DSN")
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(dsn=dsn, send_default_pii=False, traces_sample_rate=float(env_value(data_dir, "SENTRY_TRACES_RATE") or 0),
                    before_send=lambda event, hint: _scrub(event), before_send_transaction=lambda event, hint: _scrub(event))
    return True
