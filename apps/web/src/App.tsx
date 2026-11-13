import { useCallback, useEffect, useRef, useState } from "react";
import { api, AuthError, type ConnStatus, type SignupMode, getToken, setToken, subscribe } from "./api";
import { Chat, Composer, errorText, type Send } from "./Chat";
import { IconCheck, IconChevron, IconCompose, IconEye, IconFile, IconEyeOff, IconApps, IconLogout, IconMemory, IconMenu, IconMoon, IconSidebar, IconSun, IconTrash } from "./icons";
import { PixelAgent } from "./PixelAgent";
import { Mascot3D } from "./Mascot3D";
import { requestLocation, saveLocation, sharedLocation } from "./location";
import { Files } from "./Files";
import { Memory } from "./Memory";
import { Apps } from "./Apps";
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
      <h1>Simp</h1>
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
  { text: "What's the weather tomorrow?", icon: <IconSun size={16} /> },
  { text: "Summarize a file for me", icon: <IconFile size={16} /> },
  { text: "Help me plan my week", icon: <IconCheck size={16} /> },
];

const isConnHash = () => /^#(crafts|apps|connections)\b/.test(location.hash);  // #connections: older OAuth return
const hashSid = () => (isConnHash() ? "" : location.hash.slice(1));

function Main({ onLogout, onTheme, theme }: { onLogout: () => void; onTheme: () => void; theme: string }) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loaded, setLoaded] = useState(false);  // first sessions fetch finished (ok or not)
  const [drawer, setDrawer] = useState(false);  // mobile sidebar open
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("simp.sidebar") === "0"; } catch { return false; } });
  const [desktop, setDesktop] = useState(() => matchMedia("(min-width: 768px)").matches);
  useEffect(() => {
    const m = matchMedia("(min-width: 768px)"), on = () => setDesktop(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  const rail = collapsed && desktop;  // the collapsed rail only exists on desktop; mobile always uses the drawer
  const [profiles, setProfiles] = useState<string[]>([]);
  const [models, setModels] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState("");
  const [sid, setSid] = useState(hashSid);
  const [state, setState] = useState(initialState);
  const [conn, setConn] = useState<ConnStatus>("connecting");
  const [showFiles, setShowFiles] = useState(false);
  const [filesFocus, setFilesFocus] = useState<string>();
  const [confirm, setConfirm] = useState("");  // session id whose delete button was clicked once
  // A session is being created (hero composer). The hero composer is disabled meanwhile:
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
  // Overlapping refreshes (event-driven + after create/delete) can resolve out of order; keep only the newest.
  const refreshSeq = useRef(0);
  const refresh = useCallback(() => {
    const n = ++refreshSeq.current;
    return api.sessions().then((l) => { if (n === refreshSeq.current) setSessions(l); }).catch(guard).finally(() => setLoaded(true));
  }, [guard]);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);
  // Memory / Apps page (only when no session is picked); "#apps?..." / "#connections?..." is the OAuth return
  const [page, setPage] = useState<"" | "memory" | "apps">(() => (isConnHash() ? "apps" : ""));
  const pick = (id: string) => { setSid(id); setPage(""); setDrawer(false); };
  const open = (p: "memory" | "apps") => { pick(""); setPage(p); };

  useEffect(() => {
    refresh();
    api.profiles().then((p) => { setProfiles(p); setProfile(p[0] ?? ""); }).catch(() => {});
    api.models().then(setModels).catch(() => {});
  }, [refresh]);

  // Follow hash changes (pasted deep link, back/forward, same-document navigation to /#id).
  useEffect(() => {
    const onHash = () => { if (isConnHash()) setPage("apps"); setSid(hashSid()); };
    window.addEventListener("hashchange", onHash);
    onHash();  // the hash may have changed between the first render and this listener
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const lastSid = useRef(sid);
  useEffect(() => {
    // write the hash only when the app itself changed sid, never with a stale value on mount
    if (sid !== lastSid.current && location.hash.slice(1) !== sid) location.hash = sid;
    lastSid.current = sid;
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
  const [first, setFirst] = useState<{ sid: string; text: string } | null>(null);
  const queued = useRef<File[]>([]);
  const start: Send = async (c) => {
    try {
      const id = await create();
      if (!id) return;
      if (c.type === "prompt") setFirst({ sid: id, text: c.text });  // show it at once, before the server echoes it
      const files = queued.current.splice(0);  // files picked on the home screen go up before the prompt
      for (const f of files) await api.upload(id, f.name, f);
      await api.command(id, c);
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
      <aside className="sidebar" id="sidebar">
        <div className="side-top">
          <span className="brand">
            {rail ? (
              <button className="brand-mark expand" aria-label="Expand sidebar" title="Expand sidebar" onClick={toggleCollapsed}>
                <span className="face"><PixelAgent size={22} /></span><span className="toggle"><IconSidebar /></span>
              </button>
            ) : <span className="brand-mark"><PixelAgent size={22} /></span>}
            <span className="brand-name">Simp</span>
          </span>
          <button className="ghost icon only-desktop collapse" aria-label="Collapse sidebar" title="Collapse sidebar"
            onClick={toggleCollapsed}><IconSidebar /></button>
        </div>
        <button className={`ghost item new ${sid || page ? "" : "active"}`} onClick={() => pick("")} aria-current={sid || page ? undefined : "page"}
          aria-label={rail ? "New session" : undefined} title={rail ? "New session" : undefined}><IconCompose /><span className="label">New session</span></button>
        <button className={`ghost item new ${page === "memory" && !sid ? "active" : ""}`} onClick={() => open("memory")}
          aria-current={page === "memory" && !sid ? "page" : undefined} aria-label={rail ? "Memory" : undefined} title={rail ? "Memory" : undefined}>
          <IconMemory /><span className="label">Memory</span></button>
        <button className={`ghost item new ${page === "apps" && !sid ? "active" : ""}`} onClick={() => open("apps")}
          aria-current={page === "apps" && !sid ? "page" : undefined} aria-label={rail ? "Crafts" : undefined} title={rail ? "Crafts" : undefined}>
          <IconApps /><span className="label">Crafts</span></button>
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
            notify={notify} onToggleNotify={toggleNotify} menuButton={menu}
            firstPrompt={first?.sid === sid ? first.text : undefined} />
          {showFiles && <Files sid={sid} onError={guard} focus={filesFocus} onClose={() => setShowFiles(false)} />}
        </>
      ) : page === "memory" ? <Memory onError={guard} menuButton={menu} />
        : page === "apps" ? <Apps onError={guard} menuButton={menu} /> : (
        <main className="home">
          <header className="home-head">{menu}<span className="brand only-mobile"><PixelAgent size={22} />Simp</span></header>
          <div className="home-hero">
            <Mascot3D size={112} className="hero-face" working={creating} />
            <h1>How can I help today?</h1>
            <Composer busy={false} send={start} variant="hero" onQueueFiles={(fs) => queued.current.push(...fs)} disabled={creating} tools={profiles.length > 0 && (
              <ModelPicker value={profile} options={profiles} labels={models} onChange={setProfile} />
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
  const [shareLoc, setShareLoc] = useState(() => sharedLocation() !== null);
  const [locNote, setLocNote] = useState("");
  useEffect(() => { api.me().then((m) => setName(m.name)).catch(() => {}); }, []);
  const toggleLocation = () => {
    setLocNote("");
    if (shareLoc) { saveLocation(null); setShareLoc(false); return; }
    setShareLoc(true);
    requestLocation().then(saveLocation)
      .catch((e: Error) => { saveLocation(null); setShareLoc(false); setLocNote(e.message); });
  };
  const items = () => [...(root.current?.querySelectorAll<HTMLButtonElement>("[role^=menuitem]") ?? [])];
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
          <button role="menuitemcheckbox" aria-checked={shareLoc} tabIndex={-1} onClick={toggleLocation}
            title="Sends an approximate location (~10 km) with new sessions only, so the agent knows roughly where you are">
            <span aria-hidden="true">{shareLoc ? <IconCheck size={16} /> : <span style={{ width: 16, display: "inline-block" }} />}</span>
            <span>Share location</span>
          </button>
          {locNote && <div className="menu-note" role="status">{locNote}</div>}
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

/** Model picker: a themed popover listbox instead of the native <select> (whose menu follows the OS look). */
function ModelPicker({ value, options, labels, onChange }: {
  value: string; options: string[]; labels: Record<string, string>; onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const label = (p: string) => labels[p] ?? p;
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    (box.current?.querySelector('[aria-selected="true"]') as HTMLElement | null)?.focus();
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const pick = (p: string) => { onChange(p); setOpen(false); btn.current?.focus(); };
  const keys = (e: React.KeyboardEvent) => {
    const items = [...(box.current?.querySelectorAll<HTMLElement>("[role=option]") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); btn.current?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
  };
  return (
    <div className="model-pick" ref={box} onKeyDown={keys}>
      <button ref={btn} type="button" className="model-btn" aria-haspopup="listbox" aria-expanded={open} aria-label={`Model: ${label(value)}`}
        onClick={() => setOpen(!open)}>
        <span>{label(value)}</span><IconChevron size={14} className="chev" />
      </button>
      {open && (
        <ul className="model-menu" role="listbox" aria-label="Model">
          {options.map((p) => (
            <li key={p} role="option" aria-selected={p === value} tabIndex={-1}
              onClick={() => pick(p)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(p); } }}>
              <span>{label(p)}</span>{p === value && <IconCheck size={16} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
