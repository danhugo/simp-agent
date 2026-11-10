import { useCallback, useEffect, useRef, useState } from "react";
import { api, AuthError, type ConnStatus, type SignupMode, getToken, setToken, subscribe } from "./api";
import { Chat, Composer, errorText, type Send } from "./Chat";
import { IconCheck, IconCompose, IconEye, IconFile, IconFolder, IconEyeOff, IconLogout, IconMenu, IconMoon, IconSidebar, IconSun, IconTrash } from "./icons";
import { PixelAgent } from "./PixelAgent";
import { Files } from "./Files";
import type { SessionInfo } from "./protocol.gen";
import { initialState, reduce, type ServerEvent } from "./state";

export default function App() {
  const [token, setTok] = useState(getToken());
  const [theme, setTheme] = useState(() => {
    try { const t = localStorage.getItem("simp.theme"); if (t) return t; } catch { /* storage blocked */ }
    return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const logout = useCallback(() => { setToken(""); setTok(""); }, []);
  const toggle = () => {
    const t = theme === "dark" ? "light" : "dark";
    setTheme(t);
    try { localStorage.setItem("simp.theme", t); } catch { /* storage blocked: keep it for this tab */ }
  };
  return token ? <Main onLogout={logout} onTheme={toggle} theme={theme} /> : <Login onLogin={setTok} />;
}

type Field = "name" | "password" | "code" | "token";
const FIELD_ID: Record<Field, string> = { name: "login-name", password: "login-password", code: "login-code", token: "login-token" };

function Login({ onLogin }: { onLogin: (t: string) => void }) {
  const [signup, setSignup] = useState(false);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [code, setCode] = useState("");
  const [value, setValue] = useState("");  // access token (from `simp-server seed`), instead of a password
  const [tokenMode, setTokenMode] = useState(false);  // hidden by default: username + password is the normal way in
  const [error, setError] = useState("");
  const [missing, setMissing] = useState<Partial<Record<Field, string>>>({});  // per-field "required" messages
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);  // ignore repeated submits while a request is in flight
  const [mode, setMode] = useState<SignupMode>("invite");
  useEffect(() => { api.signupMode().then(setMode); }, []);
  const invite = mode === "invite";
  const withToken = !signup && tokenMode;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busyRef.current) return;
    setError("");
    const req: [Field, string, string][] = withToken ? [["token", value.trim(), "Enter your access token."]] : [
      ["name", name.trim(), "Enter a username."],
      ["password", password, "Enter a password."],
      ...(signup && invite ? [["code", code.trim(), "Enter your invite code."] as [Field, string, string]] : []),
    ];
    const bad = Object.fromEntries(req.filter(([, v]) => !v).map(([f, , msg]) => [f, msg]));
    setMissing(bad);
    const first = req.find(([, v]) => !v);
    if (first) { document.getElementById(FIELD_ID[first[0]])?.focus(); return; }
    busyRef.current = true;
    setBusy(true);
    try {
      const t = withToken ? value.trim()
        : signup ? await api.signup(name.trim(), password, invite ? code.trim() : "") : await api.login(name.trim(), password);
      setToken(t);
      await api.hello();
      await api.profiles(); // /api/hello needs no token; this checks it
      onLogin(t);
    } catch (err) {
      setToken("");
      setError(err instanceof AuthError ? "That token was not accepted." : errorText(err));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  const reset = () => { setError(""); setMissing({}); };
  const swap = () => { setSignup(!signup); setTokenMode(false); reset(); };
  // label + input + optional hint / "required" message, wired with htmlFor/id and aria-describedby
  const field = (f: Field, label: string, input: (p: React.InputHTMLAttributes<HTMLInputElement>) => React.ReactNode,
    hint?: string) => {
    const id = FIELD_ID[f];
    const desc = [hint && `${id}-hint`, missing[f] && `${id}-err`].filter(Boolean).join(" ") || undefined;
    return (
      <div className="field">
        <label htmlFor={id}>{label}</label>
        {input({ id, "aria-invalid": missing[f] ? true : undefined, "aria-describedby": desc })}
        {hint && <p id={`${id}-hint`} className="muted small hint">{hint}</p>}
        {missing[f] && <p id={`${id}-err`} className="field-error small">{missing[f]}</p>}
      </div>
    );
  };
  const clear = (f: Field) => missing[f] && setMissing({ ...missing, [f]: undefined });
  return (
    <div className="login-page">
    <form className="login" onSubmit={submit} aria-busy={busy} noValidate>
      <PixelAgent size={56} className="logo" />
      <h1>simp-agent</h1>
      <p className="muted sub">{!signup ? "Welcome." : invite ? "Join with an invite code." : "Pick a username and a password."}</p>
      {withToken ? field("token", "Token", (p) =>
        <input {...p} autoFocus type="password" value={value} aria-label="Token" autoComplete="off"
          onChange={(e) => { setValue(e.target.value); clear("token"); }} />,
      ) : (
        <>
          {field("name", "Username", (p) =>
            <input {...p} autoFocus value={name} aria-label="Username" autoComplete="username" autoCapitalize="none"
              spellCheck={false} onChange={(e) => { setName(e.target.value); clear("name"); }} />,
            signup ? "2–32 letters, digits, _ or -" : undefined)}
          {field("password", "Password", (p) =>
            <div className="pw">
              <input {...p} type={showPw ? "text" : "password"} value={password} aria-label="Password"
                autoComplete={signup ? "new-password" : "current-password"}
                onChange={(e) => { setPassword(e.target.value); clear("password"); }} />
              <button type="button" className="icon reveal" aria-label={showPw ? "Hide password" : "Show password"}
                aria-pressed={showPw} onClick={() => setShowPw(!showPw)}>
                {showPw ? <IconEyeOff /> : <IconEye />}
              </button>
            </div>)}
          {signup && invite && field("code", "Invite code", (p) =>
            <input {...p} value={code} aria-label="Invite code" autoComplete="off" autoCapitalize="none" spellCheck={false}
              onChange={(e) => { setCode(e.target.value); clear("code"); }} />)}
        </>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy}>
        {busy && <span className="spinner" aria-hidden="true" />}
        {busy ? (signup ? "Creating account…" : "Signing in…") : signup ? "Create account" : "Sign in"}
      </button>
      {!signup && !tokenMode && <p className="muted small center">Forgot your password? Ask the admin to run <code>simp-server passwd</code>.</p>}
      {(signup || mode !== "closed") &&
        <p className="swap small">{signup ? "Already have an account? " : "No account yet? "}
          <button type="button" className="link" onClick={swap}>{signup ? "Sign in" : "Create account"}</button></p>}
      {!signup &&
        <button type="button" className="link muted small token-toggle" onClick={() => { setTokenMode(!tokenMode); reset(); }}>
          {tokenMode ? "Use username and password" : "Use an access token instead"}
        </button>}
    </form>
    </div>
  );
}

const SUGGESTIONS = [
  { text: "Explain this repo", icon: <IconFolder size={16} /> },
  { text: "Write a script", icon: <IconFile size={16} /> },
  { text: "Fix a failing test", icon: <IconCheck size={16} /> },
];

function Main({ onLogout, onTheme, theme }: { onLogout: () => void; onTheme: () => void; theme: string }) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loaded, setLoaded] = useState(false);  // first sessions fetch finished (ok or not)
  const [drawer, setDrawer] = useState(false);  // mobile sidebar open
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("simp.sidebar") === "0"; } catch { return false; } });
  const [profiles, setProfiles] = useState<string[]>([]);
  const [profile, setProfile] = useState("");
  const [sid, setSid] = useState(() => location.hash.slice(1));
  const [state, setState] = useState(initialState);
  const [conn, setConn] = useState<ConnStatus>("connecting");
  const [showFiles, setShowFiles] = useState(false);
  const [filesFocus, setFilesFocus] = useState<string>();
  const [confirm, setConfirm] = useState("");  // session id whose delete button was clicked once
  // A session is being created (New session button or hero composer). The hero composer is disabled meanwhile:
  // text typed into it would be lost when the chat replaces it, and Enter would create a second session.
  const [creating, setCreating] = useState(false);
  const creatingRef = useRef(false);
  const ref = useRef(state);
  const [notify, setNotify] = useState(() => { try { return localStorage.getItem("simp.notify") === "1"; } catch { return false; } });
  const notifyRef = useRef(notify);
  notifyRef.current = notify;
  const toggleNotify = async () => {
    let on = !notify;
    if (on && typeof Notification !== "undefined" && Notification.permission !== "granted") {
      on = (await Notification.requestPermission()) === "granted";
    }
    setNotify(on);
    try { localStorage.setItem("simp.notify", on ? "1" : "0"); } catch { /* storage blocked: keep it for this tab */ }
  };
  const toggleCollapsed = () => {
    const c = !collapsed;
    setCollapsed(c);
    try { localStorage.setItem("simp.sidebar", c ? "0" : "1"); } catch { /* storage blocked: keep it for this tab */ }
  };

  const guard = useCallback((e: unknown) => { if (e instanceof AuthError) onLogout(); else console.error(e); }, [onLogout]);
  const refresh = useCallback(() => api.sessions().then(setSessions).catch(guard).finally(() => setLoaded(true)), [guard]);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);
  const pick = (id: string) => { setSid(id); setDrawer(false); };

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
      if (ev.type === "run_state" || ev.type === "snapshot" || ev.type === "session_title") refresh();
      if (ev.type === "run_state" && ["waiting_approval", "idle", "error"].includes(ev.state)) {
        alertUser(ref.current.title || sid, ev.state, notifyRef.current);
      }
    };
    return subscribe(sid, () => ref.current.lastSeq, apply, setConn, onLogout);
  }, [sid, refresh, onLogout]);

  const create = async () => {
    if (creatingRef.current) return;
    creatingRef.current = true;
    setCreating(true);
    try {
      const s = await api.newSession(profile);
      await refresh();
      pick(s.id);
      return s.id;
    } catch (e) { guard(e); } finally { creatingRef.current = false; setCreating(false); }
  };

  /** Hero composer / suggestion chips: start a session with the chosen profile, then send the first command. */
  const start: Send = async (c) => {
    try {
      const id = await create();
      if (id) await api.command(id, c);
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

  const menu = (
    <button className="ghost icon only-mobile" aria-label="Menu" aria-expanded={drawer} aria-controls="sidebar"
      onClick={() => setDrawer(true)}><IconMenu /></button>
  );

  return (
    <div className={`app ${drawer ? "drawer" : ""} ${collapsed ? "collapsed" : ""}`}>
      {(drawer || (sid && showFiles)) && (
        <div className="backdrop" aria-hidden="true" onClick={() => (drawer ? setDrawer(false) : setShowFiles(false))} />
      )}
      {collapsed && (
        <button className="ghost icon reopen only-desktop" aria-label="Expand sidebar" title="Expand sidebar"
          onClick={toggleCollapsed}><IconSidebar /></button>
      )}
      <aside className="sidebar" id="sidebar">
        <div className="side-top">
          <span className="brand"><PixelAgent size={22} />simp-agent</span>
          <button className="ghost icon only-desktop" aria-label="Collapse sidebar" title="Collapse sidebar"
            onClick={toggleCollapsed}><IconSidebar /></button>
        </div>
        <button className={`ghost item new ${sid ? "" : "active"}`} onClick={create} aria-current={sid ? undefined : "page"}><IconCompose /><span>New session</span></button>
        <nav aria-label="Sessions">
          <h2 className="section-label">Recent</h2>
          {sessions.map((s) => (
            <div key={s.id} className={`session-row ${s.id === sid ? "active" : ""}`}>
              <button className={`session ${s.id === sid ? "active" : ""}`} onClick={() => pick(s.id)}
                aria-current={s.id === sid ? "page" : undefined}>
                <span className="title">{s.title || s.id}</span>
                {s.run_state !== "idle" && <Badge state={s.run_state} />}
              </button>
              <button className={`ghost del ${confirm === s.id ? "confirm" : "icon"}`} aria-label="Delete session"
                title="Delete session" onClick={() => remove(s.id)} onBlur={() => setConfirm("")}>
                {confirm === s.id ? "Delete?" : <IconTrash size={16} />}
              </button>
            </div>
          ))}
          {!loaded ? <p className="muted small pad">Loading…</p>
            : sessions.length === 0 && <p className="muted small pad">No sessions yet.</p>}
        </nav>
        <div className="foot">
          <AccountMenu theme={theme} onTheme={onTheme} onLogout={onLogout} />
        </div>
      </aside>
      {sid ? (
        <>
          <Chat sid={sid} state={state} conn={conn} onError={guard} onToggleFiles={() => { setFilesFocus(undefined); setShowFiles(!showFiles); }} filesOpen={showFiles}
            onOpenFile={(p) => { setFilesFocus(p); setShowFiles(true); }}
            notify={notify} onToggleNotify={toggleNotify} menuButton={menu} />
          {showFiles && <Files sid={sid} onError={guard} focus={filesFocus} onClose={() => setShowFiles(false)} />}
        </>
      ) : (
        <main className="home">
          <header className="home-head">{menu}<span className="brand only-mobile"><PixelAgent size={22} />simp-agent</span></header>
          <div className="home-hero">
            <h1>What should we build?</h1>
            <Composer busy={false} send={start} variant="hero" disabled={creating} tools={profiles.length > 0 && (
              <select className="profile-pick" value={profile} onChange={(e) => setProfile(e.target.value)} aria-label="Profile"
                title="Profile">
                {profiles.map((p) => <option key={p}>{p}</option>)}
              </select>
            )} />
            <ul className="suggestions" aria-label="Suggestions">
              {SUGGESTIONS.map(({ text, icon }) => (
                <li key={text}>
                  <button className="suggestion" disabled={creating} onClick={() => start({ type: "prompt", text })}>
                    {icon}<span>{text}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </main>
      )}
    </div>
  );
}

/** Sidebar footer: avatar + username; opens a menu with the theme toggle and Sign out. */
function AccountMenu({ theme, onTheme, onLogout }: { theme: string; onTheme: () => void; onLogout: () => void }) {
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => { api.me().then((m) => setName(m.name)).catch(() => {}); }, []);
  const items = () => [...(root.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? [])];
  useEffect(() => {
    if (!open) return;
    items()[0]?.focus();
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" && open) { e.stopPropagation(); close(); return; }
    if (!open || !["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const list = items();
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "Home" ? 0 : e.key === "End" ? list.length - 1
      : (i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length;
    list[next]?.focus();
  };
  return (
    <div className="account" ref={root} onKeyDown={onKey}
      onBlur={(e) => { if (open && !root.current?.contains(e.relatedTarget as Node)) setOpen(false); }}>
      {open && (
        <div className="menu up" role="menu" aria-label="Account">
          <button role="menuitem" tabIndex={-1} onClick={() => { onTheme(); close(); }}>
            {theme === "dark" ? <IconSun size={16} /> : <IconMoon size={16} />}<span>{theme === "dark" ? "Light" : "Dark"} theme</span>
          </button>
          <button role="menuitem" tabIndex={-1} onClick={() => api.logout().catch(() => {}).finally(onLogout)}>
            <IconLogout size={16} /><span>Sign out</span>
          </button>
        </div>
      )}
      <button ref={trigger} className="ghost item account-btn" aria-haspopup="menu" aria-expanded={open}
        aria-label={`Account${name ? `: ${name}` : ""}`} onClick={() => setOpen(!open)}>
        <span className="avatar" aria-hidden="true">{(name[0] ?? "?").toUpperCase()}</span>
        <span className="account-name">{name || "Account"}</span>
      </button>
    </div>
  );
}

export function Badge({ state }: { state: string }) {
  return <span className={`badge ${state}`}>{state.replace("_", " ")}</span>;
}

/** A system notification, only when the tab is hidden and the user turned it on. */
function alertUser(title: string, state: string, on: boolean) {
  if (!on || !document.hidden || typeof Notification === "undefined" || Notification.permission !== "granted") return;
  const body = state === "waiting_approval" ? "needs your approval" : state === "error" ? "run failed" : "run finished";
  try { new Notification(title, { body, tag: title }); } catch { /* some browsers only allow it from a service worker */ }
}
