"""/api/image: serves only picture links this server signed, fetched on demand (nothing kept)."""
from simp_server import web_tools
from simp_server.server import image_link

from .test_accounts import accounts_app, client


async def test_image_proxy_only_signed_links(tmp_path, monkeypatch):
    app, mgr = await accounts_app(tmp_path)
    bodies = {"https://p/a.jpg": ("image/jpeg", b"JPEG"), "https://p/x.svg": ("image/svg+xml", b"<svg/>"),
              "https://p/big.jpg": ("image/jpeg", b"x" * 9_000_000)}
    monkeypatch.setattr(web_tools, "http_get", lambda u, max_bytes: (u, *bodies[u]))
    async with client(app) as c:
        ok = await c.get(image_link(mgr.image_key, "https://p/a.jpg"))
        assert ok.status_code == 200 and ok.content == b"JPEG" and ok.headers["content-type"] == "image/jpeg"
        assert (await c.get("/api/image", params={"u": "https://p/a.jpg", "s": "0" * 32})).status_code == 404
        assert (await c.get("/api/image", params={"u": "https://evil/?d=secret"})).status_code == 404
        assert (await c.get(image_link(mgr.image_key, "https://p/x.svg"))).status_code == 415
        assert (await c.get(image_link(mgr.image_key, "https://p/big.jpg"))).status_code == 413  # never half a picture
    await mgr.store.close()  # an open aiosqlite thread keeps the test process from exiting
