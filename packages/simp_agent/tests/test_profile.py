import pytest

from simp_agent.plugins import build_plugins
from simp_agent.session.profile import build_model


def test_build_model_openai_defaults():
    m = build_model({"api": "openai-completions", "model": "x", "base_url": "http://h/v1", "context_window": 1000,
                     "api_key_env": "K"})
    assert (m.id, m.api, m.provider, m.base_url, m.api_key_env) == ("x", "openai-completions", "openai", "http://h/v1", "K")
    assert m.compat["include_usage"] is True and m.context_window == 1000


def test_build_model_keeps_explicit_compat():
    m = build_model({"api": "openai-responses", "model": "x", "compat": {"include_usage": False}})
    assert m.compat["include_usage"] is False


def test_build_plugins():
    assert [type(p).__name__ for p in build_plugins(["plan_mode", "redact_secrets"])] == ["PlanMode", "RedactSecrets"]
    with pytest.raises(ValueError, match="unknown plugin"):
        build_plugins(["nope"])
