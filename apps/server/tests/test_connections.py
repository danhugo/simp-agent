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
from simp_server.connections import NO_EXPIRY, UserMcp
from simp_server.server import create_app, load_settings

from .test_server import reply, wait_for


def id_token(email):
    body = base64.urlsafe_b64encode(json.dumps({"email": email, "email_verified": True}).encode()).decode().rstrip("=")
    return f"h.{body}.sig"


class Google:
    """Fake token + revoke endpoints (httpx MockTransport)."""

    def __init__(self):
        self.calls, self.refresh_ok = list(), True

    def __call__(self, req: httpx.Request) -> httpx.Response:
        form = dict(urllib.parse.parse_qsl(req.content.decode()))
        self.calls.append((req.url.path, form))
        if req.url.host == "api.github.com":
            ok = req.headers.get("authorization") == "Bearer ghp_good"
            return httpx.Response(200, json={"login": "octo"}) if ok else httpx.Response(401)
        if req.url.path.endswith("/revoke"):
            return httpx.Response(200)
        if form["grant_type"] == "authorization_code":
            if form["code"].startswith("C:"):  # "C:<email>": sign in as that account
                e = form["code"][2:]
                return httpx.Response(200, json={"access_token": f"AT-{e}", "refresh_token": f"RT-{e}",
                                                 "expires_in": 3600, "id_token": id_token(e)})
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


async def connect(c, token, app="gmail", code="C", body=None):
    r = await c.post(f"/api/apps/{app}/connect", headers={"Authorization": f"Bearer {token}"}, json=body)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.json()["url"]).query))
    return q, await c.get("/api/connections/google/callback", params={"code": code, "state": q["state"]})


async def test_oauth_flow_list_delete(tmp_path):
    _, mgr, g, [(ta, ua), _], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    assert (await c.post("/api/apps/nope/connect", headers=h)).status_code == 404
    assert (await c.post("/api/apps/deepwiki/connect", headers=h)).status_code == 404  # no login
    bad = await c.get("/api/connections/google/callback", params={"code": "C", "state": "forged"})
    assert bad.status_code == 302 and "error=" in bad.headers["location"] and not g.calls
    q, r = await connect(c, ta)
    assert q["access_type"] == "offline" and q["code_challenge_method"] == "S256" and q["client_id"] == "cid"
    assert r.status_code == 302 and r.headers["location"].endswith("#crafts?ok=google")
    form = g.calls[0][1]
    assert form["code_verifier"] and form["client_secret"] == "csecret"  # PKCE verifier sent
    again = await c.get("/api/connections/google/callback", params={"code": "C", "state": q["state"]})
    assert "error=" in again.headers["location"]  # a state works once
    row = (await mgr.store.connections(ua["id"]))[0]
    assert "AT-1" not in row["access_token_enc"] and "RT-1" not in row["refresh_token_enc"]  # encrypted at rest
    listed = (await c.get("/api/connections", headers=h)).json()
    lid = row["link_id"]
    assert lid.startswith("lnk_") and len(lid) == 12
    assert listed == [{"link_id": lid, "provider": "google", "label": "Google", "email": "me@example.com", "status": "ok",
                       "created": row["created"], "scopes": sorted(row["scopes"].split()), "default": True}]
    assert (await c.delete("/api/connections/lnk_nope", headers=h)).status_code == 404
    assert (await c.delete(f"/api/connections/{lid}", headers=h)).json() == {"ok": True}
    assert g.calls[-1] == ("/revoke", {"token": "RT-1"})
    assert not await mgr.store.connections(ua["id"])
    await mgr.store.close()


async def test_servers_per_user_refresh_and_reconnect(tmp_path):
    _, mgr, g, [(ta, ua), (tb, ub)], c = await make(tmp_path)
    for app in ("gmail", "drive", "calendar"):
        await connect(c, ta, app)
    servers, problems = await mgr.conns.servers(ua["id"])
    assert {s["name"] for s in servers} == {"gmail", "drive", "calendar"} and not problems
    assert servers[0]["headers"] == {"Authorization": "Bearer AT-1"} and "command" not in servers[0]
    assert await mgr.conns.servers(ub["id"]) == ([], [])  # the other user gets nothing
    await mgr.store.update_connection_token(ua["id"], (await mgr.store.connections(ua["id"]))[0]["link_id"], (await mgr.store.connections(ua["id"]))[0][
        "access_token_enc"], time.time() + 60)  # ends soon -> refresh
    servers, _ = await mgr.conns.servers(ua["id"])
    assert servers[0]["headers"]["Authorization"] == "Bearer AT-2"
    await mgr.store.update_connection_token(ua["id"], (await mgr.store.connections(ua["id"]))[0]["link_id"], "x", time.time())
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
    for app in ("gmail", "drive", "calendar"):
        await connect(c, ta, app)
    apps = (await c.get("/api/apps", headers=h)).json()
    assert [a["app"] for a in apps][:3] == ["gmail", "drive", "calendar"]
    assert apps[1] == {"app": "drive", "label": "Google Drive", "description": apps[1]["description"], "icon": "drive",
                       "provider": "google", "auth": "oauth", "connected": True, "enabled": True, "email": "me@example.com",
                       "status": "ok", "accounts": apps[1]["accounts"]}
    assert [x["email"] for x in apps[1]["accounts"]] == ["me@example.com"]
    assert (await c.post("/api/apps/drive/disable", headers=h)).json() == {"ok": True}
    assert {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]} == {"gmail", "calendar"}  # next run: no drive__
    assert (await c.post("/api/apps/drive/enable", headers=h)).status_code == 200
    await c.post("/api/apps/drive/disable", headers=h)
    await c.delete(f"/api/connections/{(await mgr.store.connections(ua['id']))[0]['link_id']}", headers=h)
    google = lambda r: [a for a in r.json() if a["provider"] == "google"]
    assert not any(a["enabled"] or a["connected"] for a in google(await c.get("/api/apps", headers=h)))
    await connect(c, ta, "drive")  # a new login turns on only that app
    assert [a["app"] for a in google(await c.get("/api/apps", headers=h)) if a["enabled"]] == ["drive"]
    await mgr.store.close()


async def test_no_login_apps_off_by_default_toggle(tmp_path):
    _, mgr, _, [(ta, ua), (tb, ub)], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    dw = next(a for a in (await c.get("/api/apps", headers=h)).json() if a["app"] == "deepwiki")
    assert dw == {"app": "deepwiki", "label": "DeepWiki", "description": dw["description"], "icon": "deepwiki",
                  "provider": None, "auth": None, "connected": True, "enabled": False, "email": None, "status": None}
    assert await mgr.conns.servers(ua["id"]) == ([], [])
    assert (await c.post("/api/apps/deepwiki/enable", headers=h)).json() == {"ok": True}  # no login needed
    assert (await mgr.conns.servers(ua["id"]))[0] == [{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"}]
    assert await mgr.conns.servers(ub["id"]) == ([], [])  # per user
    await connect(c, ta)  # Google unchanged: gmail on, deepwiki still on
    assert {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]} == {"deepwiki", "gmail"}
    await c.post("/api/apps/deepwiki/disable", headers=h)
    assert "deepwiki" not in {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]}
    await mgr.store.close()


async def test_github_token_save_list_run_delete(tmp_path):
    _, mgr, g, [(ta, ua), _], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    bad = await c.post("/api/connections/github/token", headers=h, json={"token": "nope"})
    assert bad.status_code == 400 and bad.json()["detail"] == "token rejected"
    assert (await c.post("/api/connections/google/token", headers=h, json={"token": "x"})).status_code == 404
    assert (await c.post("/api/connections/github/start", headers=h)).status_code == 404
    r = await c.post("/api/connections/github/token", headers=h, json={"token": "ghp_good"})
    assert r.json() == {"ok": True}
    row = (await mgr.store.connections(ua["id"]))[0]
    assert "ghp_good" not in row["access_token_enc"] and row["account_email"] == "octo"
    apps = (await c.get("/api/apps", headers=h))
    assert "ghp_good" not in apps.text
    gh = next(a for a in apps.json() if a["app"] == "github")
    assert gh["auth"] == "token" and gh["connected"] and gh["enabled"] and gh["email"] == "octo"
    assert gh["token_help_url"].startswith("https://github.com/")
    assert next(a for a in apps.json() if a["app"] == "gmail")["auth"] == "oauth"
    assert next(a for a in apps.json() if a["app"] == "deepwiki")["auth"] is None
    servers, problems = await mgr.conns.servers(ua["id"])
    assert servers == [{"name": "github", "url": "https://api.githubcopilot.com/mcp/",
                        "headers": {"Authorization": "Bearer ghp_good"}, "provider": "github", "link_id": row["link_id"],
                        "email": "octo", "default": True, "expires_at": NO_EXPIRY}] and not problems
    await c.post("/api/connections/github/token", headers=h, json={"token": "ghp_good"})  # same login: same link
    assert [r["link_id"] for r in await mgr.store.connections(ua["id"])] == [row["link_id"]]
    assert (await c.delete(f"/api/connections/{row['link_id']}", headers=h)).json() == {"ok": True}
    assert await mgr.store.connections(ua["id"]) == [] and not any(p[0] == "/revoke" for p in g.calls)
    await mgr.store.close()


async def test_token_401_at_run_marks_reconnect(tmp_path):
    _, mgr, _, [(ta, ua), _], c = await make(tmp_path)
    await c.post("/api/connections/github/token", headers={"Authorization": f"Bearer {ta}"}, json={"token": "ghp_good"})

    class Run:
        user_id = ua["id"]

    Run.mgr = mgr
    plug = UserMcp(Run(), servers=[])

    async def boom(self, spec):
        req = httpx.Request("GET", "https://x")
        raise BaseExceptionGroup("tg", [httpx.HTTPStatusError("401", request=req, response=httpx.Response(401, request=req))])
    import simp_agent.plugins.mcp as m
    orig, m.McpPlugin._connect = m.McpPlugin._connect, boom
    try:
        try:
            await plug._connect({"name": "github", "url": "u", "provider": "github",
                                  "link_id": (await mgr.store.connections(ua["id"]))[0]["link_id"]})
        except BaseExceptionGroup:
            pass
    finally:
        m.McpPlugin._connect = orig
    assert (await mgr.store.connections(ua["id"]))[0]["status"] == "needs_reconnect"
    servers, problems = await mgr.conns.servers(ua["id"])
    assert servers == [] and "GitHub" in problems[0]
    await mgr.store.close()


async def test_google_apps_authorize_one_at_a_time(tmp_path):
    _, mgr, g, [(ta, ua), _], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    G = "https://www.googleapis.com/auth/"
    q, _ = await connect(c, ta, "gmail")
    assert q["scope"].split() == ["openid", G + "userinfo.email", G + "gmail.modify", G + "gmail.send"]
    assert q["include_granted_scopes"] == "true" and q["prompt"] == "consent select_account" and q["access_type"] == "offline"
    async def apps():
        return {a["app"]: (a["connected"], a["enabled"]) for a in (await c.get("/api/apps", headers=h)).json()
                if a["provider"] == "google"}
    assert await apps() == {"gmail": (True, True), "drive": (False, False), "calendar": (False, False)}
    assert (await c.post("/api/apps/drive/enable", headers=h)).status_code == 409  # not authorized yet
    assert {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]} == {"gmail"}
    q, _ = await connect(c, ta, "drive")
    assert q["scope"].split() == ["openid", G + "userinfo.email", G + "drive"]
    assert await apps() == {"gmail": (True, True), "drive": (True, True), "calendar": (False, False)}
    await c.post("/api/apps/gmail/disable", headers=h)
    assert {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]} == {"drive"}  # authorized AND enabled
    assert (await c.post("/api/apps/drive/disconnect", headers=h)).json() == {"ok": True}  # gmail keeps the token
    assert await apps() == {"gmail": (True, False), "drive": (False, False), "calendar": (False, False)}
    assert not any(p.endswith("/revoke") for p, _ in g.calls)
    await c.post("/api/apps/gmail/disconnect", headers=h)  # the last app revokes and deletes the login
    assert g.calls[-1] == ("/revoke", {"token": "RT-1"}) and not await mgr.store.connections(ua["id"])
    await mgr.store.close()


async def test_portal_change_reloads_open_run_and_evict_closes_mcp(tmp_path):
    _, mgr, _, [(ta, ua), _], c = await make(tmp_path, FakeProvider(reply("a"), reply("b")))
    row = await mgr.store.add_session(ua["id"], "test", "t")
    run = await mgr.get(ua, row["id"])
    run.mcp.servers = [{"name": "gmail", "server": fake_gmail()}]
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert "gmail__send" in run.mcp.names and run.mcp.tasks
    await c.post("/api/apps/deepwiki/disable", headers={"Authorization": f"Bearer {ta}"})  # any portal change
    assert run.mcp.stale
    blocked = await run.mcp.tool_call(ToolCall("x", "gmail__send", {}))
    assert "portals changed" in blocked["block"]  # a turn already running can't use the old portals
    await run.command(p.Prompt(text="again"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert not run.mcp.stale and not run.mcp.names and "gmail__send" not in run.session.needs_approval
    assert not any(t.name.startswith("gmail__") for t in run.session.agent.tools)  # user has no gmail: gone
    run.mcp.servers = [{"name": "gmail", "server": fake_gmail()}]
    await run.mcp.setup(run.mcp.api, dict())
    held = list(run.mcp.tasks)
    await mgr.evict(row["id"])
    assert all(t.done() for t in held) and not run.mcp.tasks  # connection closed, not leaked
    await mgr.store.close()


async def test_mcp_servers_connect_in_parallel():
    import asyncio

    from simp_agent.plugins.mcp import McpPlugin

    class Api:
        async def emit(self, *a):
            pass

    plug = McpPlugin(servers=[{"name": "a"}, {"name": "b"}, {"name": "c"}])

    async def slow(spec):
        await asyncio.sleep(0.2)
        raise RuntimeError("down")
    plug._connect = slow
    t = time.monotonic()
    await plug.setup(Api(), dict())
    assert time.monotonic() - t < 0.4 and plug.connect_timeout == 10 and plug.timeout == 60


async def test_oauth_callback_needs_same_browser(tmp_path):
    _, mgr, g, [(ta, ua), _], c = await make(tmp_path)
    r = await c.post("/api/apps/gmail/connect", headers={"Authorization": f"Bearer {ta}"})
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.json()["url"]).query))["state"]
    victim = httpx.AsyncClient(transport=c._transport, base_url="http://localhost")  # no cookie
    bad = await victim.get("/api/connections/google/callback", params={"code": "C", "state": state})
    assert "error=" in bad.headers["location"] and not g.calls and not await mgr.store.connections(ua["id"])
    await mgr.store.close()


async def test_refresh_network_error_keeps_login(tmp_path):
    _, mgr, g, [(ta, ua), _], c = await make(tmp_path)
    await connect(c, ta)
    await mgr.store.update_connection_token(ua["id"], (await mgr.store.connections(ua["id"]))[0]["link_id"], "x", time.time())
    mgr.conns.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    servers, problems = await mgr.conns.servers(ua["id"])
    assert servers == [] and "try again" in problems[0]
    assert (await mgr.store.connections(ua["id"]))[0]["status"] == "ok"  # 5xx: not the user's fault
    await mgr.store.close()


async def test_forgotten_app_stays_off_and_bad_key_row_is_isolated(tmp_path):
    _, mgr, _, [(ta, ua), _], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    await connect(c, ta, "gmail")
    await c.post("/api/apps/gmail/disconnect", headers=h)
    await connect(c, ta, "drive")  # Google reports gmail scopes granted again
    await mgr.store.set_connection_scopes(ua["id"], (await mgr.store.connections(ua["id"]))[0]["link_id"], " ".join(
        sum((a.get("scopes", []) for a in mgr.conns.app_list.values() if a.get("provider") == "google"), [])))
    assert "gmail" not in {s["name"] for s in (await mgr.conns.servers(ua["id"]))[0]}  # does not come back
    await c.post("/api/apps/deepwiki/enable", headers=h)
    await mgr.store.update_connection_token(ua["id"], (await mgr.store.connections(ua["id"]))[0]["link_id"], "not-fernet", time.time() + 3600)
    servers, problems = await mgr.conns.servers(ua["id"])
    assert [s["name"] for s in servers] == ["deepwiki"] and problems  # no-auth portal still works
    assert (await mgr.store.connections(ua["id"]))[0]["status"] == "needs_reconnect"
    await mgr.store.close()


async def test_mcp_tools_register_sorted():
    import asyncio

    from simp_agent.agent import AgentTool
    from simp_agent.plugins.mcp import McpPlugin

    names = list()

    class Api:
        def register_tool(self, t):
            names.append(t.name)

    plug = McpPlugin(servers=[{"name": "b", "delay": 0}, {"name": "a", "delay": 0.05}])

    async def connect(spec):
        await asyncio.sleep(spec["delay"])
        return spec

    async def tools(spec, _):
        return [AgentTool(f"{spec['name']}__{n}", "", {}, None) for n in ("z", "y")]
    plug._connect, plug._tools = connect, tools
    await plug.setup(Api(), dict())
    assert names == ["a__y", "a__z", "b__y", "b__z"]  # not the order servers answered in


def fake_gmail_of(who):
    s = MCPServer("gmail")

    @s.tool(annotations=ToolAnnotations(read_only_hint=True))
    def search(q: str) -> str:
        return f"{who} found {q}"

    @s.tool()
    def send(to: str) -> str:
        return f"{who} sent to {to}"
    return s


async def test_many_accounts_connect_route_disconnect(tmp_path):
    _, mgr, g, [(ta, ua), _], c = await make(tmp_path)
    h = {"Authorization": f"Bearer {ta}"}
    q, _ = await connect(c, ta, code="C:a@x.com")
    assert "select_account" in q["prompt"] and "login_hint" not in q  # "+ add account" always shows the chooser
    await connect(c, ta, code="C:b@x.com")
    await connect(c, ta, code="C:a@x.com")  # same account again: updates it, no third link
    links = (await c.get("/api/connections", headers=h)).json()
    assert [(x["email"], x["default"]) for x in links] == [("a@x.com", True), ("b@x.com", False)]
    a, b = links[0]["link_id"], links[1]["link_id"]
    servers, _ = await mgr.conns.servers(ua["id"])
    assert [(s["link_id"], s["headers"]["Authorization"], s["default"]) for s in servers] == [
        (a, "Bearer AT-a@x.com", True), (b, "Bearer AT-b@x.com", False)]
    gm = next(x for x in (await c.get("/api/apps", headers=h)).json() if x["app"] == "gmail")
    assert gm["email"] == "a@x.com" and [x["link_id"] for x in gm["accounts"]] == [a, b]

    # adding scopes to account A: Google is told A; signing in as B instead is rejected and saves nothing
    before = await mgr.store.connections(ua["id"])
    q, r = await connect(c, ta, "drive", code="C:b@x.com", body={"link_id": a})
    assert q["login_hint"] == "a@x.com" and "different account" in urllib.parse.unquote_plus(r.headers["location"])
    assert await mgr.store.connections(ua["id"]) == before
    _, r = await connect(c, ta, "drive", code="C:a@x.com", body={"link_id": a})
    assert r.headers["location"].endswith("ok=google")

    # disconnect A: B is left and is the default
    assert (await c.delete(f"/api/connections/{a}", headers=h)).json() == {"ok": True}
    assert g.calls[-1] == ("/revoke", {"token": "RT-a@x.com"})
    links = (await c.get("/api/connections", headers=h)).json()
    assert [(x["link_id"], x["default"]) for x in links] == [(b, True)]
    servers, _ = await mgr.conns.servers(ua["id"])
    assert [(s["link_id"], s["default"]) for s in servers] == [(b, True)]
    await mgr.store.close()


async def test_agent_picks_account_by_link_id(tmp_path):
    fp = FakeProvider(reply("", [ToolCall("c1", "gmail__search", {"q": "x", "link_id": "lnk_b"})]),
                      reply("", [ToolCall("c2", "gmail__search", {"q": "y"})]),
                      reply("", [ToolCall("c3", "gmail__send", {"to": "bob", "link_id": "lnk_b"})]), reply("done"))
    _, mgr, _, [(ta, ua), _], c = await make(tmp_path, fp)
    row = await mgr.store.add_session(ua["id"], "test", "t")
    run = await mgr.get(ua, row["id"])
    run.mcp.servers = [
        {"name": "gmail", "server": fake_gmail_of("A"), "link_id": "lnk_a", "email": "a@x.com", "default": True},
        {"name": "gmail", "server": fake_gmail_of("B"), "link_id": "lnk_b", "email": "b@x.com", "default": False}]
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: run.pending is not None)
    assert run.pending.args == {"to": "bob", "link_id": "b@x.com"}  # the approval card shows the email
    await run.command(p.Approve(call_id="c3", decision="allow"))
    await wait_for(lambda: not run.busy and run.task.done())
    tool = next(t for t in run.session.agent.tools if t.name == "gmail__search")
    prop = tool.parameters["properties"]["link_id"]
    assert prop["enum"] == ["lnk_a", "lnk_b"] and "lnk_a = a@x.com (default), lnk_b = b@x.com" in prop["description"]
    assert [n for n in (t.name for t in run.session.agent.tools) if n.startswith("gmail__")] == ["gmail__search", "gmail__send"]
    results = [e["content"] for e in run.log if e["type"] == "tool_result"]
    assert results[0].endswith("B found x") and results[1].endswith("A found y") and results[2].endswith("B sent to bob")
    audit = await mgr.store._all("SELECT tool, link_id FROM mcp_audit ORDER BY at")
    assert [(x["tool"], x["link_id"]) for x in audit] == [("search", "lnk_b"), ("search", "lnk_a"), ("send", "lnk_b")]
    d = (await c.get("/api/apps/gmail", headers={"Authorization": f"Bearer {ta}"})).json()  # portal detail page
    assert d["tools"] == [{"name": "search", "needs_approval": False}, {"name": "send", "needs_approval": True}]
    assert [x["tool"] for x in d["calls"]] == ["send", "search", "search"] and d["url"] == "http://127.0.0.1:8101/mcp"  # our workspace-mcp
    await run.session.shutdown()
    await mgr.store.close()


async def test_one_account_schema_unchanged(tmp_path):
    fp = FakeProvider(reply("done"))
    _, mgr, _, [(_, ua), _], _ = await make(tmp_path, fp)
    row = await mgr.store.add_session(ua["id"], "test", "t")
    run = await mgr.get(ua, row["id"])
    run.mcp.servers = [{"name": "gmail", "server": fake_gmail_of("A"), "link_id": "lnk_a", "email": "a@x.com",
                        "default": True}]
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: not run.busy and run.task.done())
    tool = next(t for t in run.session.agent.tools if t.name == "gmail__search")
    assert "link_id" not in tool.parameters.get("properties", dict())
    await run.session.shutdown()
    await mgr.store.close()


async def test_old_connections_table_migrates(tmp_path):
    import sqlite3

    from simp_server.store import SqliteStore
    db = sqlite3.connect(tmp_path / "simp.db")
    db.execute("CREATE TABLE connections(user_id TEXT NOT NULL, app TEXT NOT NULL, account_email TEXT, "
               "access_token_enc TEXT, refresh_token_enc TEXT, expires_at REAL, status TEXT, created REAL, updated REAL, "
               "PRIMARY KEY(user_id, app))")
    db.execute("CREATE TABLE mcp_audit(user_id TEXT, session_id TEXT, server TEXT, tool TEXT, decision TEXT, ok INTEGER, at REAL)")
    db.execute("INSERT INTO connections VALUES('u','google','me@x.com','A','R',1,'ok',5,5)")
    db.commit()
    db.close()
    st = SqliteStore({"data_dir": str(tmp_path)})
    await st.open()
    [r] = await st.connections("u")
    assert r["link_id"].startswith("lnk_") and r["account_email"] == "me@x.com" and r["created"] == 5
    await st.add_audit("u", "s", "gmail", "search", "auto", True, r["link_id"])
    assert (await st.audit("u", "gmail"))[0]["link_id"] == r["link_id"]
    await st.close()


async def test_token_near_expiry_reloads_before_next_turn(tmp_path):
    _, mgr, _, [(_, ua), _], _ = await make(tmp_path, FakeProvider(reply("a"), reply("b")))
    row = await mgr.store.add_session(ua["id"], "test", "t")
    run = await mgr.get(ua, row["id"])
    calls = list()

    async def servers(user_id):  # each reload gets a freshly refreshed token
        calls.append(user_id)
        return [{"name": "gmail", "server": fake_gmail_of(f"T{len(calls)}"), "link_id": "lnk_a",
                 "default": True, "expires_at": time.time() + 3600 if len(calls) > 1 else time.time() + 10}], []
    mgr.conns.servers = servers
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert len(calls) == 1 and run.mcp.expired()  # token ends within REFRESH_EARLY
    await run.command(p.Prompt(text="again"))
    await wait_for(lambda: not run.busy and run.task.done())
    assert len(calls) == 2 and not run.mcp.expired()
    await run.session.shutdown()
    await mgr.store.close()


async def test_default_link_fails_other_links_work_and_audit_real_link(tmp_path):
    fp = FakeProvider(reply("", [ToolCall("c1", "gmail__search", {"q": "x"})]),
                      reply("", [ToolCall("c2", "gmail__search", {"q": "y", "link_id": "lnk_zz"})]), reply("done"))
    _, mgr, _, [(_, ua), _], _ = await make(tmp_path, fp)
    row = await mgr.store.add_session(ua["id"], "test", "t")
    run = await mgr.get(ua, row["id"])
    run.mcp.servers = [
        {"name": "gmail", "command": ["/nonexistent-mcp"], "link_id": "lnk_a", "default": True},  # can't connect
        {"name": "gmail", "server": fake_gmail_of("B"), "link_id": "lnk_b", "default": False},
        {"name": "gmail", "server": fake_gmail_of("C"), "link_id": "lnk_c", "default": False}]
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: not run.busy and run.task.done())
    results = [e["content"] for e in run.log if e["type"] == "tool_result"]
    assert results[0].endswith("B found x") and "lnk_zz" in results[1]
    audit = await mgr.store._all("SELECT link_id FROM mcp_audit ORDER BY at")
    assert [x["link_id"] for x in audit] == ["lnk_b", None]  # the link that ran; none for a bad link_id
    await run.session.shutdown()
    await mgr.store.close()


async def test_mislabeled_write_tool_is_still_asked(tmp_path):
    """A server that marks a send tool read-only does not get it run silently: write-like names are asked."""
    s = MCPServer("gmail")

    @s.tool(annotations=ToolAnnotations(read_only_hint=True))
    def send_mail(to: str) -> str:
        return f"sent to {to}"
    fp = FakeProvider(reply("", [ToolCall("c1", "gmail__send_mail", {"to": "bob"})]), reply("done"))
    _, mgr, _, [(_, ua), _], _ = await make(tmp_path, fp)
    run = await mgr.get(ua, (await mgr.store.add_session(ua["id"], "test", "t"))["id"])
    next(x for x in run.session.plugins if isinstance(x, UserMcp)).servers = [{"name": "gmail", "server": s}]
    await run.command(p.Prompt(text="hi"))
    await wait_for(lambda: run.pending is not None)
    assert run.pending.tool == "gmail__send_mail"
    await run.command(p.Approve(call_id="c1", decision="deny"))
    await wait_for(lambda: not run.busy and run.task.done())
    await run.session.shutdown()
    await mgr.store.close()
