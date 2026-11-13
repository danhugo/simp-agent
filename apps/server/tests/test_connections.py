from __future__ import annotations

import base64
import json
import time
import urllib.parse

import httpx
from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from simp_agent.ai import ToolCall
from simp_agent.testing import FakeProvider

from simp_server import protocol as p
from simp_server.connections import UserMcp
from simp_server.server import create_app, load_settings

from .test_server import reply, wait_for


def id_token(email):
    body = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"h.{body}.sig"


class Google:
    """Fake token + revoke endpoints (httpx MockTransport)."""

    def __init__(self):
        self.calls, self.refresh_ok = list(), True

    def __call__(self, req: httpx.Request) -> httpx.Response:
        form = dict(urllib.parse.parse_qsl(req.content.decode()))
        self.calls.append((req.url.path, form))
        if req.url.path.endswith("/revoke"):
            return httpx.Response(200)
        if form["grant_type"] == "authorization_code":
            return httpx.Response(200, json={"access_token": "AT-1", "refresh_token": "RT-1", "expires_in": 3600,
                                             "id_token": id_token("me@example.com")})
        if self.refresh_ok:
            return httpx.Response(200, json={"access_token": "AT-2", "expires_in": 3600})
        return httpx.Response(400, json={"error": "invalid_grant"})


async def make(tmp_path, stream_fn=None):
    (tmp_path / "settings.toml").write_text('[profiles.test]\napi = "fake"\nmodel = "m"\n')
    (tmp_path / ".env").write_text("GOOGLE_CLIENT_ID=cid\nGOOGLE_CLIENT_SECRET=csecret\n")
    app = create_app(load_settings(tmp_path), stream_fn or FakeProvider())
    mgr = app.state.mgr
    await mgr.store.open()
    g = Google()
    mgr.conns.http = httpx.AsyncClient(transport=httpx.MockTransport(g))
    users = list()
    for n in ("ua", "ub"):
        t = await mgr.store.add_user(n)
        users.append((t, await mgr.store.user_by_token(t)))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
    return app, mgr, g, users, client


async def connect(c, token):
    r = await c.post("/api/connections/google/start", headers={"Authorization": f"Bearer {token}"})
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.json()["url"]).query))
    return q, await c.get("/api/connections/google/callback", params={"code": "C", "state": q["state"]})


async def test_oauth_flow_list_delete(tmp_path):
    _, mgr, g, [(ta, ua), _], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    assert (await c.post("/api/connections/nope/start", headers=h)).status_code == 404
    bad = await c.get("/api/connections/google/callback", params={"code": "C", "state": "forged"})
    assert bad.status_code == 302 and "error=" in bad.headers["location"] and not g.calls
    q, r = await connect(c, ta)
    assert q["access_type"] == "offline" and q["code_challenge_method"] == "S256" and q["client_id"] == "cid"
    assert r.status_code == 302 and r.headers["location"].endswith("#connections?ok=google")
    form = g.calls[0][1]
    assert form["code_verifier"] and form["client_secret"] == "csecret"  # PKCE verifier sent
    again = await c.get("/api/connections/google/callback", params={"code": "C", "state": q["state"]})
    assert "error=" in again.headers["location"]  # a state works once
    row = (await mgr.store.connections(ua["id"]))[0]
    assert "AT-1" not in row["access_token_enc"] and "RT-1" not in row["refresh_token_enc"]  # encrypted at rest
    listed = (await c.get("/api/connections", headers=h)).json()
    assert listed == [{"app": "google", "label": "Google", "connected": True, "email": "me@example.com", "status": "ok"}]
    assert (await c.delete("/api/connections/google", headers=h)).json() == {"ok": True}
    assert g.calls[-1] == ("/revoke", {"token": "RT-1"})
    assert not await mgr.store.connections(ua["id"])
    await mgr.store.close()


async def test_servers_per_user_refresh_and_reconnect(tmp_path):
    _, mgr, g, [(ta, ua), (tb, ub)], c = await make(tmp_path)
    await connect(c, ta)
    servers, problems = await mgr.conns.servers(ua["id"])
    assert {s["name"] for s in servers} == {"gmail", "drive", "calendar"} and not problems
    assert servers[0]["headers"] == {"Authorization": "Bearer AT-1"} and "command" not in servers[0]
    assert await mgr.conns.servers(ub["id"]) == ([], [])  # the other user gets nothing
    await mgr.store.update_connection_token(ua["id"], "google", (await mgr.store.connections(ua["id"]))[0][
        "access_token_enc"], time.time() + 60)  # ends soon -> refresh
    servers, _ = await mgr.conns.servers(ua["id"])
    assert servers[0]["headers"]["Authorization"] == "Bearer AT-2"
    await mgr.store.update_connection_token(ua["id"], "google", "x", time.time())
    g.refresh_ok = False
    servers, problems = await mgr.conns.servers(ua["id"])
    assert servers == [] and "reconnect" in problems[0]
    assert (await mgr.store.connections(ua["id"]))[0]["status"] == "needs_reconnect"
    await mgr.store.close()


def fake_gmail():
    s = MCPServer("gmail")

    @s.tool(annotations=ToolAnnotations(read_only_hint=True))
    def search(q: str) -> str:
        return f"found {q}"

    @s.tool()
    def send(to: str) -> str:
        return f"sent to {to}"
    return s


async def test_write_tool_needs_approval_and_audit(tmp_path):
    fp = FakeProvider(reply("", [ToolCall("c1", "gmail__search", {"q": "x"})]),
                      reply("", [ToolCall("c2", "gmail__send", {"to": "bob"})]), reply("done"))
    _, mgr, _, [(_, ua), _], _ = await make(tmp_path, fp)
    row = await mgr.store.add_session(ua["id"], "test", "t")
    run = await mgr.get(ua, row["id"])
    plugin = next(x for x in run.session.plugins if isinstance(x, UserMcp))
    plugin.servers = [{"name": "gmail", "server": fake_gmail()}]
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: run.pending is not None)
    assert run.pending.tool == "gmail__send"  # search ran without asking
    await run.command(p.Approve(call_id="c2", decision="allow"))
    await wait_for(lambda: not run.busy and run.task.done())
    results = [e["content"] for e in run.log if e["type"] == "tool_result"]
    assert results[0].endswith("found x") and results[1].endswith("sent to bob")
    audit = await mgr.store._all("SELECT server, tool, decision, ok FROM mcp_audit ORDER BY at")
    assert audit == [{"server": "gmail", "tool": "search", "decision": "auto", "ok": 1},
                     {"server": "gmail", "tool": "send", "decision": "allow", "ok": 1}]
    await run.session.shutdown()
    await mgr.store.close()


async def test_apps_one_login_toggle_disconnect(tmp_path):
    _, mgr, _, [(ta, ua), _], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    assert (await c.post("/api/apps/gmail/enable", headers=h)).status_code == 409  # google not connected
    assert (await c.post("/api/apps/nope/disable", headers=h)).status_code == 404
    await connect(c, ta)
    apps = (await c.get("/api/apps", headers=h)).json()
    assert [a["app"] for a in apps][:3] == ["gmail", "drive", "calendar"]
    assert apps[1] == {"app": "drive", "label": "Google Drive", "description": apps[1]["description"], "icon": "drive",
                       "provider": "google", "connected": True, "enabled": True, "email": "me@example.com",
                       "status": "ok"}
    assert (await c.post("/api/apps/drive/disable", headers=h)).json() == {"ok": True}
    assert {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]} == {"gmail", "calendar"}  # next run: no drive__
    assert (await c.post("/api/apps/drive/enable", headers=h)).status_code == 200
    await c.post("/api/apps/drive/disable", headers=h)
    await c.delete("/api/connections/google", headers=h)
    google = lambda r: [a for a in r.json() if a["provider"] == "google"]
    assert not any(a["enabled"] or a["connected"] for a in google(await c.get("/api/apps", headers=h)))
    await connect(c, ta)  # a new login turns all three on again
    assert all(a["enabled"] for a in google(await c.get("/api/apps", headers=h)))
    await mgr.store.close()


async def test_no_login_apps_off_by_default_toggle(tmp_path):
    _, mgr, _, [(ta, ua), (tb, ub)], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    dw = next(a for a in (await c.get("/api/apps", headers=h)).json() if a["app"] == "deepwiki")
    assert dw == {"app": "deepwiki", "label": "DeepWiki", "description": dw["description"], "icon": "deepwiki",
                  "provider": None, "connected": True, "enabled": False, "email": None, "status": None}
    assert await mgr.conns.servers(ua["id"]) == ([], [])
    assert (await c.post("/api/apps/deepwiki/enable", headers=h)).json() == {"ok": True}  # no login needed
    assert (await mgr.conns.servers(ua["id"]))[0] == [{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}]
    assert await mgr.conns.servers(ub["id"]) == ([], [])  # per user
    await connect(c, ta)  # Google unchanged: its three apps on, deepwiki still on
    assert {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]} == {"deepwiki", "gmail", "drive", "calendar"}
    await c.post("/api/apps/deepwiki/disable", headers=h)
    assert "deepwiki" not in {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]}
    await mgr.store.close()
