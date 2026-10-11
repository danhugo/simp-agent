import { useCallback, useEffect, useRef, useState } from "react";
import { api, AuthError, type ConnStatus, getToken, setToken, subscribe } from "./api";
import { Chat } from "./Chat";
import { Files } from "./Files";
import type { SessionInfo } from "./protocol.gen";
import { initialState, reduce, type ServerEvent } from "./state";

export default function App() {
  const [token, setTok] = useState(getToken());
  const [theme, setTheme] = useState(localStorage.getItem("simp.theme") ?? "light");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("simp.theme", theme);
  }, [theme]);
  const logout = useCallback(() => { setToken(""); setTok(""); }, []);
  const toggle = () => setTheme(theme === "dark" ? "light" : "dark");
  return token ? <Main onLogout={logout} onTheme={toggle} theme={theme} /> : <Login onLogin={setTok} />;
}

function Login({ onLogin }: { onLogin: (t: string) => void }) {
  const [signup, setSignup] = useState(false);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [value, setValue] = useState("");  // access token (from `simp-server seed`), instead of a password
  const [error, setError] = useState("");
  const useToken = !signup && !!value.trim();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const t = useToken ? value.trim()
        : signup ? await api.signup(name.trim(), password, code.trim()) : await api.login(name.trim(), password);
      setToken(t);
      await api.hello();
      await api.profiles(); // /api/hello needs no token; this checks it
      onLogin(t);
    } catch (err) {
      setToken("");
      setError(err instanceof AuthError ? "That token was not accepted." : err instanceof Error ? err.message : String(err));
    }
  };
  const swap = () => { setSignup(!signup); setError(""); };
  return (
    <form className="login" onSubmit={submit}>
      <h1>simp-agent</h1>
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Username" aria-label="Username"
        autoComplete="username" />
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password"
        aria-label="Password" autoComplete={signup ? "new-password" : "current-password"} />
      {signup ? (
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Invite code" aria-label="Invite code" />
      ) : (
        <>
          <p className="muted small">Or paste an access token (from <code>simp-server seed</code>):</p>
          <input type="password" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Token" aria-label="Token" />
        </>
      )}
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={!useToken && !(name.trim() && password && (!signup || code.trim()))}>
        {signup ? "Create account" : "Sign in"}
      </button>
      <button type="button" className="ghost" onClick={swap}>{signup ? "I have an account" : "Create account"}</button>
    </form>
  );
}

function Main({ onLogout, onTheme, theme }: { onLogout: () => void; onTheme: () => void; theme: string }) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [profiles, setProfiles] = useState<string[]>([]);
  const [profile, setProfile] = useState("");
  const [sid, setSid] = useState(() => location.hash.slice(1));
  const [state, setState] = useState(initialState);
  const [conn, setConn] = useState<ConnStatus>("connecting");
  const [showFiles, setShowFiles] = useState(false);
  const [confirm, setConfirm] = useState("");  // session id whose delete button was clicked once
  const ref = useRef(state);

  const guard = useCallback((e: unknown) => { if (e instanceof AuthError) onLogout(); else console.error(e); }, [onLogout]);
  const refresh = useCallback(() => api.sessions().then(setSessions).catch(guard), [guard]);

  useEffect(() => {
    refresh();
    api.profiles().then((p) => { setProfiles(p); setProfile(p[0] ?? ""); }).catch(() => {});
  }, [refresh]);

  useEffect(() => {
    location.hash = sid;
    ref.current = initialState();
    setState(ref.current);
    if (!sid) return;
    const apply = (ev: ServerEvent) => {
      ref.current = reduce(ref.current, ev);
      setState(ref.current);
      if (ev.type === "run_state" || ev.type === "snapshot") refresh();
    };
    return subscribe(sid, () => ref.current.lastSeq, apply, setConn, onLogout);
  }, [sid, refresh, onLogout]);

  const create = async () => {
    try {
      const s = await api.newSession(profile);
      await refresh();
      setSid(s.id);
    } catch (e) { guard(e); }
  };

  const remove = async (id: string) => {
    if (confirm !== id) return setConfirm(id);  // no native confirm(): first click asks, second deletes
    setConfirm("");
    try {
      await api.deleteSession(id);
      if (id === sid) setSid("");
      await refresh();
    } catch (e) { guard(e); }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">simp-agent</div>
        <div className="new">
          {profiles.length > 0 && (
            <select value={profile} onChange={(e) => setProfile(e.target.value)} aria-label="Profile">
              {profiles.map((p) => <option key={p}>{p}</option>)}
            </select>
          )}
          <button className="primary" onClick={create}>New session</button>
        </div>
        <nav>
          {sessions.map((s) => (
            <div key={s.id} className="session-row">
              <button className={`session ${s.id === sid ? "active" : ""}`} onClick={() => setSid(s.id)}>
                <span>{s.id}</span><Badge state={s.run_state} />
              </button>
              <button className="ghost del" aria-label="Delete session" onClick={() => remove(s.id)}
                onBlur={() => setConfirm("")}>{confirm === s.id ? "Delete?" : "×"}</button>
            </div>
          ))}
          {sessions.length === 0 && <p className="muted small">No sessions yet.</p>}
        </nav>
        <div className="foot">
          <button className="ghost" onClick={onTheme}>{theme === "dark" ? "Light" : "Dark"} theme</button>
          <button className="ghost" onClick={() => api.logout().catch(() => {}).finally(onLogout)}>Sign out</button>
        </div>
      </aside>
      {sid ? (
        <>
          <Chat sid={sid} state={state} conn={conn} onError={guard} onToggleFiles={() => setShowFiles(!showFiles)} />
          {showFiles && <Files sid={sid} onError={guard} />}
        </>
      ) : (
        <main className="empty muted">Create or pick a session to start.</main>
      )}
    </div>
  );
}

export function Badge({ state }: { state: string }) {
  return <span className={`badge ${state}`}>{state.replace("_", " ")}</span>;
}
