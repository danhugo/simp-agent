import { useCallback, useEffect, useState } from "react";
import { api, AuthError, type Connection } from "./api";
import { errorText } from "./Chat";

const APPS: Record<string, { name: string; about: string }> = {
  google: { name: "Google", about: "Gmail, Drive and Calendar" },
};
const appName = (app: string) => APPS[app]?.name ?? app;

/** "#connections?ok=google" / "?error=..." from the OAuth callback -> a short message (then the hash is cleared). */
function oauthResult(): { ok: boolean; text: string } | null {
  const q = new URLSearchParams(location.hash.split("?")[1] ?? "");
  if (q.get("ok")) return { ok: true, text: `${appName(q.get("ok")!)} is connected.` };
  if (q.get("error")) return { ok: false, text: `Could not connect: ${q.get("error")}` };
  return null;
}

/** Apps the agent can use for you (OAuth): connect, reconnect, disconnect. */
export function Connections({ onError, menuButton }: { onError: (e: unknown) => void; menuButton: React.ReactNode }) {
  const [items, setItems] = useState<Connection[] | null>(null);
  const [note, setNote] = useState(oauthResult);
  const [confirm, setConfirm] = useState("");  // app whose Disconnect was clicked once
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setNote({ ok: false, text: errorText(e) }); }, [onError]);
  const load = useCallback(() => api.connections().then(setItems, fail), [fail]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (location.hash) history.replaceState(null, "", location.pathname + location.search); }, []);

  const connect = async (app: string) => {
    try { location.href = (await api.connect(app)).url; } catch (e) { fail(e); }
  };
  const disconnect = async (app: string) => {
    if (confirm !== app) return setConfirm(app);  // first click asks, second disconnects
    setConfirm("");
    try { await api.disconnect(app); setNote({ ok: true, text: `${appName(app)} is disconnected.` }); await load(); } catch (e) { fail(e); }
  };

  return (
    <main className="memory">
      <header className="home-head">{menuButton}<h1>Connections</h1></header>
      <div className="memory-body">
        <p className="muted">Apps the agent can use for you. It asks before it changes anything.</p>
        {note && <p className={note.ok ? "ok" : "error"} role="status">{note.text}</p>}
        {items === null ? <p className="muted">Loading…</p> : items.length === 0 ? <p className="muted">No apps are set up on this server.</p> : (
          <ul>
            {items.map((c) => (
              <li key={c.app} className="mem app-conn" aria-label={appName(c.app)}>
                <div>
                  <strong>{appName(c.app)}</strong>
                  <div className="muted small">{APPS[c.app]?.about}</div>
                  {c.status === "connected" && <div className="small">Connected as {c.account_email ?? "your account"}</div>}
                  {c.status === "needs_reconnect" && <div className="small warn">Access expired. Please reconnect.</div>}
                </div>
                {c.status === "connected" ? (
                  <button className={confirm === c.app ? "danger" : ""} onClick={() => disconnect(c.app)} onBlur={() => setConfirm("")}>
                    {confirm === c.app ? "Disconnect?" : "Disconnect"}</button>
                ) : (
                  <button className="primary" onClick={() => connect(c.app)}>{c.status === "needs_reconnect" ? "Reconnect" : "Connect"}</button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
