import re
import shutil
from pathlib import Path


def user_root(workspaces: Path, legacy: Path, user_id: str, sid: str) -> Path:
    """The user's workspace dir, shared by all their sessions. One-time migration of old per-session dirs:
    sandboxes/<sid> (Stage 2) or workspaces/<sid> -> workspaces/<user_id>/<sid>/ (skipped once moved)."""
    for name in (user_id, sid):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError(f"bad id: {name!r}")
    root = workspaces / user_id
    root.mkdir(parents=True, exist_ok=True)
    for old in (legacy / sid, workspaces / sid):
        if old.exists() and not (root / sid).exists():
            shutil.move(old, root / sid)
    return root
