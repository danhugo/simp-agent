import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { admin, api, AuthError, type ConnStatus, getToken, setToken, subscribe } from "./api";
import { Chat, Composer, type Send, writtenFile } from "./Chat";
import { IconCalendar, IconChart, IconCheck, IconChevron, IconCompose, IconFile, IconSearch, IconApps, IconLogout, IconMemory, IconMenu, IconPersona, IconMoon, IconSidebar, IconSun, IconTrash } from "./icons";
import { PixelAgent } from "./PixelAgent";
import { Mascot3D } from "./Mascot3D";
import { requestLocation, saveLocation, sharedLocation } from "./location";
import { Files } from "./Files";
import { Preview } from "./Preview";
import { Memory } from "./Memory";
import { Admin } from "./Admin";
import { Apps } from "./Apps";
import { Persona, loadSavedSkin } from "./Persona";
import type { SessionInfo } from "./protocol.gen";
import { initialState, reduce, type ServerEvent } from "./state";

export default function App() {
  const [token, setTok] = useState(() => {
    // after Google sign-in the server redirects to /#login=<token>: keep it, then clean the URL
    const m = location.hash.match(/^#login=(.+)$/);
    if (m) { setToken(m[1]); history.replaceState(null, "", location.pathname + location.search); }
    return getToken();
  });
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
  return token ? <Main onLogout={logout} onTheme={toggle} theme={theme} /> : <Login />;
}

function Login() {
  return (
    <div className="login-page">
    <form className="login" action="/api/auth/google/start" method="get">
      <PixelAgent size={56} className="logo" />
      <h1>Simp</h1>
      <p className="muted sub">Welcome.</p>
      <button className="primary">Sign in with Google</button>
    </form>
    </div>
  );
}

// Each one works with no extra context; "fill" is what goes into the box (some end open, for you to finish).
const SUGGESTIONS = [
  // shows the agent's reach: it searches the web, runs code in its own computer and hands back a file
  { text: "Chart real data", fill: "Find recent data and draw a chart of: ", icon: <IconChart size={16} /> },
  { text: "Research a topic", fill: "Find reliable sources and give me a short summary on: ", icon: <IconSearch size={16} /> },
  { text: "Help me plan my week", fill: "Help me plan my week. My main goals are: ", icon: <IconCalendar size={16} /> },
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
  const [profiles, setProfiles] = useState<string[]>([]);
  const [models, setModels] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState("");
  const [sid, setSid] = useState(hashSid);
  const [state, setState] = useState(initialState);
  const [conn, setConn] = useState<ConnStatus>("connecting");
  const [showFiles, setShowFiles] = useState(false);
  const [filesFocus, setFilesFocus] = useState<string>();
  const [preview, setPreview] = useState<string>();
  useEffect(() => setPreview(undefined), [sid]);
  useEffect(() => { if (!preview) setPinOpen(false); }, [preview]);
  // how many times the chat shows the agent wrote the previewed file: each new write reloads the preview
  const writes = preview ? state.items.flatMap((i) => (i.kind === "assistant" ? i.msg.tool_calls : []))
    .filter((c) => writtenFile(c, state.results[c.id]) === preview).length : 0;
  const [confirm, setConfirm] = useState("");  // session id whose delete button was clicked once
  // A session is being created (hero composer). The hero composer is disabled meanwhile:
  // text typed into it would be lost when the chat replaces it, and Enter would create a second session.
  const [prefill, setPrefill] = useState<{ text: string; n: number }>();  // a picked suggestion goes into the box to edit
  const [creating, setCreating] = useState(false);
  const [hello, setHello] = useState(true);  // one happy hop when the new-chat screen opens
  useEffect(() => { if (sid) return; setHello(true); const t = setTimeout(() => setHello(false), 1200); return () => clearTimeout(t); }, [sid]);
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
  // a preview needs the room: the sidebar folds while it is open, unless the user opens it again (not saved)
  const [pinOpen, setPinOpen] = useState(false);
  const folded = preview ? !pinOpen : collapsed;
  const rail = folded && desktop;  // the collapsed rail only exists on desktop; mobile always uses the drawer
  const toggleCollapsed = () => {
    if (preview) return setPinOpen(!pinOpen);  // during a preview: open/fold for this preview only, nothing saved
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
  // Memory / Apps page (only when no session is picked); "#crafts?..." (aliases "#apps", "#connections") is the OAuth return
  const [page, setPage] = useState<"" | "memory" | "apps" | "persona" | "admin">(() => (isConnHash() ? "apps" : ""));
  const pick = (id: string) => { setSid(id); setPage(""); setDrawer(false); };
  const open = (p: "memory" | "apps" | "persona" | "admin") => { pick(""); setPage(p); };

  useEffect(() => {
    refresh();
    api.profiles().then((p) => { setProfiles(p); setProfile(p[0] ?? ""); }).catch(() => {});
    api.models().then(setModels).catch(() => {});
    loadSavedSkin();
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
        alertUser(ref.current.title || "New chat", ev.state, notifyRef.current);
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
    <div className={`app ${drawer ? "drawer" : ""} ${folded ? "collapsed" : ""}`}>
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
        <button className={`ghost item new ${page === "persona" && !sid ? "active" : ""}`} onClick={() => open("persona")}
          aria-current={page === "persona" && !sid ? "page" : undefined} aria-label={rail ? "Persona" : undefined} title={rail ? "Persona" : undefined}>
          <IconPersona /><span className="label">Persona</span></button>
        <nav aria-label="Sessions">
          <h2 className="section-label">Recent</h2>
          {sessions.map((s) => (
            <div key={s.id} className={`session-row ${s.id === sid ? "active" : ""}`}>
              <button className={`session ${s.id === sid ? "active" : ""}`} onClick={() => pick(s.id)}
                aria-current={s.id === sid ? "page" : undefined}>
                <span className="title">{chatName(s)}</span>
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
          <AccountMenu theme={theme} onTheme={onTheme} onLogout={onLogout} onAdmin={() => open("admin")} />
        </div>
      </aside>
      {sid ? (
        <>
          <Chat sid={sid} created={sessions.find((x) => x.id === sid)?.created} state={state} conn={conn} onError={guard} onToggleFiles={() => { setFilesFocus(undefined); setShowFiles(!showFiles); }} filesOpen={showFiles}
            onOpenFile={(p) => { setFilesFocus(p); setShowFiles(true); }} onPreviewFile={setPreview}
            notify={notify} onToggleNotify={toggleNotify} menuButton={menu}
            firstPrompt={first?.sid === sid ? first.text : undefined} />
          {preview ? (
            // one side panel: with a preview open, Files is a list inside it (opened from its header)
            <Preview sid={sid} path={preview} writes={writes} onError={guard} onClose={() => setPreview(undefined)}
              filesOpen={showFiles} onToggleFiles={() => setShowFiles(!showFiles)}>
              {showFiles && <Files sid={sid} onError={guard} focus={preview} onPreview={(p) => { setPreview(p); setShowFiles(false); }} onClose={() => setShowFiles(false)} />}
            </Preview>
          ) : showFiles && <Files sid={sid} onError={guard} focus={filesFocus} onPreview={(p) => { setPreview(p); setShowFiles(false); }} onClose={() => setShowFiles(false)} />}
        </>
      ) : page === "memory" ? <Memory onError={guard} menuButton={menu} />
        : page === "apps" ? <Apps onError={guard} menuButton={menu} />
        : page === "admin" ? <Admin onError={guard} menuButton={menu} />
        : page === "persona" ? <Persona onError={guard} menuButton={menu} profiles={profiles} models={models} /> : (
        <main className="home">
          <header className="home-head">{menu}<span className="brand only-mobile"><PixelAgent size={22} />Simp</span></header>
          <div className="home-hero">
            <Mascot3D size={112} className="hero-face" working={creating} mood={hello ? "done" : "idle"} />
            <h1>{greeting()}</h1>
            <Composer busy={false} send={start} variant="hero" prefill={prefill} onQueueFiles={(fs) => queued.current.push(...fs)} disabled={creating} tools={profiles.length > 0 && (
              <ModelPicker value={profile} options={profiles} labels={models} onChange={setProfile} />
            )} />
            <ul className="suggestions" aria-label="Suggestions">
              {SUGGESTIONS.map(({ text, fill, icon }) => (
                <li key={text}>
                  <button className="suggestion" disabled={creating} onClick={() => setPrefill((p) => ({ text: fill, n: (p?.n ?? 0) + 1 }))}>
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

const fmt = (x: number) => x.toLocaleString("en-US");
/** 3,580 -> 3.6k, 5,200,000 -> 5.2M; numbers under 1,000 stay exact */
const short = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const fmtShort = (x: number) => short.format(x).replace("K", "k");

/** Sidebar footer: avatar + username; opens a menu with the theme toggle and Sign out. */
function AccountMenu({ theme, onTheme, onLogout, onAdmin }: { theme: string; onTheme: () => void; onLogout: () => void; onAdmin: () => void }) {
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => { admin.me().then(setIsAdmin).catch(() => {}); }, []);  // the link only; the server checks every call
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [shareLoc, setShareLoc] = useState(() => sharedLocation() !== null);
  const [locNote, setLocNote] = useState("");
  const [points, setPoints] = useState<{ left: number; granted: number } | null>(null);
  useEffect(() => {  // points shown under the name: on load, every minute, and when the menu opens
    const load = () => api.usage().then((u) => setPoints(u.billing_enabled ? { left: u.points_balance ?? 0, granted: u.points_granted ?? 0 } : null)).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [open]);
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
          {isAdmin && <button role="menuitem" tabIndex={-1} onClick={() => { onAdmin(); close(); }}>
            <IconChart size={16} /><span>Admin</span></button>}
          <button role="menuitem" tabIndex={-1} onClick={() => api.logout().catch(() => {}).finally(onLogout)}>
            <IconLogout size={16} /><span>Sign out</span>
          </button>
        </div>
      )}
      <button ref={trigger} className="ghost item account-btn" aria-haspopup="menu" aria-expanded={open}
        aria-label={`Account${name ? `: ${name}` : ""}`} onClick={() => setOpen(!open)}>
        <span className="avatar" aria-hidden="true">{(name[0] ?? "?").toUpperCase()}</span>
        <span className="account-name">{name || "Account"}</span>
        {points && <span className={`account-pts ${points.left > 0 ? "" : "out"}`}>{points.left > 0 ? `${fmtShort(points.left)} pts` : "Out of points"}</span>}
      </button>
      {points && points.granted > 0 && (() => {
        const used = Math.min(1, Math.max(0, 1 - points.left / points.granted));
        return (
          <div className="credit-bar" role="meter" aria-label="Points used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(used * 100)}
            aria-valuetext={`${fmt(Math.max(0, points.left))} of ${fmt(points.granted)} points left`} title={`${fmt(Math.max(0, points.left))} of ${fmt(points.granted)} points left`}>
            <i className={used >= 1 ? "out" : used >= 0.8 ? "low" : ""} style={{ width: `${used * 100}%` }} />
          </div>
        );
      })()}
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
export function ModelPicker({ value, options, labels, onChange }: {
  value: string; options: string[]; labels: Record<string, string>; onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [up, setUp] = useState(false);
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
  // no room below the button (e.g. Persona's draw box) → open upward, before the first paint
  useLayoutEffect(() => {
    if (!open) return setUp(false);
    const b = btn.current!.getBoundingClientRect(), h = box.current!.querySelector("ul")!.offsetHeight + 6;
    setUp(b.bottom + h > innerHeight && b.top > innerHeight - b.bottom);
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
        <ul className={up ? "model-menu up" : "model-menu"} role="listbox" aria-label="Model">
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

/** A chat's name: its title, or "New chat 16/11 14:05" until the title arrives. */
export const chatName = (s: { title: string; created?: number }) =>
  s.title || `New chat ${s.created ? new Date(s.created * 1000).toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""}`.trim();

/** The new-chat headline, in Simp's voice, by time of day. */
export function greeting(h = new Date().getHours()) {
  if (h < 5) return "Still up? What's next?";
  if (h < 12) return "Morning! What are we making?";
  if (h < 18) return "Afternoon! What's on your mind?";
  return "Evening! What should we work on?";
}

