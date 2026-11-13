import { useCallback, useEffect, useState } from "react";
import { api, AuthError, type AppItem } from "./api";
import { errorText } from "./Chat";
import { IconPlus } from "./icons";

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
  const disconnect = async (provider: string) => {
    if (confirm !== provider) return setConfirm(provider);  // first click asks, second disconnects
    setConfirm("");
    try { await api.disconnect(provider); setNote({ ok: true, text: "Your account is disconnected." }); await load(); } catch (e) { fail(e); }
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
  const card = (a: AppItem) => tokenFor === a.app ? (
    <li key={a.app} className="mem app-card editing" aria-label={a.label}>
      <strong>{a.label}</strong>
      {tokenForm(a)}
    </li>
  ) : a.auth === "token" ? (
    <li key={a.app} className="mem app-card" aria-label={a.label}>
      <AppIcon name={a.icon} />
      <div className="app-text">
        <strong>{a.label}</strong>
        <div className="muted small app-desc">{a.description}</div>
        {a.status === "needs_reconnect" && <div className="small warn">Token stopped working. Please update it.</div>}
      </div>
      {a.status === "needs_reconnect" ? <button className="primary" onClick={() => openToken(a.app)}>Update token</button>
        : a.connected ? (
          <div className="token-on">
            <button className={`switch ${a.enabled ? "on" : ""}`} role="switch" aria-checked={a.enabled}
              aria-label={`Use ${a.label}`} onClick={() => toggle(a)}><span /></button>
            <button className={`ghost small ${confirm === a.provider ? "danger" : ""}`} onClick={() => disconnect(a.provider!)}
              onBlur={() => setConfirm("")}>{confirm === a.provider ? "Disconnect?" : "Disconnect"}</button>
          </div>
        ) : (
          <button className="ghost icon add" aria-label={`Connect ${a.label}`} title="Connect" onClick={() => openToken(a.app)}><IconPlus /></button>
        )}
    </li>
  ) : (
    <li key={a.app} className="mem app-card" aria-label={a.label}>
      <AppIcon name={a.icon} />
      <div className="app-text">
        <strong>{a.label}</strong>
        <div className="muted small app-desc">{a.description}</div>
        {a.status === "needs_reconnect" && <div className="small warn">Access expired. Please reconnect.</div>}
      </div>
      {a.status === "needs_reconnect" ? <button className="primary" onClick={() => connect(a.app)}>Reconnect</button>
        : a.connected ? (
          <button className={`switch ${a.enabled ? "on" : ""}`} role="switch" aria-checked={a.enabled}
            aria-label={`Use ${a.label}`} onClick={() => toggle(a)}><span /></button>
        ) : (
          <button className="ghost icon add" aria-label={`Connect ${a.label}`} title="Connect" onClick={() => connect(a.app)}><IconPlus /></button>
        )}
    </li>
  );
  const section = (title: string, list: AppItem[]) => list.length > 0 && (
    <section aria-label={title}><h2>{title}</h2><ul className="app-grid">{list.map(card)}</ul></section>
  );
  // one account line per connected login provider (only Google today); no-auth apps (provider null) have none
  const accounts = [...new Map((items ?? []).filter((a) => a.provider && a.connected && a.auth !== "token").map((a) => [a.provider!, a])).values()];

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
          {section("Connected", items.filter((a) => a.enabled))}
          {section("Available", items.filter((a) => !a.enabled))}
          {accounts.map((a) => (
            <p key={a.provider} className="muted small account-line">
              <span>{a.provider === "google" ? "Google" : a.provider} account: {a.email ?? "connected"}</span>
              <button className={`ghost ${confirm === a.provider ? "danger" : ""}`} onClick={() => disconnect(a.provider!)}
                onBlur={() => setConfirm("")}>{confirm === a.provider ? "Disconnect?" : "Disconnect"}</button>
            </p>
          ))}
        </>}
        </>}
      </div>
    </main>
  );
}
