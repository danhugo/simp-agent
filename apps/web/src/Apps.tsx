import { useCallback, useEffect, useState } from "react";
import { api, AuthError, type AppDetail, type AppItem } from "./api";
import { errorText } from "./Chat";

/** "#crafts?error=..." (or older "#apps" / "#connections") from the OAuth callback -> an error message; success shows in the card. */
function oauthResult(): { ok: boolean; text: string } | null {
  const q = new URLSearchParams(location.hash.split("?")[1] ?? "");
  if (q.get("error")) return { ok: false, text: `Could not connect: ${q.get("error")}` };
  return null;
}

/** Small simple app marks (inline, no external images). */
const ICONS: Record<string, React.ReactNode> = {
  gmail: <><rect x="3" y="6" width="18" height="13" rx="2" fill="#fff" stroke="#c5221f" /><path d="M3.5 7l8.5 6.5L20.5 7" fill="none" stroke="#ea4335" strokeWidth="2" /></>,
  drive: <><path d="M9 4h6l6 10.5h-6z" fill="#fbbc04" /><path d="M9 4L3 14.5l3 5.5 6-10.5z" fill="#0f9d58" /><path d="M6 20h12l3-5.5H9z" fill="#4285f4" /></>,
  deepwiki: <><rect x="3" y="3" width="18" height="18" rx="4" fill="#1f6feb" /><path d="M8 7h4a5 5 0 010 10H8z" fill="none" stroke="#fff" strokeWidth="2" /></>,
  context7: <><rect x="3" y="3" width="18" height="18" rx="4" fill="#0e1116" /><path d="M8 7h8l-5 10" fill="none" stroke="#3fd28e" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></>,
  mslearn: <><rect x="3" y="3" width="8.5" height="8.5" fill="#f25022" /><rect x="12.5" y="3" width="8.5" height="8.5" fill="#7fba00" /><rect x="3" y="12.5" width="8.5" height="8.5" fill="#00a4ef" /><rect x="12.5" y="12.5" width="8.5" height="8.5" fill="#ffb900" /></>,
  cloudflare: <path d="M6 17h13.5a3 3 0 00-1.2-5.8 5.5 5.5 0 00-10.6-1.4A3.7 3.7 0 006 17z" fill="#f38020" />,
  aws: <><rect x="3" y="3" width="18" height="18" rx="4" fill="#232f3e" /><path d="M7 15.5c3 1.8 7 1.8 10 0" fill="none" stroke="#ff9900" strokeWidth="1.8" strokeLinecap="round" /><text x="12" y="12.5" fontSize="6.5" textAnchor="middle" fill="#fff" fontFamily="sans-serif" fontWeight="700">aws</text></>,
  github: <path fill="var(--text)" d="M12 .3a12 12 0 00-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 016 0C17.3 4.7 18.3 5 18.3 5c.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0012 .3" transform="translate(1.2 1.2) scale(.9)" />,
  calendar: <><rect x="4" y="5" width="16" height="15" rx="2" fill="#fff" stroke="#4285f4" strokeWidth="1.5" /><rect x="4" y="5" width="16" height="4" fill="#4285f4" /><text x="12" y="18" fontSize="8" textAnchor="middle" fill="#4285f4" fontFamily="sans-serif" fontWeight="700">31</text></>,
};
const AppIcon = ({ name }: { name: string }) => (
  <svg className="app-icon" viewBox="0 0 24 24" width="52" height="52" aria-hidden="true">{ICONS[name] ?? <><rect x="4" y="4" width="16" height="16" rx="4" fill="none" stroke="var(--muted)" strokeWidth="1.5" /><circle cx="12" cy="12" r="2.5" fill="var(--muted)" /></>}</svg>
);

/** Crafts page, Portals tab: apps the agent can use for you: connect a provider once (Google), then turn each app on or off. */
export function Apps({ onError, menuButton }: { onError: (e: unknown) => void; menuButton: React.ReactNode }) {
  const [items, setItems] = useState<AppItem[] | null>(null);
  const [note, setNote] = useState(oauthResult);
  const [confirm, setConfirm] = useState("");  // provider whose Disconnect was clicked once
  const [tokenFor, setTokenFor] = useState("");  // app whose "paste a token" form is open
  const [tab, setTab] = useState<"Portals" | "Skills">("Portals");
  const [tokenErr, setTokenErr] = useState("");
  const [detail, setDetail] = useState("");  // app whose detail page is open
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setNote({ ok: false, text: errorText(e) }); }, [onError]);
  const load = useCallback(() => api.apps().then(setItems, fail), [fail]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (location.hash) history.replaceState(null, "", location.pathname + location.search); }, []);

  const connect = async (app: string) => {
    try { location.href = (await api.connect(app)).url; } catch (e) { fail(e); }
  };
  const toggle = async (a: AppItem) => {
    try { await api.setApp(a.app, !a.enabled); await load(); } catch (e) { fail(e); }
  };
  const openToken = (app: string) => { setTokenFor(app); setTokenErr(""); };
  const saveToken = async (e: React.FormEvent<HTMLFormElement>, a: AppItem) => {
    e.preventDefault();
    const input = e.currentTarget.elements.namedItem("token") as HTMLInputElement;
    try {
      await api.saveToken(a.provider!, input.value.trim());
      input.value = "";  // never keep the token around
      setTokenFor(""); setNote({ ok: true, text: `${a.label} is connected.` }); await load();
    } catch (err) { onError(err); input.value = ""; setTokenErr(errorText(err)); }
  };
  const disconnect = async (linkId: string) => {
    if (confirm !== linkId) return setConfirm(linkId);  // first click asks, second disconnects
    setConfirm("");
    try { await api.disconnect(linkId); setNote({ ok: true, text: "Your account is disconnected." }); await load(); } catch (e) { fail(e); }
  };

  const tokenForm = (a: AppItem) => (
    <form className="token-form" onSubmit={(e) => saveToken(e, a)}>
      <input name="token" type="password" required autoFocus autoComplete="off" placeholder="Paste your token" aria-label={`${a.label} token`}
        aria-invalid={!!tokenErr} aria-describedby={tokenErr ? `${a.app}-token-err` : undefined} />
      {tokenErr && <div id={`${a.app}-token-err`} className="small error" role="alert">{tokenErr}</div>}
      {a.token_help_url && <a className="small" href={a.token_help_url} target="_blank" rel="noopener noreferrer">How to get a token</a>}
      <div className="token-actions">
        <button type="button" className="ghost" onClick={() => setTokenFor("")}>Cancel</button>
        <button className="primary">Save</button>
      </div>
    </form>
  );
  const open = (a: AppItem) => (e: React.MouseEvent) => { if (!(e.target as HTMLElement).closest("button:not(.app-open), label")) setDetail(a.app); };
  const sw = (a: AppItem, label?: string) => (
    <label className="sw">
      <button className={`switch ${a.enabled ? "on" : ""}`} role="switch" aria-checked={a.enabled} aria-label={`Use ${a.label}`} onClick={() => toggle(a)}><span /></button>
      {label}
    </label>
  );
  const warn = (a: AppItem) => a.status === "needs_reconnect" && <div className="small warn">{a.auth === "token" ? "Token stopped working. Please update it." : "Access expired. Please reconnect."}</div>;
  const fix = (a: AppItem) => <button className="primary small" onClick={() => a.auth === "token" ? openToken(a.app) : connect(a.app)}>{a.auth === "token" ? "Update token" : "Reconnect"}</button>;
  // Connected: one row per app, the account it uses, a labeled switch and Manage.
  const row = (a: AppItem) => {
    const acc = a.accounts ?? [];
    return (
      <li key={a.app} className="app-row" aria-label={a.label} onClick={open(a)}>
        <AppIcon name={a.icon} />
        <div className="app-text">
          <strong>{a.label}</strong>
          <div className="muted small">{acc[0]?.email ?? a.description}{acc.length > 1 && <span className="more">+{acc.length - 1} account{acc.length > 2 ? "s" : ""}</span>}</div>
          {warn(a)}
        </div>
        {a.status === "needs_reconnect" ? fix(a) : sw(a, "Use in chats")}
        <button className="ghost small app-open" aria-label={`${a.label} details`} onClick={() => setDetail(a.app)}>Manage</button>
      </li>
    );
  };
  // Available: a compact tile with one plain action.
  const tile = (a: AppItem) => tokenFor === a.app ? (
    <li key={a.app} className="app-tile editing" aria-label={a.label}><strong>{a.label}</strong>{tokenForm(a)}</li>
  ) : (
    <li key={a.app} className="app-tile" aria-label={a.label} onClick={open(a)}>
      <AppIcon name={a.icon} />
      <div className="app-text"><strong>{a.label}</strong><div className="muted small app-desc">{a.description}</div>{warn(a)}</div>
      {a.status === "needs_reconnect" ? fix(a)
        : a.connected || !a.auth ? sw(a)
        : <button className="ghost small" aria-label={`Connect ${a.label}`} onClick={() => a.auth === "token" ? openToken(a.app) : connect(a.app)}>{a.auth === "token" ? "Add token" : "Connect"}</button>}
    </li>
  );
  const section = (title: string, list: AppItem[], on: boolean) => list.length > 0 && (
    <section aria-label={title}><h2>{title}</h2>
      {on ? <ul className="app-rows">{list.map(row)}</ul> : <ul className="app-tiles">{list.map(tile)}</ul>}
    </section>
  );
  if (detail) return <Detail app={detail} onBack={() => { setDetail(""); load(); }} fail={fail} menuButton={menuButton} />;

  return (
    <main className="memory">
      <header className="home-head">{menuButton}<h1>Crafts</h1></header>
      <div className="memory-body">
        <div className="tabs" role="tablist">
          {(["Portals", "Skills"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className="tab" onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>
        {tab === "Skills" ? <p className="muted">Skills are coming soon.</p> : <>
        {note && <p className={note.ok ? "ok" : "error"} role="status">{note.text}</p>}
        {items === null ? <p className="muted">Loading…</p> : items.length === 0 ? <p className="muted">No portals are set up on this server.</p> : <>
          {section("Connected", items.filter((a) => a.enabled), true)}
          {section("Available", items.filter((a) => !a.enabled), false)}
        </>}
        </>}
      </div>
    </main>
  );
}

const day = (t: number) => new Date(t * 1000).toLocaleDateString();

/** Portal detail page: its accounts, scopes, tools, MCP URL and recent calls. */
function Detail({ app, onBack, fail, menuButton }: { app: string; onBack: () => void; fail: (e: unknown) => void; menuButton: React.ReactNode }) {
  const [d, setD] = useState<AppDetail | null>(null);
  const [confirm, setConfirm] = useState("");
  const load = useCallback(() => api.appDetail(app).then(setD, fail), [app, fail]);
  useEffect(() => { load(); }, [load]);
  const add = async () => { try { location.href = (await api.connect(app)).url; } catch (e) { fail(e); } };
  const disconnect = async (linkId: string) => {
    if (confirm !== linkId) return setConfirm(linkId);
    setConfirm("");
    try { await api.disconnect(linkId); await load(); } catch (e) { fail(e); }
  };
  const scopeName = (u: string) => u.replace(/^https:\/\/www\.googleapis\.com\/auth\//, "").replace(/^https?:\/\//, "");
  const [copied, setCopied] = useState(false);
  const copyUrl = async () => { try { await navigator.clipboard.writeText(d?.url ?? ""); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ } };
  return (
    <main className="memory">
      <header className="home-head">{menuButton}<button className="ghost" onClick={onBack}>← Portals</button></header>
      <div className="memory-body app-detail">
        {d === null ? <p className="muted">Loading…</p> : <>
          <div className="detail-hero">
            <AppIcon name={d.icon} />
            <div>
              <h1>{d.label}</h1>
              <p className="muted">{d.description}</p>
            </div>
            <span className={`pill ${d.enabled ? "on" : ""}`}>{d.enabled ? "In use" : "Off"}</span>
          </div>
          {d.provider && <section className="detail-card" aria-label="Accounts">
            <div className="card-head"><h2>Accounts</h2>
              {d.auth === "oauth" && <button className="ghost small" onClick={add}>+ Add account</button>}</div>
            {(d.accounts ?? []).length === 0 && <p className="muted small">No account connected.</p>}
            <ul className="account-list">{(d.accounts ?? []).map((x, i) => (
              <li key={x.link_id}>
                <span className="avatar" aria-hidden="true">{(x.email ?? "?").slice(0, 1).toUpperCase()}</span>
                <span className="account-main">
                  <span className="account-email">{x.email ?? "account"}{i === 0 && <span className="pill small">Default</span>}</span>
                  <span className={`small ${x.status === "ok" ? "muted" : "warn"}`}>{x.status === "ok" ? `Connected since ${day(x.created)}` : "Needs reconnect"}</span>
                </span>
                <button className={`ghost small ${confirm === x.link_id ? "danger" : ""}`} onClick={() => disconnect(x.link_id)}
                  onBlur={() => setConfirm("")}>{confirm === x.link_id ? "Disconnect?" : "Disconnect"}</button>
              </li>))}
            </ul>
          </section>}
          {d.scopes.length > 0 && <section className="detail-card" aria-label="Scopes"><h2>Granted scopes</h2>
            <div className="chips">{d.scopes.map((s) => <code key={s} className="chip-code" title={s}>{scopeName(s)}</code>)}</div></section>}
          <section className="detail-card" aria-label="Tools"><h2>Tools</h2>
            {d.tools.length === 0 ? <p className="muted small">Tools show here after a chat uses this portal.</p>
              : <ul className="tool-list">{d.tools.map((t) => (
                <li key={t.name}><code>{t.name}</code><span className={`pill small ${t.needs_approval ? "warn" : ""}`}>{t.needs_approval ? "Needs approval" : "Auto"}</span></li>))}</ul>}
          </section>
          {d.url && <section className="detail-card" aria-label="MCP URL"><h2>MCP URL</h2>
            <div className="url-row"><code>{d.url}</code><button className="ghost small" onClick={copyUrl}>{copied ? "Copied" : "Copy"}</button></div></section>}
          <section className="detail-card" aria-label="Recent calls"><h2>Recent calls</h2>
            {d.calls.length === 0 ? <p className="muted small">No calls yet.</p>
              : <table className="detail-table"><thead><tr><th>Time</th><th>Tool</th><th>Account</th><th>Result</th></tr></thead>
                <tbody>{d.calls.map((c, i) => (
                  <tr key={i}><td className="muted">{new Date(c.at * 1000).toLocaleString()}</td><td><code>{c.tool}</code></td><td>{c.account ?? "-"}</td>
                    <td><span className={`pill small ${c.ok ? "on" : "err"}`}>{c.ok ? "OK" : "Failed"}</span></td></tr>))}</tbody></table>}
          </section>
        </>}
      </div>
    </main>
  );
}
