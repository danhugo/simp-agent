"""Connections: a user links an app (Google) with OAuth; its remote MCP servers join every run of that user.

A provider (Google) is one OAuth login; apps (Gmail, Drive, Calendar) are its MCP servers, each on/off per user.
Only providers/apps in settings (PROVIDERS/APPS + [providers.<name>] / [apps.<name>] overrides) exist, and only over HTTP: an MCP stdio server
would run on the host, outside the sandbox. Tokens are encrypted at rest (Fernet, SIMP_SECRET_KEY in <data_dir>/.env)
and only ever sent to the app's own token/MCP URLs: never logged, never in prompts, events or the sandbox."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken

from simp_agent.plugins.mcp import McpPlugin

from . import policy
from . import protocol as p

log = logging.getLogger("simp_server")

PROVIDERS = {"google": {
    "kind": "oauth", "label": "Google",
    "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "revoke_url": "https://oauth2.googleapis.com/revoke",
    "scopes": ["openid", "https://www.googleapis.com/auth/userinfo.email"],  # always; each app adds its own
    "client_id_env": "GOOGLE_CLIENT_ID", "client_secret_env": "GOOGLE_CLIENT_SECRET",
}, "github": {  # kind "token": the user pastes a personal token; no OAuth app to register
    "kind": "token", "label": "GitHub",
    "token_help": "Make a fine-grained personal access token with the repo access you want the agent to have.",
    "token_help_url": "https://github.com/settings/personal-access-tokens",
    "header": "Authorization: Bearer {token}",
    "validate_url": "https://api.github.com/user",  # optional: GET once on save; 401/403 = rejected; json login/email kept
}}
# kind "mcp_oauth": the MCP server's own OAuth, found from its URL (RFC 9728 / 8414) with a client we register ourselves
# (RFC 7591), so there is no app to register by hand. The provider name is the app name.
_MCP_OAUTH = {
    "notion": ("Notion", "Pages, databases and comments in Notion.", "https://mcp.notion.com/mcp"),
    "linear": ("Linear", "Issues, projects and cycles in Linear.", "https://mcp.linear.app/mcp"),
    "sentry": ("Sentry", "Errors, issues and releases in Sentry.", "https://mcp.sentry.dev/mcp"),
    "atlassian": ("Atlassian", "Jira issues and Confluence pages.", "https://mcp.atlassian.com/v1/mcp"),
    "canva": ("Canva", "Find, make and export Canva designs.", "https://mcp.canva.com/mcp"),
}
PROVIDERS.update({n: {"kind": "mcp_oauth", "label": lab, "mcp_url": url} for n, (lab, _, url) in _MCP_OAUTH.items()})
NO_EXPIRY = 1e18  # expires_at for pasted tokens: never refreshed
APPS = {  # the app name is also the MCP server name, so its tools are "<app>__<tool>"
    "gmail": {"label": "Gmail", "description": "Search, read, label and draft email.", "icon": "gmail",
              "provider": "google", "scopes": ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.send"],
              "url": "http://127.0.0.1:8101/mcp"},  # our workspace-mcp (simp_server.google_mcp), not Google's preview MCP
    "drive": {"label": "Google Drive", "description": "Find, read and create files in Drive.", "icon": "drive",
              "provider": "google", "scopes": ["https://www.googleapis.com/auth/drive"],
              "url": "http://127.0.0.1:8102/mcp"},
    "calendar": {"label": "Google Calendar", "description": "See and manage calendar events.", "icon": "calendar",
                 "provider": "google", "scopes": ["https://www.googleapis.com/auth/calendar.events",
                                                 "https://www.googleapis.com/auth/calendar.readonly"],  # listing calendars
                 "url": "http://127.0.0.1:8103/mcp"},
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
    **{n: {"label": lab, "description": d, "icon": n, "provider": n, "url": url} for n, (lab, d, url) in _MCP_OAUTH.items()},
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
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)  # never readable by others, not even briefly
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a") as out:
        out.write(("" if not old or old.endswith("\n") else "\n") + f"SIMP_SECRET_KEY={k}\n")
    log.warning("made a new SIMP_SECRET_KEY in %s: keep it, losing it means every user must reconnect", f)
    return k.encode()


def _email(id_token: str | None) -> str | None:
    # from the token endpoint over TLS (OIDC 3.1.3.7): the payload can be read without checking the signature
    try:
        part = id_token.split(".")[1]
        c = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return c["email"] if c.get("email_verified") is True else None  # unverified = anyone could claim it
    except Exception:
        return None


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _is_401(e: BaseException) -> bool:
    if isinstance(e, BaseExceptionGroup):
        return any(_is_401(x) for x in e.exceptions)
    r = getattr(e, "response", None)  # httpx / httpx2 HTTPStatusError
    return getattr(r, "status_code", None) == 401


def _granted(row: dict | None) -> set[str]:
    return set((row and row.get("scopes") or "").split())


def new_link_id() -> str:
    return "lnk_" + secrets.token_hex(4)


class Connections:
    def __init__(self, settings: dict, store, keys: dict):
        self.settings, self.store, self.keys = settings, store, keys
        self.apps = providers(settings)  # OAuth providers; the user-facing apps are self.app_list
        self.app_list = _merged(APPS, settings.get("apps", dict()))
        self.fernet = Fernet(secret_key(keys, settings["data_dir"]))
        self.pending: dict[str, tuple] = dict()  # ponytail: in memory, a restart drops OAuth starts in flight
        self.http = httpx.AsyncClient(timeout=20)
        self.found: dict[str, dict] = dict()  # mcp_oauth provider -> its endpoints + our registered client
        self.clients_file = Path(settings["data_dir"]) / "mcp_clients.json"  # registered clients, encrypted

    async def _oauth(self, name: str) -> dict:
        """Endpoints and client of an OAuth provider: auth_url, token_url, revoke_url?, client_id, client_secret?.
        RuntimeError when it can't be set up (no keys in .env, no OAuth metadata, registration refused)."""
        a = self.app(name)
        if a.get("kind") != "mcp_oauth":
            cid, sec = self._client(a)
            return {**a, "client_id": cid, "client_secret": sec}
        if name not in self.found:
            ep = await self._discover(a["mcp_url"])
            self.found[name] = {**ep, **await self._register(name, ep)}
        return self.found[name]

    async def _get_json(self, url: str) -> dict | None:
        try:
            r = await self.http.get(url)
            return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    async def _discover(self, mcp_url: str) -> dict:
        """The MCP server's resource metadata names its authorization server; that one's metadata has the endpoints."""
        u = urllib.parse.urlsplit(mcp_url)
        origin, auth_server = f"{u.scheme}://{u.netloc}", f"{u.scheme}://{u.netloc}"
        for url in (f"{origin}/.well-known/oauth-protected-resource{u.path.rstrip('/')}", f"{origin}/.well-known/oauth-protected-resource"):
            if (j := await self._get_json(url)) and j.get("authorization_servers"):
                auth_server = j["authorization_servers"][0]
                break
        s = urllib.parse.urlsplit(auth_server)
        base, path = f"{s.scheme}://{s.netloc}", s.path.rstrip("/")
        for url in (f"{base}/.well-known/oauth-authorization-server{path}", f"{base}/.well-known/openid-configuration{path}",
                    f"{base}{path}/.well-known/openid-configuration"):
            if (j := await self._get_json(url)) and j.get("authorization_endpoint") and j.get("token_endpoint"):
                return {"auth_url": j["authorization_endpoint"], "token_url": j["token_endpoint"],
                        "registration_url": j.get("registration_endpoint"), "revoke_url": j.get("revocation_endpoint"),
                        "resource": mcp_url}
        raise RuntimeError("this app has no OAuth sign-in we can use")

    async def _register(self, name: str, ep: dict) -> dict:
        """Our client at this provider: registered once per redirect URI and kept (encrypted) in mcp_clients.json."""
        key, saved = f"{name} {self.redirect_uri(name)}", dict()
        try:
            saved = json.loads(self.clients_file.read_text())
            return json.loads(self.fernet.decrypt(saved[key]).decode())
        except (OSError, ValueError, KeyError, InvalidToken):
            pass
        if not ep.get("registration_url"):
            raise RuntimeError("this app needs a registered client; it can't be connected yet")
        r = await self.http.post(ep["registration_url"], json={
            "client_name": "Simp", "redirect_uris": [self.redirect_uri(name)], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"})
        if r.status_code not in (200, 201) or not r.json().get("client_id"):
            raise RuntimeError(f"the app refused our sign-in client ({r.status_code})")
        c = {"client_id": r.json()["client_id"], "client_secret": r.json().get("client_secret")}
        saved[key] = self.fernet.encrypt(json.dumps(c).encode()).decode()
        self.clients_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.clients_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(saved, f)
        return c

    @staticmethod
    def _creds(o: dict) -> dict:  # client auth in the token request body (public clients: no secret)
        return {"client_id": o["client_id"], **({"client_secret": o["client_secret"]} if o.get("client_secret") else dict())}

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
        same = next((r for r in await self.links(user_id, name) if who and r["account_email"] == who), None)
        await self.store.save_connection(user_id, same["link_id"] if same else new_link_id(), name, who,
                                         self.fernet.encrypt(token.encode()).decode(), "", NO_EXPIRY)
        for n, app in self.app_list.items():  # a forgotten app turns on again with its new token
            if app.get("provider") == name:
                await self.store.set_app_disabled(user_id, n, False)

    def _client(self, a: dict) -> tuple[str, str]:
        cid, sec = self.keys.get(a["client_id_env"]), self.keys.get(a["client_secret_env"])
        if not cid or not sec:
            raise RuntimeError(f"{a['client_id_env']} / {a['client_secret_env']} not set in .env")
        return cid, sec

    def redirect_uri(self, name: str) -> str:
        return f"{self.settings.get('public_url', 'http://localhost:8766').rstrip('/')}/api/connections/{name}/callback"

    def authorized(self, app: dict, row: dict | None) -> bool:
        """This link has every scope of this app (apps without scopes: the login is enough)."""
        return row is not None and set(app.get("scopes", ())) <= _granted(row)

    async def links(self, user_id: str, prov: str) -> list[dict]:
        """The user's accounts of one provider, oldest (= default) first."""
        return [r for r in await self.store.connections(user_id) if r["app"] == prov]

    async def link(self, user_id: str, link_id: str) -> dict | None:
        return next((r for r in await self.store.connections(user_id) if r["link_id"] == link_id), None)

    async def start(self, user_id: str, app_name: str, link: dict | None = None) -> tuple[str, str]:
        """(auth URL, browser nonce) for one app: only its scopes (+ the provider's base ones); Google adds them to
        earlier grants. The nonce goes in an HttpOnly cookie; the callback needs it, so a URL sent to someone else fails.
        link None: Google shows the account chooser (add an account); a link: add scopes to that account only."""
        if app_name not in self.app_list or not self.app_list[app_name].get("provider"):
            raise LookupError(f"unknown app {app_name!r}")
        name = self.app_list[app_name]["provider"]
        a = self.app(name)
        if a.get("kind") == "token":
            raise LookupError(f"{name!r} takes a pasted token, not OAuth")
        o = await self._oauth(name)
        now = time.time()
        self.pending = {s: v for s, v in self.pending.items() if v[3] > now}
        state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        self.pending[state] = (user_id, name, verifier, now + STATE_TTL, app_name, _hash(nonce), link and link["link_id"])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        scope = " ".join(a.get("scopes", []) + self.app_list[app_name].get("scopes", []))
        q = {"client_id": o["client_id"], "redirect_uri": self.redirect_uri(name), "response_type": "code", "state": state,
             "code_challenge": challenge, "code_challenge_method": "S256", **({"scope": scope} if scope else dict())}
        if a.get("kind") == "mcp_oauth":
            q["resource"] = o["resource"]  # RFC 8707: a token for this MCP server only
        else:  # Google: a refresh token, the account chooser, scopes added to earlier grants
            q |= {"access_type": "offline", "prompt": "consent select_account", "include_granted_scopes": "true",
                  **({"login_hint": link["account_email"]} if link and link["account_email"] else dict())}
        return f"{o['auth_url']}?{urllib.parse.urlencode(q)}", nonce

    async def callback(self, name: str, code: str, state: str, nonce: str = "") -> str:
        """The user id. Raises ValueError with a short, token-free reason."""
        v = self.pending.pop(state, None)
        if v is None or v[1] != name or v[3] < time.time() or not secrets.compare_digest(v[5], _hash(nonce)):
            raise ValueError("bad or expired state")
        user_id, _, verifier, _, app_name, _, link_id = v
        a = self.app(name)
        o = await self._oauth(name)
        mcp = a.get("kind") == "mcp_oauth"
        r = await self.http.post(o["token_url"], data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri(name),
            **self._creds(o), "code_verifier": verifier, **({"resource": o["resource"]} if mcp else dict())})
        if r.status_code != 200:
            raise ValueError(f"token exchange failed ({r.status_code})")
        t = r.json()
        if not t.get("refresh_token") and not mcp:  # an MCP app may give none: reconnect when the token ends
            raise ValueError("no refresh token returned")
        email = _email(t.get("id_token"))
        mine = await self.links(user_id, name)
        if mcp and not email:  # no account name to tell logins apart: one account, updated on reconnect
            old = mine[0] if mine else None
        elif link_id:  # adding scopes to one account: the user must not pick another one in Google's chooser
            old = next((r for r in mine if r["link_id"] == link_id), None)
            if old is None or not email or email != old["account_email"]:
                raise ValueError("signed in with a different account; nothing saved")
        else:  # same account again -> update it, else a new account
            old = next((r for r in mine if email and r["account_email"] == email), None)
        # Google's "scope" = everything granted so far (include_granted_scopes); missing -> what we asked for
        scopes = t.get("scope") or " ".join(sorted(_granted(old) | set(a.get("scopes", [])) |
                                                  set(self.app_list[app_name].get("scopes", []))))
        await self.store.save_connection(user_id, old["link_id"] if old else new_link_id(), name, email, self.fernet.encrypt(
            t["access_token"].encode()).decode(), self.fernet.encrypt(t["refresh_token"].encode()).decode() if t.get("refresh_token") else "",
            time.time() + float(t.get("expires_in", 3600)), scopes)
        await self.store.set_app_disabled(user_id, app_name, False)  # only the app just connected turns on
        return user_id

    def login_redirect_uri(self) -> str:
        return f"{self.settings.get('public_url', 'http://localhost:8766').rstrip('/')}/api/auth/google/callback"

    def login_start(self) -> tuple[str, str]:
        """(Google auth URL, browser nonce) for web sign-in: openid + email only, no API scopes, no refresh token."""
        a = self.app("google")
        cid, _ = self._client(a)
        now = time.time()
        self.pending = {s: v for s, v in self.pending.items() if v[3] > now}
        state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        self.pending[state] = (None, "login", verifier, now + STATE_TTL, None, _hash(nonce), None)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        q = {"client_id": cid, "redirect_uri": self.login_redirect_uri(), "response_type": "code",
             "scope": " ".join(a["scopes"]), "state": state, "code_challenge": challenge,
             "code_challenge_method": "S256", "prompt": "select_account"}
        return f"{a['auth_url']}?{urllib.parse.urlencode(q)}", nonce

    async def login_callback(self, code: str, state: str, nonce: str = "") -> str:
        """The signed-in Google email. Raises ValueError with a short, token-free reason."""
        v = self.pending.pop(state, None)
        if v is None or v[1] != "login" or v[3] < time.time() or not secrets.compare_digest(v[5], _hash(nonce)):
            raise ValueError("bad or expired state")
        a = self.app("google")
        cid, sec = self._client(a)
        r = await self.http.post(a["token_url"], data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.login_redirect_uri(),
            "client_id": cid, "client_secret": sec, "code_verifier": v[2]})
        if r.status_code != 200:
            raise ValueError(f"token exchange failed ({r.status_code})")
        if not (email := _email(r.json().get("id_token"))):
            raise PermissionError("Google did not give a verified email.")
        return email

    async def forget_app(self, user_id: str, app_name: str) -> None:
        """Per-app disconnect: drop its scopes locally (Google can't revoke one scope); the last app revokes the token.
        ponytail: Google still holds the scope, so a later connect of another app may report it granted again."""
        app = self.app_list.get(app_name)
        if not app or not app.get("provider"):
            raise LookupError(f"unknown app {app_name!r}")
        for row in await self.links(user_id, app["provider"]):
            await self._forget(user_id, app_name, row)
        await self.store.set_app_disabled(user_id, app_name, True)  # stays off until this app is connected again

    async def _forget(self, user_id: str, app_name: str, row: dict) -> None:
        app, prov = self.app_list[app_name], self.app_list[app_name]["provider"]
        left = _granted(row) - set(app.get("scopes", ()))
        others = [a for n, a in self.app_list.items() if a.get("provider") == prov and n != app_name]
        if not app.get("scopes") or not any(set(a.get("scopes", ())) <= left for a in others if a.get("scopes")):
            return await self.delete(user_id, row["link_id"])
        await self.store.set_connection_scopes(user_id, row["link_id"], " ".join(sorted(left)))

    async def list(self, user_id: str) -> list[dict]:
        """Every linked account (never tokens); default = the oldest of its provider."""
        seen, out = set(), list()
        for r in await self.store.connections(user_id):
            out.append({"link_id": r["link_id"], "provider": r["app"], "label": self.apps.get(r["app"], dict()).get(
                "label", r["app"]), "email": r["account_email"], "status": r["status"], "created": r["created"],
                "scopes": sorted(_granted(r)), "default": r["app"] not in seen})
            seen.add(r["app"])
        return out

    async def delete(self, user_id: str, link_id: str) -> None:
        """Revoke and drop one account; the next oldest of its provider becomes the default. LookupError: unknown."""
        row = await self.link(user_id, link_id)
        if row is None:
            raise LookupError(f"unknown link {link_id!r}")
        name = row["app"]
        url = (self.found.get(name) or self.apps.get(name, dict())).get("revoke_url")
        if row["refresh_token_enc"] and url:
            try:  # best effort: the row goes either way
                extra = {"client_id": self.found[name]["client_id"]} if name in self.found else dict()
                await self.http.post(url, data={"token": self.fernet.decrypt(row["refresh_token_enc"]).decode(), **extra})
            except Exception as e:
                log.warning("revoke %s failed: %s", name, type(e).__name__)
        await self.store.delete_connection(user_id, link_id)
        if not await self.links(user_id, name):  # last account gone: its apps start fresh on the next connect
            await self.store.clear_app_flags(user_id, [n for n, a in self.app_list.items() if a.get("provider") == name])

    async def list_apps(self, user_id: str) -> list[dict]:
        """Every app; enabled = provider connected and not turned off (default on: a login enables all its apps)."""
        rows = await self.store.connections(user_id)
        off, on = await self.store.disabled_apps(user_id), await self.store.enabled_apps(user_id)
        out = list()
        for n, a in self.app_list.items():
            if a.get("provider") is None:
                out.append({"app": n, "label": a.get("label", n), "description": a.get("description", ""),
                            "icon": a.get("icon", n), "provider": None, "auth": None, "connected": True, "enabled": n in on,
                            "email": None, "status": None})
                continue
            prov = self.apps.get(a["provider"], dict())
            ok = [r for r in rows if r["app"] == a["provider"] and self.authorized(a, r)]
            row = ok[0] if ok else None  # the default account for this app
            out.append({"app": n, "label": a.get("label", n), "description": a.get("description", ""),
                        "icon": a.get("icon", n), "provider": a["provider"], "auth": "token" if prov.get("kind") == "token" else "oauth",
                        **({"token_help": prov.get("token_help", ""), "token_help_url": prov.get("token_help_url")}
                           if prov.get("kind") == "token" else dict()), "connected": row is not None,
                        "enabled": row is not None and n not in off, "email": row and row["account_email"],
                        "status": row and row["status"], "accounts": [
                            {"link_id": r["link_id"], "email": r["account_email"], "status": r["status"],
                             "created": r["created"]} for r in ok]})
        return out

    async def set_enabled(self, user_id: str, name: str, on: bool) -> None:
        """LookupError: unknown app; PermissionError: enabling an app whose provider is not connected."""
        if name not in self.app_list:
            raise LookupError(f"unknown app {name!r}")
        prov = self.app_list[name].get("provider")
        if prov is None:
            return await self.store.set_app_on(user_id, name, on)
        if on and not any(self.authorized(self.app_list[name], r) for r in await self.links(user_id, prov)):
            raise PermissionError(f"connect {name} first")
        await self.store.set_app_disabled(user_id, name, not on)

    async def _access(self, user_id: str, row: dict) -> str | None:
        """A valid access token, refreshed when it ends within REFRESH_EARLY; None (and needs_reconnect) on failure."""
        try:
            if row["expires_at"] - time.time() > REFRESH_EARLY:
                return self.fernet.decrypt(row["access_token_enc"]).decode()
            refresh = self.fernet.decrypt(row["refresh_token_enc"]).decode()
        except InvalidToken:  # SIMP_SECRET_KEY changed: only this login is lost
            await self.store.set_connection_status(user_id, row["link_id"], "needs_reconnect")
            return None
        try:
            o = await self._oauth(row["app"])
            r = await self.http.post(o["token_url"], data={"grant_type": "refresh_token", "refresh_token": refresh, **self._creds(o),
                                                           **({"resource": o["resource"]} if o.get("resource") else dict())})
        except Exception as e:  # network, config: try again next run, the login itself may be fine
            log.warning("refresh %s failed: %s", row["app"], type(e).__name__)
            return None
        t = r.json() if r.status_code == 200 else None
        if not t or not t.get("access_token"):
            if r.status_code in (400, 401):  # invalid_grant: revoked or expired for good
                await self.store.set_connection_status(user_id, row["link_id"], "needs_reconnect")
            else:
                log.warning("refresh %s failed: HTTP %s", row["app"], r.status_code)
            return None
        await self.store.update_connection_token(user_id, row["link_id"], self.fernet.encrypt(
            t["access_token"].encode()).decode(), time.time() + float(t.get("expires_in", 3600)))
        row["expires_at"] = time.time() + float(t.get("expires_in", 3600))  # servers() passes it to UserMcp
        return t["access_token"]

    async def servers(self, user_id: str) -> tuple[list[dict], list[str]]:
        """McpPlugin server specs for the user's enabled apps, and notices for providers that need a reconnect."""
        out, problems = list(), list()
        off, on = await self.store.disabled_apps(user_id), await self.store.enabled_apps(user_id)
        out += [{"name": n, "url": a["url"]} for n, a in self.app_list.items() if a.get("provider") is None and n in on]
        defaults = set()  # apps seen: the first authorized link of each app is its default
        for row in await self.store.connections(user_id):
            mine = {n: a for n, a in self.app_list.items() if a.get("provider") == row["app"] and n not in off
                    and self.authorized(a, row)}
            if not mine:
                continue
            a = self.apps.get(row["app"])
            if a is None:  # app removed from settings
                continue
            token = await self._access(user_id, row) if row["status"] == "ok" else None
            if token is None:
                gone = (await self.link(user_id, row["link_id"]) or dict()).get("status") != "ok"
                who = f" ({row['account_email']})" if row["account_email"] else ""
                problems.append(f"{a.get('label', row['app'])}{who} " + ("connection needs reconnect (Crafts > Portals)"
                                if gone else "is not reachable right now, try again later"))
                continue
            for n, app in mine.items():
                out.append({"name": n, "url": app["url"], "headers": self._header(row["app"], token), "provider": row[
                    "app"], "link_id": row["link_id"], "email": row["account_email"], "default": n not in defaults,
                    "expires_at": row["expires_at"]})
                defaults.add(n)
        return out, problems



class UserMcp(McpPlugin):
    """The run's MCP plugin: the user's connected apps. Tools not marked read-only need approval; every call is audited.
    Tokens are fixed at setup; expired() tells the run to reload before a turn once the earliest one is near its end."""

    def __init__(self, run, servers: list[dict] | None = None):
        super().__init__(servers=servers)
        self.run, self.names = run, set()
        self.api, self.config, self.stale = None, dict(), False  # stale: the user changed portals; reload next turn
        self.emails: dict[str, str | None] = dict()  # link_id -> account email (audit, approval card)
        self.default: dict[str, str] = dict()  # app -> its default link_id
        self.expires = NO_EXPIRY  # earliest token expiry of the links
        self.links: dict[str, set] = dict()  # tool name -> link ids it can run with (audit)

    def expired(self) -> bool:
        return time.time() > self.expires - REFRESH_EARLY

    async def reload(self) -> None:
        """Drop the old connections and tools, read the user's portals again. Only between turns."""
        self.stale = False
        if self.api is None:  # never set up: the first prompt reads fresh portals anyway
            return
        await self.session_shutdown()
        for n in self.names:
            self.api.unregister_tool(n)
            self.run.session.needs_approval.discard(n)
        self.names, self.servers, self.stop = set(), None, asyncio.Event()
        self.emails, self.default, self.expires, self.links = dict(), dict(), NO_EXPIRY, dict()
        await self.setup(self.api, self.config)

    async def tool_call(self, call):
        if self.stale and call.name in self.names:  # turned off or reconnected while this turn runs
            return {"block": "portals changed; they apply from the next message"}
        return None

    async def setup(self, api, config: dict) -> None:
        self.api, self.config = api, config
        if self.servers is None:  # tests pass servers directly
            self.servers, problems = await self.run.mgr.conns.servers(self.run.user_id)
            for text in problems:
                await self.run.durable(p.Notice, level="warning", text=text)
        if not self.servers:
            return
        for spec in self.servers:
            if spec.get("link_id"):
                self.emails[spec["link_id"]] = spec.get("email")
                if spec.get("default"):
                    self.default[spec["name"]] = spec["link_id"]
            self.expires = min(self.expires, spec.get("expires_at", NO_EXPIRY))
        tools = list()

        class Collect:  # gather every link's tools first: same-named tools of one app become one tool
            emit = api.emit

            def register_tool(self, t):
                tools.append(t)
        await super().setup(Collect(), config)
        by_name: dict[str, list] = dict()
        for t in tools:
            by_name.setdefault(t.name, list()).append(t)
        for name, ts in by_name.items():
            self.links[name] = {t.link_id for t in ts}
            api.register_tool(ts[0] if len(ts) == 1 else self._merge(ts))
        session = self.run.session
        for t in session.agent.tools:
            if hasattr(t, "read_only_hint"):  # set by McpPlugin on every MCP tool
                self.names.add(t.name)
                # asked unless read-only; a write-like name is asked even if its server says read-only
                if t.read_only_hint is not True or policy.MCP_WRITE.search(t.name.partition("__")[2]):
                    session.needs_approval.add(t.name)
        # for the portal detail page; ponytail: in memory, filled when a chat opens the app (empty after a restart)
        known = self.run.mgr.tools_seen.setdefault(self.run.user_id, dict())
        for t in session.agent.tools:
            if t.name in self.names:
                app, _, tool = t.name.partition("__")
                known.setdefault(app, dict())[tool] = t.name in session.needs_approval

    async def _tools(self, spec: dict, client):
        out = await super()._tools(spec, client)
        for t in out:
            t.link_id = spec.get("link_id")
        return out

    def _merge(self, ts: list):
        """One tool for many accounts: optional link_id picks the account (missing -> the default).
        The model sees link ids and emails only, never tokens."""
        app = ts[0].name.partition("__")[0]
        by_link = {t.link_id: t for t in ts}
        default = self.default.get(app) or ts[0].link_id
        if default not in by_link:  # the default link failed to connect
            default = self.default[app] = ts[0].link_id
        base = by_link[default]
        accounts = ", ".join(f"{lid} = {self.emails.get(lid) or 'account'}" + (" (default)" if lid == default else "")
                             for lid in by_link)
        params = dict(base.parameters)
        params["properties"] = {**params.get("properties", dict()), "link_id": {
            "type": "string", "enum": list(by_link), "description": f"Which account to use: {accounts}. Omit for the default."}}

        async def execute(args, ctx):
            args = dict(args)
            t = by_link.get(args.pop("link_id", None) or default)
            if t is None:
                return f"{base.name} error: unknown link_id; use one of {', '.join(by_link)}"
            return await t.execute(args, ctx)
        tool = dataclasses.replace(base, parameters=params, execute=execute)
        tool.read_only_hint, tool.destructive_hint = base.read_only_hint, base.destructive_hint
        tool.link_id = None
        return tool

    def link_of(self, call) -> str | None:
        """The link the call ran with: the one asked for if this tool has it, else the tool's default."""
        links = self.links.get(call.name, set())
        if len(links) == 1:  # unmerged: any link_id the model passes is ignored
            return next(iter(links))
        lid = (call.arguments or dict()).get("link_id") or self.default.get(call.name.partition("__")[0])
        return lid if lid in links else None  # unknown link_id: nothing ran

    def shown_args(self, call) -> dict:
        """Approval card args: the account's email instead of the raw link id."""
        args = dict(call.arguments or dict())
        if "link_id" in args:
            args["link_id"] = self.emails.get(args["link_id"]) or args["link_id"]
        return args

    async def _connect(self, spec: dict):
        try:
            return await super()._connect(spec)
        except Exception as e:  # revoked/expired token: ask the user to reconnect instead of failing every run
            if spec.get("provider") and _is_401(e):
                await self.run.mgr.store.set_connection_status(self.run.user_id, spec["link_id"], "needs_reconnect")
            raise

    async def tool_result(self, call, result):
        if call.name in self.names:
            server, _, tool = call.name.partition("__")
            ok = not result.is_error and not result.content.startswith(f"{call.name} error:")
            await self.run.mgr.store.add_audit(self.run.user_id, self.run.sid, server, tool,
                                               self.run.decisions.pop(call.id, "auto"), ok, self.link_of(call))
        return None
