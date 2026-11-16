import type { Protocol, SessionInfo } from "./protocol.gen";
import type { ServerEvent } from "./state";
import { sharedLocation } from "./location";

export type Command = Protocol["command"];
export interface FileEntry { name: string; is_dir: boolean; size: number }
/** REST-only (GET /api/apps). */
export interface AppItem {
  app: string; label: string; description: string; icon: string; provider: string | null;  // null: no login needed, connected is always true
  connected: boolean; enabled: boolean; email: string | null; status: "ok" | "needs_reconnect" | null;
  auth: "oauth" | "token" | null; token_help_url: string | null;  // auth "token": paste a token (POST .../token)
  accounts?: Account[];  // linked accounts that can use this app, default (oldest) first
}
export interface Account { link_id: string; email: string | null; status: "ok" | "needs_reconnect"; created: number }
/** REST-only (GET /api/apps/{app}): the portal detail page. */
export interface AppDetail extends AppItem {
  scopes: string[]; url: string; tools: { name: string; needs_approval: boolean }[];
  calls: { at: number; tool: string; account: string | null; ok: boolean; decision: string }[];
}
/** REST-only (GET /api/memories), not in the protocol schema. */
export interface MemoryItem { id: string; scope: "global" | "agent"; agent_id: string | null; content: string; created: number; source_run_id: string | null }

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
  me: async (): Promise<{ name: string }> => (await call("/api/me")).json(),
  logout: () => call("/api/logout", { method: "POST" }),
  hello: () => call("/api/hello", json({ type: "hello", protocol_version: 1 })),
  sessions: async (): Promise<SessionInfo[]> => (await call("/api/sessions")).json(),
  newSession: async (profile: string): Promise<SessionInfo> => (await call("/api/sessions", json({
    profile, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    ...(sharedLocation() ? { location: sharedLocation() } : {}),  // opt-in only (account menu: Share location)
  }))).json(),
  profiles: async (): Promise<string[]> => (await call("/api/profiles")).json(),
  models: async (): Promise<Record<string, string>> => (await call("/api/models")).json(),
  deleteSession: (sid: string) => call(`/api/sessions/${sid}`, { method: "DELETE" }),
  usage: async (): Promise<{ today_usd: number; day_limit_usd: number; paused: boolean }> => (await call("/api/usage")).json(),
  command: (sid: string, c: Command) => call(`/api/sessions/${sid}/commands`, json(c)),
  files: async (sid: string, path: string): Promise<FileEntry[]> =>
    (await call(`/api/sessions/${sid}/files?path=${encodeURIComponent(path)}`)).json(),
  download: async (sid: string, path: string): Promise<Blob> =>
    (await call(`/api/sessions/${sid}/files/raw?path=${encodeURIComponent(path)}`)).blob(),
  /** path is relative to the workspace root. */
  upload: (sid: string, path: string, data: Blob) =>
    call(`/api/sessions/${sid}/files/raw?path=${encodeURIComponent(path)}`, { method: "PUT", body: data }),
  apps: async (): Promise<AppItem[]> => (await call("/api/apps")).json(),
  setApp: (app: string, on: boolean) => call(`/api/apps/${app}/${on ? "enable" : "disable"}`, { method: "POST" }),
  appDetail: async (app: string): Promise<AppDetail> => (await call(`/api/apps/${app}`)).json(),
  /** linkId: add this app's scopes to that account; none: Google's account chooser (add an account). */
  connect: async (app: string, linkId?: string): Promise<{ url: string }> =>
    (await call(`/api/apps/${app}/connect`, linkId ? json({ link_id: linkId }) : { method: "POST" })).json(),
  saveToken: (provider: string, token: string) => call(`/api/connections/${provider}/token`, json({ token })),
  disconnect: (linkId: string) => call(`/api/connections/${linkId}`, { method: "DELETE" }),
  memories: async (): Promise<MemoryItem[]> => (await call("/api/memories")).json(),
  editMemory: (id: string, content: string) => call(`/api/memories/${id}`, { ...json({ content }), method: "PATCH" }),
  deleteMemory: (id: string) => call(`/api/memories/${id}`, { method: "DELETE" }),
  exportMemories: async (): Promise<Blob> => (await call("/api/memories/export")).blob(),
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
