import { useCallback, useEffect, useState } from "react";
import { api, AuthError, type AppItem } from "./api";
import { errorText } from "./Chat";
import { IconPlus } from "./icons";

/** "#apps?ok=google" (or older "#connections?...") / "?error=..." from the OAuth callback -> a short message. */
function oauthResult(): { ok: boolean; text: string } | null {
  const q = new URLSearchParams(location.hash.split("?")[1] ?? "");
  if (q.get("ok")) return { ok: true, text: "Your account is connected." };
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
  calendar: <><rect x="4" y="5" width="16" height="15" rx="2" fill="#fff" stroke="#4285f4" strokeWidth="1.5" /><rect x="4" y="5" width="16" height="4" fill="#4285f4" /><text x="12" y="18" fontSize="8" textAnchor="middle" fill="#4285f4" fontFamily="sans-serif" fontWeight="700">31</text></>,
};
const AppIcon = ({ name }: { name: string }) => (
  <svg className="app-icon" viewBox="0 0 24 24" width="52" height="52" aria-hidden="true">{ICONS[name] ?? <><rect x="4" y="4" width="16" height="16" rx="4" fill="none" stroke="var(--muted)" strokeWidth="1.5" /><circle cx="12" cy="12" r="2.5" fill="var(--muted)" /></>}</svg>
);

/** Apps the agent can use for you: connect a provider once (Google), then turn each app on or off. */
export function Apps({ onError, menuButton }: { onError: (e: unknown) => void; menuButton: React.ReactNode }) {
  const [items, setItems] = useState<AppItem[] | null>(null);
  const [note, setNote] = useState(oauthResult);
  const [confirm, setConfirm] = useState("");  // provider whose Disconnect was clicked once
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setNote({ ok: false, text: errorText(e) }); }, [onError]);
  const load = useCallback(() => api.apps().then(setItems, fail), [fail]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (location.hash) history.replaceState(null, "", location.pathname + location.search); }, []);

  const connect = async (provider: string) => {
    try { location.href = (await api.connect(provider)).url; } catch (e) { fail(e); }
  };
  const toggle = async (a: AppItem) => {
    try { await api.setApp(a.app, !a.enabled); await load(); } catch (e) { fail(e); }
  };
  const disconnect = async (provider: string) => {
    if (confirm !== provider) return setConfirm(provider);  // first click asks, second disconnects
    setConfirm("");
    try { await api.disconnect(provider); setNote({ ok: true, text: "Your account is disconnected." }); await load(); } catch (e) { fail(e); }
  };

  const card = (a: AppItem) => (
    <li key={a.app} className="mem app-card" aria-label={a.label}>
      <AppIcon name={a.icon} />
      <div className="app-text">
        <strong>{a.label}</strong>
        <div className="muted small app-desc">{a.description}</div>
        {a.status === "needs_reconnect" && <div className="small warn">Access expired. Please reconnect.</div>}
      </div>
      {a.status === "needs_reconnect" ? <button className="primary" onClick={() => connect(a.provider!)}>Reconnect</button>
        : a.connected ? (
          <button className={`switch ${a.enabled ? "on" : ""}`} role="switch" aria-checked={a.enabled}
            aria-label={`Use ${a.label}`} onClick={() => toggle(a)}><span /></button>
        ) : (
          <button className="ghost icon add" aria-label={`Connect ${a.label}`} title="Connect" onClick={() => connect(a.provider!)}><IconPlus /></button>
        )}
    </li>
  );
  const section = (title: string, list: AppItem[]) => list.length > 0 && (
    <section aria-label={title}><h2>{title}</h2><ul className="app-grid">{list.map(card)}</ul></section>
  );
  // one account line per connected login provider (only Google today); no-auth apps (provider null) have none
  const accounts = [...new Map((items ?? []).filter((a) => a.provider && a.connected).map((a) => [a.provider!, a])).values()];

  return (
    <main className="memory">
      <header className="home-head">{menuButton}<h1>Apps</h1></header>
      <div className="memory-body">
        <p className="muted">Apps the agent can use for you. It asks before it changes anything.</p>
        {note && <p className={note.ok ? "ok" : "error"} role="status">{note.text}</p>}
        {items === null ? <p className="muted">Loading…</p> : items.length === 0 ? <p className="muted">No apps are set up on this server.</p> : <>
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
      </div>
    </main>
  );
}
