"""A settings profile (plain dict from TOML) -> Model. Shared by the CLI and the server."""

from __future__ import annotations

from simp_agent.ai import Model


def build_model(pr: dict) -> Model:
    api = pr.get("api", "anthropic-messages")
    kw = {"id": pr.get("model"), "api": api, "provider": "openai" if api.startswith("openai") else "anthropic",
          "base_url": pr.get("base_url"), "api_key_env": pr.get("api_key_env"), "compat": dict(pr.get("compat", dict()))}
    kw.update({k: pr[k] for k in ("max_tokens", "context_window") if k in pr})
    if api.startswith("openai"):
        kw["compat"].setdefault("include_usage", True)
    return Model(**{k: v for k, v in kw.items() if v is not None})  # None -> Model's default
