import httpx

from simp_server import health
from simp_server.server import create_app, load_settings


async def test_healthz_and_readyz(tmp_path):
    (tmp_path / "settings.toml").write_text('[profiles.test]\napi = "fake"\nmodel = "m"\n')
    app = create_app(load_settings(tmp_path))
    await app.state.mgr.store.open()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as c:
            assert (await c.get("/api/healthz")).json() == {"ok": True}
            r = await c.get("/api/readyz")
            assert r.status_code == 200 and r.json()["database"]["ok"] and set(r.json()) == {"database"}
    finally:
        await app.state.mgr.store.close()


class Files:
    kind, bucket = "s3", "b"

    class s3:
        @staticmethod
        def head_bucket(Bucket):
            raise RuntimeError("secret-key-xyz in message")


class Sandbox:
    kind, calls = "e2b", 0

    async def list_all(self):
        Sandbox.calls += 1
        return []


class Store:
    async def _all(self, sql):
        return []


async def test_readyz_checks_fail_cached_no_secrets():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(401)
    settings = {"default_profile": "or", "profiles": {"or": {"api": "openai-completions", "model": "x",
                "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"}}}
    ready = health.Ready(health.checks(settings, Store(), Files(), Sandbox(), {"OPENROUTER_API_KEY": "k"},
                                       httpx.MockTransport(handler)))
    ok, r = await ready()
    assert not ok and r["database"]["ok"] and r["e2b"]["ok"]
    assert r["workspace"] == {"ok": False, "error": "RuntimeError", "ms": r["workspace"]["ms"]}
    assert r["model"]["error"] == "HTTPStatusError" and seen == ["https://openrouter.ai/api/v1/key"]
    await ready()
    assert Sandbox.calls == 1 and len(seen) == 1  # cached
