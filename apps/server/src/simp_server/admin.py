"""Admin API (/api/admin/*): users, points, kill switch, audit log, runtime settings.

Admins are the emails in ADMIN_EMAILS (<data_dir>/.env or the env, comma-separated); never editable from the app.
Every route goes through `admin_user`: signed in + email in ADMIN_EMAILS + not revoked, else 403. Every write goes into
admin_audit (append-only: no route updates or deletes it).
"""

from __future__ import annotations

import collections
import copy
import json
import math
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import budget

BIG_GRANT = 100_000  # |points| above this needs confirm: true
RATE = {"write": 60, "read": 600}  # requests per minute per admin
WEEK = 7 * 86400


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class Credit(Reason):
    points: int
    confirm: bool = False


class QuotaIn(Reason):
    quota_mb: float | None = Field(default=None, ge=0, le=1e7)  # None: back to the global workspace.quota_mb


class SettingIn(Reason):
    value: object = None


# ---- runtime settings: an explicit whitelist, one validator per key ------------------------------------------------

def _num(lo: float, hi: float, lo_open: bool = False):
    def check(v, settings):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("must be a number")
        if v < lo or v > hi or (lo_open and v == lo):
            raise ValueError(f"must be {'>' if lo_open else '>='} {lo:g} and <= {hi:g}")
        return float(v)
    return check


def _profile(v, settings):
    if not isinstance(v, str) or v not in settings["profiles"]:
        raise ValueError(f"must be one of {sorted(settings['profiles'])}")
    return v


def _emails(v, settings):
    if not isinstance(v, list) or not all(isinstance(e, str) and "@" in e and len(e) <= 254 for e in v):
        raise ValueError("must be a list of email addresses")
    return sorted({e.strip().lower() for e in v})


def editable(settings: dict) -> dict:
    """key -> validator. Never secrets, buckets, endpoints, domains, mount scope or ADMIN_EMAILS."""
    keys = {"default_profile": _profile, "allowed_emails": _emails,
            "budget.user_day_usd": _num(0, 10_000), "budget.run_usd": _num(0, 10_000),
            "billing.points_per_usd": _num(0, 1e9, lo_open=True), "sandbox.paused_price_ratio": _num(0, 1),
            "workspace.quota_mb": _num(0, 1e7)}
    for name in settings["profiles"]:
        keys[f"profiles.{name}.price_in"] = keys[f"profiles.{name}.price_out"] = _num(0, 10_000)
    return keys


DEFAULTS = {"budget.user_day_usd": budget.Limits.user_day_usd, "budget.run_usd": budget.Limits.run_usd,
            "billing.points_per_usd": 1000.0, "sandbox.paused_price_ratio": 0.1, "allowed_emails": [],
            "workspace.quota_mb": 10240.0}


def get_key(settings: dict, key: str):
    if key.startswith("profiles."):
        name, field = key.removeprefix("profiles.").rsplit(".", 1)
        return settings["profiles"].get(name, dict()).get(field, 0.0)
    if "." in key:
        sec, k = key.split(".", 1)
        return settings.get(sec, dict()).get(k, DEFAULTS.get(key))
    return settings.get(key, DEFAULTS.get(key))


def set_key(settings: dict, key: str, value) -> None:
    """Copy-on-write for profiles: a loaded run keeps the profile dict it started with."""
    if key.startswith("profiles."):
        name, field = key.removeprefix("profiles.").rsplit(".", 1)
        settings["profiles"][name] = {**settings["profiles"][name], field: value}
    elif "." in key:
        sec, k = key.split(".", 1)
        settings[sec] = {**settings.get(sec, dict()), k: value}
    else:
        settings[key] = value


def refresh(settings: dict, mgr) -> None:
    """Push settings into the objects that cached them. Runs in progress keep their own snapshot (Run.limits)."""
    mgr.limits = budget.limits(settings)
    if c := getattr(mgr.sandbox, "compute", None):
        c.billing = budget.billing(settings)
        c.paused_ratio = float(settings.get("sandbox", dict()).get("paused_price_ratio", 0.1))


async def load_overrides(settings: dict, mgr) -> None:
    """settings.toml values, overridden by settings_kv. A stored value that no longer validates is skipped."""
    settings.setdefault("_file_values", {k: copy.deepcopy(get_key(settings, k)) for k in editable(settings)})
    keys = editable(settings)
    for r in await mgr.store._all("SELECT key, value FROM settings_kv"):
        if (check := keys.get(r["key"])) is None:
            continue
        try:
            set_key(settings, r["key"], check(json.loads(r["value"]), settings))
        except ValueError:
            continue
    refresh(settings, mgr)


# ---- routes ---------------------------------------------------------------------------------------------------------

def mount(app: FastAPI, settings: dict, mgr, user) -> None:
    store = mgr.store
    hits: dict[tuple, collections.deque] = collections.defaultdict(collections.deque)
    settings.setdefault("_file_values", {k: copy.deepcopy(get_key(settings, k)) for k in editable(settings)})

    async def admin_user(request: Request, u=Depends(user)) -> dict:
        if not (mgr.admin_emails and u["name"].lower() in mgr.admin_emails and await store.user_active(u["id"])):
            raise HTTPException(403, "admin only")
        kind = "read" if request.method == "GET" else "write"
        q, now = hits[(u["id"], kind)], time.monotonic()
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= RATE[kind]:
            raise HTTPException(429, "too many admin requests; wait a minute")
        q.append(now)
        return u

    def audit_sql(actor: str, action: str, target: str | None, detail: dict):
        return ("INSERT INTO admin_audit(actor_user_id, action, target_user_id, detail, created) VALUES(?,?,?,?,?)",
                (actor, action, target, json.dumps(detail), time.time()))

    async def audit(actor: str, action: str, target: str | None, detail: dict) -> None:
        await store.db.execute(*audit_sql(actor, action, target, detail))
        await store.db.commit()

    async def target(uid: str) -> dict:
        rows = await store._all("SELECT id, name, disabled FROM users WHERE id=?", uid)
        if not rows:
            raise HTTPException(404, "no such user")
        return rows[0]

    def rate() -> float:
        return budget.billing(settings)[1]

    def paused_file() -> Path:
        return Path(settings["data_dir"]) / "PAUSED"

    USER_SQL = """SELECT u.id, u.name AS email, u.disabled,
        (SELECT MIN(created) FROM agents WHERE user_id=u.id) AS created,
        (SELECT COALESCE(SUM(points), 0) FROM credit_ledger WHERE user_id=u.id) AS granted,
        (SELECT COALESCE(SUM(cost), 0) FROM usage WHERE user_id=u.id) AS spent_usd,
        (SELECT COALESCE(SUM(cost), 0) FROM usage WHERE user_id=u.id AND at>=?) AS spend_7d_usd,
        MAX(COALESCE((SELECT MAX(at) FROM usage WHERE user_id=u.id), 0),
            COALESCE((SELECT MAX(updated) FROM sessions WHERE user_id=u.id), 0),
            COALESCE((SELECT MAX(created) FROM tokens WHERE user_id=u.id), 0)) AS last_active
        FROM users u"""

    def shape(r: dict) -> dict:
        spent = math.ceil(round(r["spent_usd"] * rate(), 6))
        return {"id": r["id"], "email": r["email"], "created": r["created"], "revoked": bool(r["disabled"]),
                "points_granted": r["granted"], "points_spent": spent, "points_balance": r["granted"] - spent,
                "spend_7d_usd": round(r["spend_7d_usd"], 4), "last_active": r["last_active"] or None}

    @app.get("/api/admin/me")
    async def me(u=Depends(admin_user)):
        return {"admin": True}

    @app.get("/api/admin/users")
    async def users(q: str = "", limit: int = 50, offset: int = 0, u=Depends(admin_user)):
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = await store._all(USER_SQL + " WHERE lower(u.name) LIKE ? ESCAPE '\\' ORDER BY u.name LIMIT ? OFFSET ?",
                                time.time() - WEEK, like, limit, offset)
        total = (await store._all("SELECT COUNT(*) AS n FROM users WHERE lower(name) LIKE ? ESCAPE '\\'", like))[0]["n"]
        return {"users": [shape(r) for r in rows], "total": total}

    @app.get("/api/admin/users/{uid}")
    async def user_detail(uid: str, u=Depends(admin_user)):
        await target(uid)
        row = (await store._all(USER_SQL + " WHERE u.id=?", time.time() - WEEK, uid))[0]
        ledger = await store._all("SELECT id, points, note, created FROM credit_ledger WHERE user_id=? "
                                  "ORDER BY id DESC LIMIT 50", uid)
        usage = await store._all("SELECT model, COUNT(*) AS calls, SUM(input) AS input, SUM(output) AS output, "
                                 "ROUND(SUM(cost), 4) AS cost_usd FROM usage WHERE user_id=? AND at>=? GROUP BY model "
                                 "ORDER BY cost_usd DESC", uid, time.time() - 30 * 86400)
        return {**shape(row), "ledger": ledger, "usage_30d": usage, "workspace": await store.ws_usage(uid)}

    @app.post("/api/admin/users/{uid}/credit")
    async def credit(uid: str, body: Credit, u=Depends(admin_user)):
        await target(uid)
        if body.points == 0:
            raise HTTPException(400, "points must not be 0")
        if abs(body.points) > BIG_GRANT and not body.confirm:
            raise HTTPException(400, f"more than {BIG_GRANT} points: send confirm: true")
        before = await store.credits(uid, rate())
        await store.db.execute("INSERT INTO credit_ledger(user_id, points, note, created) VALUES(?,?,?,?)",
                               (uid, body.points, body.reason, time.time()))
        await store.db.execute(*audit_sql(u["id"], "credit", uid, {"points": body.points, "reason": body.reason,
                                                                    "before": before["balance"]}))
        await store.db.commit()
        return await store.credits(uid, rate())

    async def set_revoked(uid: str, body: Reason, u: dict, revoke: bool):
        t = await target(uid)
        if revoke and uid == u["id"]:
            raise HTTPException(400, "you cannot revoke yourself")
        if bool(t["disabled"]) == revoke:
            raise HTTPException(409, f"user is already {'revoked' if revoke else 'active'}")
        if revoke:
            await store.revoke(t["name"])  # drops every token
        else:  # Google users sign in again; a CLI user needs `simp-server rotate`
            await store._do("UPDATE users SET disabled=0 WHERE id=?", uid)
        await audit(u["id"], "revoke" if revoke else "unrevoke", uid, {"reason": body.reason})
        return {"revoked": revoke}

    @app.put("/api/admin/users/{uid}/quota")
    async def set_quota(uid: str, body: QuotaIn, u=Depends(admin_user)):
        await target(uid)
        before = (await store.ws_usage(uid) or {}).get("quota_mb")
        await store.ws_set_quota(uid, body.quota_mb)
        await audit(u["id"], "quota", uid, {"before_mb": before, "after_mb": body.quota_mb, "reason": body.reason})
        return {"quota_mb": body.quota_mb}

    @app.post("/api/admin/users/{uid}/revoke")
    async def revoke(uid: str, body: Reason, u=Depends(admin_user)):
        return await set_revoked(uid, body, u, True)

    @app.post("/api/admin/users/{uid}/unrevoke")
    async def unrevoke(uid: str, body: Reason, u=Depends(admin_user)):
        return await set_revoked(uid, body, u, False)

    @app.get("/api/admin/system")
    async def system(u=Depends(admin_user)):
        today = (await store._all("SELECT COALESCE(SUM(cost), 0) AS c FROM usage WHERE at>=?", budget.day_start()))[0]["c"]
        return {"paused": mgr.paused(), "spend_today_usd": round(today, 4),
                "open_sessions": len(mgr.runs), "busy_sessions": sum(1 for r in mgr.runs.values() if r.busy),
                "users": (await store._all("SELECT COUNT(*) AS n FROM users"))[0]["n"],
                "billing_enabled": budget.billing(settings)[0]}

    @app.post("/api/admin/system/{action}")
    async def pause(action: str, body: Reason, u=Depends(admin_user)):
        if action not in ("pause", "resume"):
            raise HTTPException(404, "no such action")
        before = mgr.paused()
        paused_file().touch() if action == "pause" else paused_file().unlink(missing_ok=True)  # same as the CLI
        await audit(u["id"], action, None, {"reason": body.reason, "before": before, "after": mgr.paused()})
        return {"paused": mgr.paused()}

    @app.get("/api/admin/audit")
    async def audit_log(limit: int = 50, offset: int = 0, u=Depends(admin_user)):
        rows = await store._all(
            "SELECT a.id, a.action, a.actor_user_id, ua.name AS actor, a.target_user_id, ut.name AS target, a.detail, "
            "a.created FROM admin_audit a LEFT JOIN users ua ON ua.id=a.actor_user_id LEFT JOIN users ut "
            "ON ut.id=a.target_user_id ORDER BY a.id DESC LIMIT ? OFFSET ?", max(1, min(limit, 200)), max(0, offset))
        return [{**r, "detail": json.loads(r["detail"] or "{}")} for r in rows]

    # settings

    @app.get("/api/admin/settings")
    async def get_settings(u=Depends(admin_user)):
        db = {r["key"]: r for r in await store._all("SELECT key, updated, updated_by FROM settings_kv")}
        return [{"key": k, "value": get_key(settings, k), "file_value": settings["_file_values"].get(k),
                 "source": "db" if k in db else "file", "editable": True,
                 "updated": db[k]["updated"] if k in db else None} for k in editable(settings)]

    async def put(key: str, value, reason: str, actor: str, action: str, extra: dict | None = None):
        if (check := editable(settings).get(key)) is None:
            raise HTTPException(400, f"{key!r} is not editable at runtime")
        try:
            value = check(value, settings)
        except ValueError as e:
            raise HTTPException(400, f"{key}: {e}") from None
        old, now = get_key(settings, key), time.time()
        db = store.db
        await db.execute("INSERT INTO settings_kv VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                         "updated=excluded.updated, updated_by=excluded.updated_by", (key, json.dumps(value), now, actor))
        await db.execute("INSERT INTO settings_history(key, old, new, actor, reason, created) VALUES(?,?,?,?,?,?)",
                         (key, json.dumps(old), json.dumps(value), actor, reason, now))
        await db.execute(*audit_sql(actor, action, None, {"key": key, "before": old, "after": value, "reason": reason,
                                                           **(extra or {})}))
        await db.commit()
        set_key(settings, key, value)  # in memory only after the commit
        refresh(settings, mgr)
        return {"key": key, "value": value, "source": "db"}

    @app.put("/api/admin/settings/{key}")
    async def put_setting(key: str, body: SettingIn, u=Depends(admin_user)):
        return await put(key, body.value, body.reason, u["id"], "setting")

    @app.get("/api/admin/settings/history")
    async def history(key: str = "", limit: int = 100, u=Depends(admin_user)):
        sql, args = "SELECT h.*, us.name AS actor_email FROM settings_history h LEFT JOIN users us ON us.id=h.actor", []
        if key:
            sql, args = sql + " WHERE h.key=?", [key]
        rows = await store._all(sql + " ORDER BY h.id DESC LIMIT ?", *args, max(1, min(limit, 500)))
        return [{**r, "old": json.loads(r["old"]), "new": json.loads(r["new"])} for r in rows]

    @app.post("/api/admin/settings/history/{hid}/rollback")
    async def rollback(hid: int, body: Reason, u=Depends(admin_user)):
        rows = await store._all("SELECT key, old FROM settings_history WHERE id=?", hid)
        if not rows:
            raise HTTPException(404, "no such history row")
        return await put(rows[0]["key"], json.loads(rows[0]["old"]), body.reason, u["id"], "setting_rollback",
                         {"history_id": hid})
