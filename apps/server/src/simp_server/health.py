"""/api/healthz and /api/readyz (no auth). readyz checks each dependency with a short timeout and caches the answer
CACHE_S seconds, so it can't be used to hammer providers. Errors are short type names: never raw text (may hold keys)."""
from __future__ import annotations

import asyncio
import time

import httpx

from simp_agent.session.profile import build_model

TIMEOUT_S, CACHE_S = 3.0, 30.0


async def _timed(name: str, fn) -> tuple[str, dict]:
    t = time.monotonic()
    try:
        await asyncio.wait_for(fn(), TIMEOUT_S)
        r = {"ok": True}
    except TimeoutError:
        r = {"ok": False, "error": "timeout"}
    except Exception as e:  # noqa: BLE001 - report every failure, but only its type
        r = {"ok": False, "error": type(e).__name__}
    return name, {**r, "ms": round((time.monotonic() - t) * 1000)}


def checks(settings: dict, store, files, sandbox, keys: dict, transport=None) -> dict:
    """name -> async fn that raises on failure. Skipped dependencies are left out."""
    out = {"database": lambda: store._all("SELECT 1")}
    if getattr(files, "kind", "") == "s3":
        out["workspace"] = lambda: asyncio.to_thread(files.s3.head_bucket, Bucket=files.bucket)
    if getattr(sandbox, "kind", "") == "e2b":
        out["e2b"] = sandbox.list_all
    pr = settings["profiles"].get(settings.get("default_profile") or "")
    if pr and pr.get("api") != "fake":
        m = build_model(pr)
        name = m.api_key_env or ("OPENAI_API_KEY" if m.api.startswith("openai") else "ANTHROPIC_API_KEY")
        key = keys.get(name, "")
        if m.base_url and "openrouter.ai" in m.base_url:  # /key needs a valid key and spends nothing
            url, hdr = m.base_url.rstrip("/") + "/key", {"Authorization": f"Bearer {key}"}
        elif m.base_url:
            url, hdr = m.base_url.rstrip("/") + "/models", {"Authorization": f"Bearer {key}"}
        elif m.api.startswith("anthropic"):
            url, hdr = "https://api.anthropic.com/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"}
        else:
            url = None
        if url:
            async def model():
                async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as c:
                    (await c.get(url, headers=hdr)).raise_for_status()
            out["model"] = model
    return out


class Ready:
    def __init__(self, checks: dict):
        self.checks, self.at, self.result, self.lock = checks, 0.0, None, asyncio.Lock()

    async def __call__(self) -> tuple[bool, dict]:
        async with self.lock:  # concurrent callers share one run
            if self.result is None or time.monotonic() - self.at > CACHE_S:
                self.result = dict(await asyncio.gather(*(_timed(n, f) for n, f in self.checks.items())))
                self.at = time.monotonic()
        return all(r["ok"] for r in self.result.values()), self.result
