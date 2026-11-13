"""Connections: a user links an app (Google) with OAuth; its remote MCP servers join every run of that user.

A provider (Google) is one OAuth login; apps (Gmail, Drive, Calendar) are its MCP servers, each on/off per user.
Only providers/apps in settings (PROVIDERS/APPS + [providers.<name>] / [apps.<name>] overrides) exist, and only over HTTP: an MCP stdio server
would run on the host, outside the sandbox. Tokens are encrypted at rest (Fernet, SIMP_SECRET_KEY in <data_dir>/.env)
and only ever sent to the app's own token/MCP URLs: never logged, never in prompts, events or the sandbox."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from simp_agent.plugins.mcp import McpPlugin

from . import protocol as p

log = logging.getLogger("simp_server")

PROVIDERS = {"google": {
    "kind": "oauth", "label": "Google",
    "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "revoke_url": "https://oauth2.googleapis.com/revoke",
    "scopes": ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/gmail.modify",
               "https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/calendar.events",
               "https://www.googleapis.com/auth/drive"],
    "client_id_env": "GOOGLE_CLIENT_ID", "client_secret_env": "GOOGLE_CLIENT_SECRET",
}, "github": {  # kind "token": the user pastes a personal token; no OAuth app to register
    "kind": "token", "label": "GitHub",
    "token_help": "Make a fine-grained personal access token with the repo access you want the agent to have.",
    "token_help_url": "https://github.com/settings/personal-access-tokens",
    "header": "Authorization: Bearer {token}",
    "validate_url": "https://api.github.com/user",  # optional: GET once on save; 401/403 = rejected; json login/email kept
}}
NO_EXPIRY = 1e18  # expires_at for pasted tokens: never refreshed
APPS = {  # the app name is also the MCP server name, so its tools are "<app>__<tool>"
    "gmail": {"label": "Gmail", "description": "Search, read, label and draft email.", "icon": "gmail",
              "provider": "google", "url": "https://gmailmcp.googleapis.com/mcp/v1"},
    "drive": {"label": "Google Drive", "description": "Find, read and create files in Drive.", "icon": "drive",
              "provider": "google", "url": "https://drivemcp.googleapis.com/mcp/v1"},
    "calendar": {"label": "Google Calendar", "description": "See and manage calendar events.", "icon": "calendar",
                 "provider": "google", "url": "https://calendarmcp.googleapis.com/mcp/v1"},
    # no login (provider None): off until the user turns them on, so new users don't get many extra tools
    "github": {"label": "GitHub", "description": "Issues, pull requests, code and CI", "icon": "github",
               "provider": "github", "url": "https://api.githubcopilot.com/mcp/"},
    "deepwiki": {"label": "DeepWiki", "description": "Ask about any public GitHub repo.", "icon": "deepwiki",
                 "provider": None, "url": "https://mcp.deepwiki.com/mcp"},
    "context7": {"label": "Context7", "description": "Up-to-date library docs and code examples.", "icon": "context7",
                 "provider": None, "url": "https://mcp.context7.com/mcp"},
    "mslearn": {"label": "Microsoft Learn", "description": "Search Microsoft Learn docs and code samples.",
                "icon": "mslearn", "provider": None, "url": "https://learn.microsoft.com/api/mcp"},
    "cfdocs": {"label": "Cloudflare Docs", "description": "Search Cloudflare documentation.", "icon": "cloudflare",
               "provider": None, "url": "https://docs.mcp.cloudflare.com/mcp"},
    "awsknowledge": {"label": "AWS Knowledge", "description": "Search AWS documentation.", "icon": "aws",
                     "provider": None, "url": "https://knowledge-mcp.global.api.aws"},
}
STATE_TTL = 600  # s: an OAuth start must finish within 10 minutes
REFRESH_EARLY = 300  # s: refresh tokens that expire within 5 minutes


def _merged(defaults: dict, overrides: dict) -> dict:
    return {n: {**defaults.get(n, dict()), **a} for n, a in {**defaults, **overrides}.items()}


def providers(settings: dict) -> dict:
    return _merged(PROVIDERS, settings.get("providers", dict()))


def secret_key(keys: dict, data_dir: str) -> bytes:
    """SIMP_SECRET_KEY from .env; made and saved there (mode 600) on first use."""
    if k := keys.get("SIMP_SECRET_KEY"):
        return k.encode()
    k = keys["SIMP_SECRET_KEY"] = Fernet.generate_key().decode()
    f = Path(data_dir) / ".env"
    f.parent.mkdir(parents=True, exist_ok=True)
    old = f.read_text() if f.exists() else ""
    f.write_text(old + ("" if not old or old.endswith("\n") else "\n") + f"SIMP_SECRET_KEY={k}\n")
    os.chmod(f, 0o600)
    log.warning("made a new SIMP_SECRET_KEY in %s: keep it, losing it means every user must reconnect", f)
    return k.encode()


def _email(id_token: str | None) -> str | None:
    # from the token endpoint over TLS (OIDC 3.1.3.7): the payload can be read without checking the signature
    try:
        part = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["email"]
    except Exception:
        return None


class Connections:
    def __init__(self, settings: dict, store, keys: dict):
        self.settings, self.store, self.keys = settings, store, keys
        self.apps = providers(settings)  # OAuth providers; the user-facing apps are self.app_list
        self.app_list = _merged(APPS, settings.get("apps", dict()))
        self.fernet = Fernet(secret_key(keys, settings["data_dir"]))
        self.pending: dict[str, tuple] = dict()  # ponytail: in memory, a restart drops OAuth starts in flight
        self.http = httpx.AsyncClient(timeout=20)

    def app(self, name: str) -> dict:
        if name not in self.apps:
            raise LookupError(f"unknown app {name!r}")
        return self.apps[name]

    def _header(self, prov: str, token: str) -> dict:
        k, _, v = self.apps[prov].get("header", "Authorization: Bearer {token}").partition(":")
        return {k.strip(): v.strip().replace("{token}", token)}

    async def save_token(self, user_id: str, name: str, token: str) -> None:
        """LookupError: not a token provider; ValueError: token rejected."""
        a = self.app(name)
        token = token.strip()
        if a.get("kind") != "token":
            raise LookupError(f"{name!r} does not take a pasted token")
        if not token:
            raise ValueError("token is empty")
        who = None
        if url := a.get("validate_url"):
            r = await self.http.get(url, headers=self._header(name, token))
            if r.status_code in (401, 403):
                raise ValueError("token rejected")
            if r.status_code == 200:
                try:
                    j = r.json()
                    who = j.get("login") or j.get("email") or j.get("name")
                except Exception:
                    pass
        await self.store.save_connection(user_id, name, who, self.fernet.encrypt(token.encode()).decode(), "",
                                         NO_EXPIRY)

    def _client(self, a: dict) -> tuple[str, str]:
        cid, sec = self.keys.get(a["client_id_env"]), self.keys.get(a["client_secret_env"])
        if not cid or not sec:
            raise RuntimeError(f"{a['client_id_env']} / {a['client_secret_env']} not set in .env")
        return cid, sec

    def redirect_uri(self, name: str) -> str:
        return f"{self.settings.get('public_url', 'http://localhost:8766').rstrip('/')}/api/connections/{name}/callback"

    def start(self, user_id: str, name: str) -> str:
        a = self.app(name)
        if a.get("kind") == "token":
            raise LookupError(f"{name!r} takes a pasted token, not OAuth")
        cid, _ = self._client(a)
        now = time.time()
        self.pending = {s: v for s, v in self.pending.items() if v[3] > now}
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        self.pending[state] = (user_id, name, verifier, now + STATE_TTL)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        q = {"client_id": cid, "redirect_uri": self.redirect_uri(name), "response_type": "code",
             "scope": " ".join(a["scopes"]), "state": state, "code_challenge": challenge,
             "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent",
             "include_granted_scopes": "true"}
        return f"{a['auth_url']}?{urllib.parse.urlencode(q)}"

    async def callback(self, name: str, code: str, state: str) -> None:
        """Raises ValueError with a short, token-free reason."""
        v = self.pending.pop(state, None)
        if v is None or v[1] != name or v[3] < time.time():
            raise ValueError("bad or expired state")
        user_id, _, verifier, _ = v
        a = self.app(name)
        cid, sec = self._client(a)
        r = await self.http.post(a["token_url"], data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri(name),
            "client_id": cid, "client_secret": sec, "code_verifier": verifier})
        if r.status_code != 200:
            raise ValueError(f"token exchange failed ({r.status_code})")
        t = r.json()
        if not t.get("refresh_token"):
            raise ValueError("no refresh token returned")
        await self.store.save_connection(user_id, name, _email(t.get("id_token")), self.fernet.encrypt(
            t["access_token"].encode()).decode(), self.fernet.encrypt(t["refresh_token"].encode()).decode(),
            time.time() + float(t.get("expires_in", 3600)))

    async def list(self, user_id: str) -> list[dict]:
        rows = {r["app"]: r for r in await self.store.connections(user_id)}
        return [{"app": n, "label": a.get("label", n), "connected": n in rows,
                 "email": rows[n]["account_email"] if n in rows else None,
                 "status": rows[n]["status"] if n in rows else None} for n, a in self.apps.items()]

    async def delete(self, user_id: str, name: str) -> None:
        row = next((r for r in await self.store.connections(user_id) if r["app"] == name), None)
        if row and row["refresh_token_enc"] and (url := self.apps.get(name, dict()).get("revoke_url")):
            try:  # best effort: the row goes either way
                await self.http.post(url, data={"token": self.fernet.decrypt(row["refresh_token_enc"]).decode()})
            except Exception as e:
                log.warning("revoke %s failed: %s", name, type(e).__name__)
        await self.store.delete_connection(user_id, name)
        await self.store.clear_app_flags(user_id, [n for n, a in self.app_list.items() if a.get("provider") == name])

    async def list_apps(self, user_id: str) -> list[dict]:
        """Every app; enabled = provider connected and not turned off (default on: a login enables all its apps)."""
        rows = {r["app"]: r for r in await self.store.connections(user_id)}
        off, on = await self.store.disabled_apps(user_id), await self.store.enabled_apps(user_id)
        out = list()
        for n, a in self.app_list.items():
            if a.get("provider") is None:
                out.append({"app": n, "label": a.get("label", n), "description": a.get("description", ""),
                            "icon": a.get("icon", n), "provider": None, "auth": None, "connected": True, "enabled": n in on,
                            "email": None, "status": None})
                continue
            row, prov = rows.get(a["provider"]), self.apps.get(a["provider"], dict())
            out.append({"app": n, "label": a.get("label", n), "description": a.get("description", ""),
                        "icon": a.get("icon", n), "provider": a["provider"], "auth": prov.get("kind", "oauth"),
                        **({"token_help": prov.get("token_help", ""), "token_help_url": prov.get("token_help_url")}
                           if prov.get("kind") == "token" else dict()), "connected": row is not None,
                        "enabled": row is not None and n not in off, "email": row and row["account_email"],
                        "status": row and row["status"]})
        return out

    async def set_enabled(self, user_id: str, name: str, on: bool) -> None:
        """LookupError: unknown app; PermissionError: enabling an app whose provider is not connected."""
        if name not in self.app_list:
            raise LookupError(f"unknown app {name!r}")
        prov = self.app_list[name].get("provider")
        if prov is None:
            return await self.store.set_app_on(user_id, name, on)
        if on and not any(r["app"] == prov for r in await self.store.connections(user_id)):
            raise PermissionError(f"connect {prov} first")
        await self.store.set_app_disabled(user_id, name, not on)

    async def _access(self, user_id: str, row: dict) -> str | None:
        """A valid access token, refreshed when it ends within REFRESH_EARLY; None (and needs_reconnect) on failure."""
        if row["expires_at"] - time.time() > REFRESH_EARLY:
            return self.fernet.decrypt(row["access_token_enc"]).decode()
        a = self.apps[row["app"]]
        try:
            cid, sec = self._client(a)
            r = await self.http.post(a["token_url"], data={
                "grant_type": "refresh_token", "refresh_token": self.fernet.decrypt(row["refresh_token_enc"]).decode(),
                "client_id": cid, "client_secret": sec})
            t = r.json() if r.status_code == 200 else None
        except Exception as e:
            log.warning("refresh %s failed: %s", row["app"], type(e).__name__)
            t = None
        if not t or not t.get("access_token"):
            await self.store.set_connection_status(user_id, row["app"], "needs_reconnect")
            return None
        await self.store.update_connection_token(user_id, row["app"], self.fernet.encrypt(
            t["access_token"].encode()).decode(), time.time() + float(t.get("expires_in", 3600)))
        return t["access_token"]

    async def servers(self, user_id: str) -> tuple[list[dict], list[str]]:
        """McpPlugin server specs for the user's enabled apps, and notices for providers that need a reconnect."""
        out, problems = list(), list()
        off, on = await self.store.disabled_apps(user_id), await self.store.enabled_apps(user_id)
        out += [{"name": n, "url": a["url"]} for n, a in self.app_list.items() if a.get("provider") is None and n in on]
        for row in await self.store.connections(user_id):
            mine = {n: a for n, a in self.app_list.items() if a.get("provider") == row["app"] and n not in off}
            if not mine:
                continue
            a = self.apps.get(row["app"])
            if a is None:  # app removed from settings
                continue
            token = await self._access(user_id, row) if row["status"] == "ok" else None
            if token is None:
                problems.append(f"{a.get('label', row['app'])} connection needs reconnect (Settings > Connections)")
                continue
            out += [{"name": n, "url": app["url"], "headers": self._header(row["app"], token), "provider": row["app"]}
                    for n, app in mine.items()]
        return out, problems


class UserMcp(McpPlugin):
    """The run's MCP plugin: the user's connected apps. Tools not marked read-only need approval; every call is audited.
    ponytail: the access token is fixed when the first prompt connects (about 1 h); a very long-lived run then
    gets auth errors until it is evicted and reloaded. Reconnect on 401 if that matters."""

    def __init__(self, run, servers: list[dict] | None = None):
        super().__init__(servers=servers)
        self.run, self.names = run, set()

    async def setup(self, api, config: dict) -> None:
        if self.servers is None:  # tests pass servers directly
            self.servers, problems = await self.run.mgr.conns.servers(self.run.user_id)
            for text in problems:
                await self.run.durable(p.Notice, level="warning", text=text)
        if not self.servers:
            return
        await super().setup(api, config)
        session = self.run.session
        for t in session.agent.tools:
            if hasattr(t, "read_only_hint"):  # set by McpPlugin on every MCP tool
                self.names.add(t.name)
                if t.read_only_hint is not True:
                    session.needs_approval.add(t.name)

    async def _connect(self, spec: dict):
        try:
            return await super()._connect(spec)
        except Exception as e:  # revoked/expired token: ask the user to reconnect instead of failing every run
            if spec.get("provider") and "401" in f"{e!r} {getattr(e, 'exceptions', '')}":
                await self.run.mgr.store.set_connection_status(self.run.user_id, spec["provider"], "needs_reconnect")
            raise

    async def tool_result(self, call, result):
        if call.name in self.names:
            server, _, tool = call.name.partition("__")
            ok = not result.is_error and not result.content.startswith(f"{call.name} error:")
            await self.run.mgr.store.add_audit(self.run.user_id, self.run.sid, server, tool,
                                               self.run.decisions.pop(call.id, "auto"), ok)
        return None
