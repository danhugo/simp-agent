"""Example plugins: they prove the session sockets. Library code, no app deps."""

from .plan_mode import PlanMode
from .redact_secrets import RedactSecrets

__all__ = ["PlanMode", "RedactSecrets"]
