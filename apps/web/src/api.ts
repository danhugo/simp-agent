import type { Protocol, SessionInfo } from "./protocol.gen";
import type { ServerEvent } from "./state";

export type Command = Protocol["command"];
export interface FileEntry { name: string; is_dir: boolean; size: number }

export class AuthError extends Error {}

export const getToken = () => localStorage.getItem("simp.token") ?? "";
export const setToken = (t: string) => (t ? localStorage.setItem("simp.token", t) : localStorage.removeItem("simp.token"));

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, { ...init, headers: { Authorization: `Bearer ${getToken()}`, ...init.headers } });
  if (r.status === 401) throw new AuthError("invalid token");
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r;
}

const json = (body: unknown): RequestInit => ({
  method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" },
});

export const api = {
  hello: () => call("/api/hello", json({ type: "hello", protocol_version: 1 })),
  sessions: async (): Promise<SessionInfo[]> => (await call("/api/sessions")).json(),
  newSession: async (profile: string): Promise<SessionInfo> => (await call("/api/sessions", json({ profile }))).json(),
  profiles: async (): Promise<string[]> => (await call("/api/profiles")).json(),
  deleteSession: (sid: string) => call(`/api/sessions/${sid}`, { method: "DELETE" }),
  command: (sid: string, c: Command) => call(`/api/sessions/${sid}/commands`, json(c)),
  files: async (sid: string, path: string): Promise<FileEntry[]> =>
    (await call(`/api/sessions/${sid}/files?path=${encodeURIComponent(path)}`)).json(),
  download: async (sid: string, path: string): Promise<Blob> =>
    (await call(`/api/sessions/${sid}/files/raw?path=${encodeURIComponent(path)}`)).blob(),
  upload: (sid: string, path: string, data: Blob) =>
    call(`/api/sessions/${sid}/files/raw?path=${encodeURIComponent(path)}`, { method: "PUT", body: data }),
};

export type ConnStatus = "connecting" | "live" | "reconnecting";

/**
 * EventSource-like SSE client over fetch (EventSource cannot send Authorization).
 * Reconnects forever with Last-Event-ID = the last durable seq applied; the server answers with the missed
 * durable events, then a snapshot, then live.
 */
export function subscribe(
  sid: string, lastSeq: () => number, onEvent: (ev: ServerEvent) => void,
  onStatus: (s: ConnStatus) => void, onAuthError: () => void,
): () => void {
  const ctl = new AbortController();
  (async () => {
    for (let attempt = 0; !ctl.signal.aborted; attempt++) {
      onStatus(attempt ? "reconnecting" : "connecting");
      try {
        const r = await call(`/api/sessions/${sid}/events`, {
          signal: ctl.signal, headers: { "Last-Event-ID": String(lastSeq()) },
        });
        const reader = r.body!.pipeThrough(new TextDecoderStream()).getReader();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += value;
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const data = buf.slice(0, i).split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("\n");
            buf = buf.slice(i + 2);
            if (data) {
              const ev = JSON.parse(data) as ServerEvent;
              if (ev.type === "snapshot") { onStatus("live"); attempt = 0; }
              onEvent(ev);
            }
          }
        }
      } catch (e) {
        if (e instanceof AuthError) return onAuthError();
      }
      if (!ctl.signal.aborted) {
        onStatus("reconnecting");
        await new Promise((ok) => setTimeout(ok, Math.min(1000 * 2 ** attempt, 10000)));
      }
    }
  })();
  return () => ctl.abort();
}
