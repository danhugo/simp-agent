"""Example plugins: they prove the session sockets. Library code, no app deps."""

from .plan_mode import PlanMode
from .redact_secrets import RedactSecrets

__all__ = ["PlanMode", "RedactSecrets", "build_plugins"]


def build_plugins(names: list[str]) -> list:
    known = {"redact_secrets": RedactSecrets, "plan_mode": PlanMode}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(f"unknown plugin {unknown[0]!r}; have {sorted(known)}")
    return [known[n]() for n in names]
