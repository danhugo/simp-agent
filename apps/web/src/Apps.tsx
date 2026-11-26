import { IconChevron, IconDownload, IconPlus, IconRefresh, IconSearch, IconTrash, IconUpload } from "./icons";
import { useCallback, useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  BookOpen, Bug, ChartLine, Clapperboard, Contact, Database, FlaskConical, GitBranch, GitPullRequest, GraduationCap, Image, Languages,
  LayoutTemplate, Lightbulb, ListChecks, ListOrdered, Mail, Megaphone, NotebookPen, Palette, Plug, ScanText, ScrollText, ShieldCheck,
  Sigma, SwatchBook, TableProperties, Telescope,
} from "lucide-react";
import { api, AuthError, type AppDetail, type AppItem, type LibrarySkill, type SkillItem } from "./api";
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
  linear: <><rect x="3" y="3" width="18" height="18" rx="5" fill="#5e6ad2" /><path d="M6.5 13.5l4 4M6.2 10.8l7 7M7.5 8l8.5 8.5M10 6.3l7.7 7.7" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" /></>,
  notion: <><rect x="4" y="3" width="16" height="18" rx="3" fill="#fff" stroke="var(--text)" strokeWidth="1.5" /><path d="M9 16V8l6 8V8" fill="none" stroke="var(--text)" strokeWidth="1.6" /></>,
  sentry: <><rect x="3" y="3" width="18" height="18" rx="5" fill="#362d59" /><path d="M7 17h3a5 5 0 00-2.5-4.3L12 6l5.5 11h-2" fill="none" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round" /></>,
  atlassian: <><rect x="3" y="3" width="18" height="18" rx="5" fill="#0c66e4" /><path d="M9 11l-3 6h5zM12 6c-1.5 2.5-1.5 5 0 8l1.5 3H18z" fill="#fff" /></>,
  canva: <><circle cx="12" cy="12" r="9.5" fill="#00c4cc" /><path d="M15 9.5a3.5 3.5 0 100 5" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" /></>,
  deepwiki: <><rect x="3" y="3" width="18" height="18" rx="4" fill="#1f6feb" /><path d="M8 7h4a5 5 0 010 10H8z" fill="none" stroke="#fff" strokeWidth="2" /></>,
  context7: <><rect x="3" y="3" width="18" height="18" rx="4" fill="#0e1116" /><path d="M8 7h8l-5 10" fill="none" stroke="#3fd28e" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></>,
  mslearn: <><rect x="3" y="3" width="8.5" height="8.5" fill="#f25022" /><rect x="12.5" y="3" width="8.5" height="8.5" fill="#7fba00" /><rect x="3" y="12.5" width="8.5" height="8.5" fill="#00a4ef" /><rect x="12.5" y="12.5" width="8.5" height="8.5" fill="#ffb900" /></>,
  cloudflare: <path d="M6 17h13.5a3 3 0 00-1.2-5.8 5.5 5.5 0 00-10.6-1.4A3.7 3.7 0 006 17z" fill="#f38020" />,
  aws: <><rect x="3" y="3" width="18" height="18" rx="4" fill="#232f3e" /><path d="M7 15.5c3 1.8 7 1.8 10 0" fill="none" stroke="#ff9900" strokeWidth="1.8" strokeLinecap="round" /><text x="12" y="12.5" fontSize="6.5" textAnchor="middle" fill="#fff" fontFamily="sans-serif" fontWeight="700">aws</text></>,
  github: <path fill="var(--text)" d="M12 .3a12 12 0 00-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 016 0C17.3 4.7 18.3 5 18.3 5c.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0012 .3" transform="translate(1.2 1.2) scale(.9)" />,
  calendar: <><rect x="4" y="5" width="16" height="15" rx="2" fill="#fff" stroke="#4285f4" strokeWidth="1.5" /><rect x="4" y="5" width="16" height="4" fill="#4285f4" /><text x="12" y="18" fontSize="8" textAnchor="middle" fill="#4285f4" fontFamily="sans-serif" fontWeight="700">31</text></>,
};
const doc = (color: string, letter: string) => <><path d="M6 2.5h8.5L19 7v14a.5.5 0 01-.5.5h-12A.5.5 0 016 21z" fill="#fff" stroke={color} strokeWidth="1.3" /><path d="M14.5 2.5V7H19" fill="none" stroke={color} strokeWidth="1.3" /><rect x="3.5" y="10" width="11" height="8" rx="1.5" fill={color} /><text x="9" y="16.3" fontSize={letter.length > 1 ? 4.6 : 6.5} textAnchor="middle" fill="#fff" fontFamily="sans-serif" fontWeight="700">{letter}</text></>;
ICONS.pptx = doc("#c43e1c", "P");
ICONS.docx = doc("#185abd", "W");
ICONS.xlsx = doc("#107c41", "X");
ICONS.pdf = doc("#d93025", "PDF");
// library skills: a Lucide glyph on a tinted tile; the hue groups them (data, writing, media, code, design, learning)
const SKILL_ICONS: Record<string, [LucideIcon, string]> = {
  "data-analysis": [ChartLine, "#0f9d58"], "csv-cleanup": [TableProperties, "#0f9d58"], "spreadsheet-formulas": [Sigma, "#0f9d58"],
  "sql-helper": [Database, "#0f9d58"],
  "business-writing": [Mail, "#1a73e8"], "internal-comms": [Megaphone, "#1a73e8"], "meeting-notes": [NotebookPen, "#1a73e8"],
  "summarize-documents": [ScrollText, "#1a73e8"], "translation": [Languages, "#1a73e8"], "research-citations": [Telescope, "#1a73e8"],
  "resume-cover-letter": [Contact, "#1a73e8"], "readme-docs": [BookOpen, "#1a73e8"],
  "image-editing": [Image, "#e8710a"], "audio-video": [Clapperboard, "#e8710a"], "ocr-scans": [ScanText, "#e8710a"],
  "systematic-debugging": [Bug, "#5f6368"], "code-review": [GitPullRequest, "#5f6368"], "git-workflow": [GitBranch, "#5f6368"],
  "test-driven-development": [FlaskConical, "#5f6368"], "security-best-practices": [ShieldCheck, "#5f6368"], "mcp-builder": [Plug, "#5f6368"],
  "frontend-design": [LayoutTemplate, "#a142f4"], "algorithmic-art": [Palette, "#a142f4"], "brand-guidelines": [SwatchBook, "#a142f4"],
  "slide-outline": [ListOrdered, "#a142f4"],
  "brainstorming": [Lightbulb, "#c5221f"], "writing-plans": [ListChecks, "#c5221f"], "study-notes": [GraduationCap, "#c5221f"],
};
const SkillIcon = ({ name }: { name: string }) => {
  const hit = !ICONS[name] && SKILL_ICONS[name];
  if (!hit) return <AppIcon name={name} />;
  const [I, color] = hit;
  return <span className="app-icon skill-icon" style={{ "--tint": color } as React.CSSProperties} aria-hidden="true"><I size={26} strokeWidth={1.75} /></span>;
};
const AppIcon = ({ name }: { name: string }) => (
  <svg className="app-icon" viewBox="0 0 24 24" width="52" height="52" aria-hidden="true">{ICONS[name] ?? <><rect x="4" y="4" width="16" height="16" rx="4" fill="none" stroke="var(--muted)" strokeWidth="1.5" /><circle cx="12" cy="12" r="2.5" fill="var(--muted)" /></>}</svg>
);

/** Crafts page, Portals tab: apps the agent can use for you: connect a provider once (Google), then turn each app on or off. */
export function Apps({ onError, menuButton }: { onError: (e: unknown) => void; menuButton: React.ReactNode }) {
  const [items, setItems] = useState<AppItem[] | null>(null);
  const [q, setQ] = useState("");  // search portals by name or description
  const [searching, setSearching] = useState(false);
  const [note, setNote] = useState(oauthResult);
  const [confirm, setConfirm] = useState("");  // provider whose Disconnect was clicked once
  const [tokenFor, setTokenFor] = useState("");  // app whose "paste a token" form is open
  const [tab, setTab] = useState<"Portals" | "Skills">("Portals");
  const [tokenErr, setTokenErr] = useState("");
  const [detail, setDetail] = useState("");  // app whose detail page is open
  const [skills, setSkills] = useState<SkillItem[] | null>(null);
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setNote({ ok: false, text: errorText(e) }); }, [onError]);
  const load = useCallback(() => api.apps().then(setItems, fail), [fail]);
  useEffect(() => { load(); }, [load]);
  const [lib, setLib] = useState<LibrarySkill[] | null>(null);
  const loadSkills = useCallback(() => Promise.all([api.skills(), api.skillLibrary()]).then(([a, b]) => { setSkills(a); setLib(b); }, fail), [fail]);
  const skillDo = async (f: () => Promise<unknown>) => { try { await f(); } catch (e) { fail(e); } loadSkills(); };
  const saveZip = async (name: string) => {
    try {
      const url = URL.createObjectURL(await api.skillZip(name));
      const a = document.createElement("a");
      a.href = url; a.download = `${name}.zip`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { fail(e); }
  };
  const importZip = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) skillDo(() => api.importSkill(f));
  };
  useEffect(() => { if (tab === "Skills" && skills === null) loadSkills(); }, [tab, skills, loadSkills]);
  const toggleSkill = async (s: SkillItem) => {
    setSkills((xs) => xs && xs.map((x) => x.name === s.name ? { ...x, enabled: !s.enabled } : x));  // flip now, server catches up
    try { await api.setSkill(s.name, !s.enabled); } catch (e) { fail(e); loadSkills(); }
  };
  const skillTile = (s: SkillItem) => (
    <li key={s.name} className={`app-tile ${s.enabled ? "on" : ""}`} aria-label={s.label}>
      <SkillIcon name={s.name} />
      <div className="app-text"><strong>{s.label}</strong><div className="muted small app-desc">{s.description}</div></div>
      {s.update && <button className="ghost small" title="The library has a newer version" onClick={() => skillDo(() => api.addSkill(s.name))}>
        <IconRefresh size={14} /> Update</button>}
      <button className="ghost icon" aria-label={`Download ${s.label}`} title="Download (.zip)" onClick={() => saveZip(s.name)}><IconDownload size={16} /></button>
      <button className="ghost icon" aria-label={`Remove ${s.label}`} title="Remove from your skills" onClick={() => skillDo(() => api.removeSkill(s.name))}><IconTrash size={16} /></button>
      <label className="sw"><button className={`switch ${s.enabled ? "on" : ""}`} role="switch" aria-checked={s.enabled}
        aria-label={`Use ${s.label}`} onClick={() => toggleSkill(s)}><span /></button></label>
    </li>
  );
  const libTile = (s: LibrarySkill) => (
    <li key={s.name} className="app-tile" aria-label={s.label}>
      <SkillIcon name={s.name} />
      <div className="app-text"><strong>{s.label}</strong><div className="muted small app-desc">{s.description}</div></div>
      <button className="ghost small" aria-label={`Add ${s.label}`} onClick={() => skillDo(() => api.addSkill(s.name))}><IconPlus size={14} /> Add</button>
    </li>
  );
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
  // One grid for every portal: the switch already says which ones Simp uses, so no Connected/Available split.
  // A connected app shows its account instead of the description, and a chevron to its page.
  const tile = (a: AppItem) => {
    const acc = a.accounts ?? [];
    if (tokenFor === a.app) return <li key={a.app} className="app-tile editing" aria-label={a.label}><strong>{a.label}</strong>{tokenForm(a)}</li>;
    return (
      <li key={a.app} className={`app-tile ${a.enabled ? "on" : ""}`} aria-label={a.label} onClick={open(a)}>
        <AppIcon name={a.icon} />
        <div className="app-text"><strong>{a.label}</strong>
          <div className="muted small app-desc">{acc[0]?.email
            ? <>{acc[0].email}{acc.length > 1 && <span className="more">+{acc.length - 1}</span>}</>
            : a.description}</div>
          {warn(a)}</div>
        {a.status === "needs_reconnect" ? fix(a)
          : a.connected || !a.auth ? sw(a)
          : <button className="ghost small" aria-label={`Connect ${a.label}`} onClick={() => a.auth === "token" ? openToken(a.app) : connect(a.app)}>{a.auth === "token" ? "Add token" : "Connect"}</button>}
        {a.connected && a.auth && <button className="ghost icon app-open" aria-label={`${a.label} details`} title="Manage" onClick={() => setDetail(a.app)}><IconChevron size={16} /></button>}
      </li>
    );
  };
  if (detail) return <Detail app={detail} onBack={() => { setDetail(""); load(); }} fail={fail} menuButton={menuButton} />;

  return (
    <main className="memory">
      <header className="home-head">{menuButton}</header>
      <div className="memory-body">
        <h1 className="page-title">Crafts</h1>
        {/* same layout as Memory (and claude.ai): tabs on the left, tools on the right */}
        <div className="mem-toolbar">
          <div className="tabs" role="tablist">
            {(["Portals", "Skills"] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className="tab" onClick={() => setTab(t)}>{t}</button>
            ))}
          </div>
          <span className="spacer" />
          {(searching || q ? (
            <label className="mem-search"><IconSearch size={16} />
              <input type="search" autoFocus value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => !q && setSearching(false)}
                onKeyDown={(e) => e.key === "Escape" && (setQ(""), setSearching(false))} placeholder={`Search ${tab.toLowerCase()}…`} aria-label={`Search ${tab.toLowerCase()}`} />
            </label>
          ) : (
            <button className="ghost icon" aria-label="Search" title="Search" onClick={() => setSearching(true)}><IconSearch /></button>
          ))}
        </div>
        {tab === "Skills" ? <>
          <p className="muted small mem-about">Know-how Simp reads before a task that needs it, such as making a deck or a spreadsheet.
            Add skills from the library or import your own (.zip with a SKILL.md).
            <label className="ghost small skill-import"><IconUpload size={14} /> Import .zip
              <input type="file" accept=".zip,application/zip" hidden onChange={importZip} /></label></p>
          {skills === null || lib === null ? <p className="muted">Loading…</p> : (() => {
            const needle = q.trim().toLowerCase();
            const hit = (s: { label: string; description: string }) => !needle || `${s.label} ${s.description}`.toLowerCase().includes(needle);
            const mine = skills.filter(hit), more = lib.filter((s) => !s.added && hit(s));
            return <>
              <h3 className="skill-head">Your skills</h3>
              {mine.length === 0 ? <p className="muted">{needle ? `None of yours match “${q.trim()}”.` : "No skills yet. Add some from the library below."}</p>
                : <ul className="app-tiles" aria-label="Your skills">{mine.map(skillTile)}</ul>}
              {(more.length > 0 || !needle) && <h3 className="skill-head">Library</h3>}
              {more.length === 0 ? !needle && <p className="muted">You have every skill in the library.</p>
                : <ul className="app-tiles" aria-label="Skill library">{more.map(libTile)}</ul>}
            </>;
          })()}
        </> : <>
        {note && <p className={note.ok ? "ok" : "error"} role="status">{note.text}</p>}
        {items === null ? <p className="muted">Loading…</p> : items.length === 0 ? <p className="muted">No portals are set up on this server.</p> : <>
          {(() => {
            const needle = q.trim().toLowerCase();
            const shown = needle ? items.filter((a) => `${a.label} ${a.description}`.toLowerCase().includes(needle)) : items;
            return shown.length === 0 ? <p className="muted">No portals match “{q.trim()}”.</p> : <>
              <ul className="app-tiles" aria-label="Portals">{shown.map(tile)}</ul>
            </>;
          })()}
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
