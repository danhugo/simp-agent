import { useCallback, useEffect, useState } from "react";
import { admin, AuthError, type AdminAudit, type AdminHistory, type AdminSetting, type AdminSystem, type AdminUser, type AdminUserDetail } from "./api";
import { errorText } from "./Chat";
import { ago } from "./Memory";

const BIG_GRANT = 100_000;  // same as the server: bigger grants need a second confirm
const fmt = (x: number) => x.toLocaleString("en-US");
const usd = (x: number) => `$${x.toFixed(2)}`;
const when = (t: number | null) => (t ? ago(t) : "never");

/** Text field -> JSON value for a setting: numbers stay numbers, lists are comma-separated, otherwise a string. */
export function parseSetting(text: string, current: unknown): unknown {
  const t = text.trim();
  if (Array.isArray(current)) return t ? t.split(/[\s,]+/).filter(Boolean) : [];
  if (typeof current === "number") return t !== "" && Number.isFinite(Number(t)) ? Number(t) : t;
  return t;
}
export const showSetting = (v: unknown) => (Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v));

/** A form that asks for a reason before a dangerous action. */
function ReasonForm({ label, danger, onSubmit, onCancel, children }: {
  label: string; danger?: boolean; onSubmit: (reason: string) => Promise<void>; onCancel?: () => void; children?: React.ReactNode;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form className="admin-form" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      try { await onSubmit(reason.trim()); setReason(""); } finally { setBusy(false); }
    }}>
      {children}
      <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="Reason (required)" aria-label="Reason" />
      <button className={danger ? "danger" : "primary"} disabled={busy || !reason.trim()}>{label}</button>
      {onCancel && <button type="button" className="ghost" onClick={onCancel}>Cancel</button>}
    </form>
  );
}

type Tab = "overview" | "users" | "audit" | "settings";

/** Admin console: system status and kill switch, users and points, audit log, runtime settings. */
export function Admin({ onError, menuButton }: { onError: (e: unknown) => void; menuButton: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState("");
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);
  const ok = () => setError("");
  return (
    <main className="memory admin">
      <header className="home-head">{menuButton}</header>
      <div className="memory-body">
        <div className="page-head"><h1 className="page-title">Admin</h1></div>
        <div className="mem-toolbar">
          <div className="tabs" role="tablist">
            {([["overview", "Overview"], ["users", "Users"], ["audit", "Audit log"], ["settings", "Settings"]] as const).map(([v, label]) => (
              <button key={v} role="tab" aria-selected={tab === v} className="tab" onClick={() => { setTab(v); ok(); }}>{label}</button>
            ))}
          </div>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {tab === "overview" ? <Overview fail={fail} ok={ok} /> : tab === "users" ? <Users fail={fail} ok={ok} />
          : tab === "audit" ? <Audit fail={fail} /> : <Settings fail={fail} ok={ok} />}
      </div>
    </main>
  );
}

type P = { fail: (e: unknown) => void; ok: () => void };

function Overview({ fail, ok }: P) {
  const [s, setS] = useState<AdminSystem | null>(null);
  const load = useCallback(() => admin.system().then(setS, fail), [fail]);
  useEffect(() => { load(); }, [load]);
  if (!s) return <p className="muted">Loading…</p>;
  return (
    <section aria-label="System">
      <h2>System</h2>
      <dl className="admin-stats">
        <div><dt>Status</dt><dd className={s.paused ? "error" : ""}>{s.paused ? "Paused: every model call is refused" : "Running"}</dd></div>
        <div><dt>Spend today</dt><dd>{usd(s.spend_today_usd)}</dd></div>
        <div><dt>Open sessions</dt><dd>{s.open_sessions} ({s.busy_sessions} busy)</dd></div>
        <div><dt>Users</dt><dd>{s.users}</dd></div>
        <div><dt>Billing</dt><dd>{s.billing_enabled ? "On" : "Off"}</dd></div>
      </dl>
      <h2>{s.paused ? "Resume" : "Pause"} the server</h2>
      <p className="muted small mem-about">{s.paused ? "Lets model calls run again." : "Kill switch: refuses every model call until resumed. Same as `simp-server pause`."}</p>
      <ReasonForm label={s.paused ? "Resume" : "Pause"} danger={!s.paused}
        onSubmit={(r) => admin.pause(!s.paused, r).then(() => { ok(); return load(); }, fail)} />
    </section>
  );
}

function Users({ fail, ok }: P) {
  const [q, setQ] = useState("");
  const [list, setList] = useState<{ users: AdminUser[]; total: number } | null>(null);
  const [sel, setSel] = useState("");
  const load = useCallback(() => admin.users(q).then(setList, fail), [q, fail]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);
  return (
    <section aria-label="Users">
      <input type="search" className="admin-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by email…" aria-label="Search users" />
      {!list ? <p className="muted">Loading…</p> : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Email</th><th>Balance</th><th>Granted</th><th>7 days</th><th>Last active</th><th>Status</th></tr></thead>
            <tbody>
              {list.users.map((u) => (
                <tr key={u.id} className={sel === u.id ? "active" : ""} onClick={() => setSel(sel === u.id ? "" : u.id)}>
                  <td><button className="ghost link" aria-expanded={sel === u.id}>{u.email}</button></td>
                  <td className="num">{fmt(u.points_balance)}</td><td className="num">{fmt(u.points_granted)}</td>
                  <td className="num">{usd(u.spend_7d_usd)}</td><td>{when(u.last_active)}</td>
                  <td>{u.revoked ? <span className="error">Revoked</span> : "Active"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">{list.total} user{list.total === 1 ? "" : "s"}{list.total > list.users.length ? `, showing ${list.users.length}` : ""}</p>
        </div>
      )}
      {sel && <UserPanel key={sel} id={sel} fail={fail} ok={ok} onChange={load} onClose={() => setSel("")} />}
    </section>
  );
}

function UserPanel({ id, fail, ok, onChange, onClose }: P & { id: string; onChange: () => void; onClose: () => void }) {
  const [u, setU] = useState<AdminUserDetail | null>(null);
  const [points, setPoints] = useState("");
  const [confirmBig, setConfirmBig] = useState(false);
  const load = useCallback(() => admin.user(id).then(setU, fail), [id, fail]);
  useEffect(() => { load(); }, [load]);
  if (!u) return <p className="muted">Loading…</p>;
  const n = Number(points), valid = Number.isInteger(n) && n !== 0, big = Math.abs(n) > BIG_GRANT;
  const done = () => { ok(); onChange(); return load(); };
  return (
    <aside className="admin-panel" aria-label={`User ${u.email}`}>
      <div className="page-head"><h2>{u.email}</h2><span className="spacer" /><button className="ghost" onClick={onClose}>Close</button></div>
      <p className="muted small">Joined {when(u.created)} · last active {when(u.last_active)} · {fmt(u.points_balance)} points left of {fmt(u.points_granted)} · {usd(u.spend_7d_usd)} in 7 days</p>
      <h3>Add points</h3>
      <ReasonForm label={big ? "Grant (large)" : "Add points"} danger={big}
        onSubmit={async (r) => {
          if (!valid || (big && !confirmBig)) return;
          await admin.credit(id, n, r, big).then(() => { setPoints(""); setConfirmBig(false); return done(); }, fail);
        }}>
        <input inputMode="numeric" value={points} onChange={(e) => { setPoints(e.target.value); setConfirmBig(false); }} placeholder="Points (negative to correct)" aria-label="Points" />
        {big && valid && <label className="small"><input type="checkbox" checked={confirmBig} onChange={(e) => setConfirmBig(e.target.checked)} /> Yes, {fmt(n)} points</label>}
      </ReasonForm>
      <h3>{u.revoked ? "Restore access" : "Revoke access"}</h3>
      <p className="muted small mem-about">{u.revoked ? "They can sign in with Google again." : "Signs them out everywhere and blocks sign-in and model calls."}</p>
      <ReasonForm label={u.revoked ? "Restore" : "Revoke"} danger={!u.revoked}
        onSubmit={(r) => admin.revoke(id, !u.revoked, r).then(done, fail)} />
      <h3>Points ledger</h3>
      {u.ledger.length === 0 ? <p className="muted small">No grants yet.</p> : (
        <table className="admin-table"><tbody>
          {u.ledger.map((l) => <tr key={l.id}><td>{when(l.created)}</td><td className="num">{l.points > 0 ? "+" : ""}{fmt(l.points)}</td><td>{l.note}</td></tr>)}
        </tbody></table>
      )}
      <h3>Usage, last 30 days</h3>
      {u.usage_30d.length === 0 ? <p className="muted small">No usage.</p> : (
        <table className="admin-table"><thead><tr><th>Model</th><th>Calls</th><th>Cost</th></tr></thead><tbody>
          {u.usage_30d.map((x) => <tr key={x.model}><td>{x.model}</td><td className="num">{fmt(x.calls)}</td><td className="num">{usd(x.cost_usd)}</td></tr>)}
        </tbody></table>
      )}
    </aside>
  );
}

function Audit({ fail }: { fail: (e: unknown) => void }) {
  const [rows, setRows] = useState<AdminAudit[] | null>(null);
  useEffect(() => { admin.audit().then(setRows, fail); }, [fail]);
  if (!rows) return <p className="muted">Loading…</p>;
  if (!rows.length) return <p className="muted">No admin actions yet.</p>;
  return (
    <div className="admin-table-wrap"><table className="admin-table">
      <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
      <tbody>{rows.map((a) => (
        <tr key={a.id}><td title={new Date(a.created * 1000).toLocaleString()}>{ago(a.created)}</td><td>{a.actor}</td><td>{a.action}</td>
          <td>{a.target ?? ""}</td><td className="admin-detail">{JSON.stringify(a.detail)}</td></tr>
      ))}</tbody>
    </table></div>
  );
}

function Settings({ fail, ok }: P) {
  const [rows, setRows] = useState<AdminSetting[] | null>(null);
  const [hist, setHist] = useState<AdminHistory[]>([]);
  const [edit, setEdit] = useState("");
  const [draft, setDraft] = useState("");
  const load = useCallback(() => Promise.all([admin.settings(), admin.history()]).then(([s, h]) => { setRows(s); setHist(h); }, fail), [fail]);
  useEffect(() => { load(); }, [load]);
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <>
      <section aria-label="Settings">
        <p className="muted small mem-about">Changes apply to the next run without a restart. Secrets, storage and admins are not editable here.</p>
        <table className="admin-table">
          <thead><tr><th>Key</th><th>Value</th><th>Source</th><th /></tr></thead>
          <tbody>{rows.map((s) => (
            <tr key={s.key}>
              <td><code>{s.key}</code></td>
              <td>{edit === s.key ? (
                <ReasonForm label="Save" onCancel={() => setEdit("")}
                  onSubmit={(r) => admin.putSetting(s.key, parseSetting(draft, s.value), r).then(() => { setEdit(""); ok(); return load(); }, fail)}>
                  <input value={draft} autoFocus onChange={(e) => setDraft(e.target.value)} aria-label={`Value of ${s.key}`} />
                </ReasonForm>
              ) : showSetting(s.value)}</td>
              <td className="muted small" title={s.source === "db" ? `File value: ${showSetting(s.file_value)}` : undefined}>{s.source === "db" ? "Changed here" : "settings.toml"}</td>
              <td>{edit !== s.key && <button className="ghost" onClick={() => { setEdit(s.key); setDraft(showSetting(s.value)); }}>Edit</button>}</td>
            </tr>
          ))}</tbody>
        </table>
      </section>
      <section aria-label="History">
        <h2>History</h2>
        {hist.length === 0 ? <p className="muted small">No changes yet.</p> : (
          <table className="admin-table"><thead><tr><th>When</th><th>Key</th><th>Change</th><th>Who</th><th>Reason</th><th /></tr></thead>
            <tbody>{hist.map((h) => <HistoryRow key={h.id} h={h} fail={fail} ok={ok} onDone={load} />)}</tbody>
          </table>
        )}
      </section>
    </>
  );
}

function HistoryRow({ h, fail, ok, onDone }: P & { h: AdminHistory; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <tr>
      <td>{ago(h.created)}</td><td><code>{h.key}</code></td>
      <td>{showSetting(h.old)} → {showSetting(h.new)}</td><td>{h.actor_email}</td><td>{h.reason}</td>
      <td>{open ? <ReasonForm label={`Back to ${showSetting(h.old)}`} onCancel={() => setOpen(false)}
        onSubmit={(r) => admin.rollback(h.id, r).then(() => { setOpen(false); ok(); onDone(); }, fail)} />
        : <button className="ghost" onClick={() => setOpen(true)}>Roll back</button>}</td>
    </tr>
  );
}
