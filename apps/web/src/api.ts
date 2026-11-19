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
export interface MemoryItem { id: string; scope: "global" | "agent"; agent_id: string | null; content: string; created: number; source_run_id: string | null;
  /** the chat it was saved in, if that chat still exists ("" = untitled) */ source_title?: string | null; source_created?: number | null }

/** REST-only (/api/persona): Simp's personality (the user's words) and outfit slot code (see skin.ts). {} = none. */
export interface Persona { name?: string; description?: string; instruction?: string; hat?: string; bottom?: string; profile?: string }

/** REST-only (/api/outfits): a saved outfit in the user's collection. */
export interface Outfit { id: string; kind: "outfit" | "hat" | "bottom"; name: string; description: string; hat: string; bottom: string; created: number }

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

const send = (method: string, body: unknown): RequestInit => ({ ...json(body), method });

/** REST-only (/api/admin/*): admins only (ADMIN_EMAILS on the server); everyone else gets 403. */
export interface AdminUser { id: string; email: string; created: number | null; revoked: boolean; points_granted: number;
  points_spent: number; points_balance: number; spend_7d_usd: number; last_active: number | null }
export interface AdminUserDetail extends AdminUser {
  ledger: { id: number; points: number; note: string; created: number }[];
  usage_30d: { model: string; calls: number; input: number; output: number; cost_usd: number }[];
  /** quota_mb_override: null = the global workspace.quota_mb applies. */
  workspace: WorkspaceUsage & { quota_mb_override: number | null };
}
export interface AdminSystem { paused: boolean; spend_today_usd: number; open_sessions: number; busy_sessions: number; users: number; billing_enabled: boolean }
export interface AdminAudit { id: number; action: string; actor: string | null; target: string | null; detail: Record<string, unknown>; created: number }
export interface AdminSetting { key: string; value: unknown; file_value: unknown; source: "file" | "db"; editable: boolean; updated: number | null }
export interface AdminHistory { id: number; key: string; old: unknown; new: unknown; actor_email: string | null; reason: string; created: number }

/** Workspace storage: bytes used of the quota (0 = no quota). full = /work is read-only for the agent. */
export type WorkspaceUsage = { used: number; quota: number; state: "off" | "ok" | "warn" | "full" };

export const admin = {
  me: async (): Promise<boolean> => { try { await call("/api/admin/me"); return true; } catch (e) { if (e instanceof AuthError) throw e; return false; } },
  users: async (q: string, offset = 0): Promise<{ users: AdminUser[]; total: number }> =>
    (await call(`/api/admin/users?q=${encodeURIComponent(q)}&limit=50&offset=${offset}`)).json(),
  user: async (id: string): Promise<AdminUserDetail> => (await call(`/api/admin/users/${id}`)).json(),
  credit: async (id: string, points: number, reason: string, confirm = false) =>
    (await call(`/api/admin/users/${id}/credit`, json({ points, reason, confirm }))).json(),
  /** quota_mb: null = back to the global default, 0 = no limit. */
  quota: (id: string, quota_mb: number | null, reason: string) => call(`/api/admin/users/${id}/quota`, send("PUT", { quota_mb, reason })),
  revoke: (id: string, revoke: boolean, reason: string) => call(`/api/admin/users/${id}/${revoke ? "revoke" : "unrevoke"}`, json({ reason })),
  system: async (): Promise<AdminSystem> => (await call("/api/admin/system")).json(),
  pause: (pause: boolean, reason: string) => call(`/api/admin/system/${pause ? "pause" : "resume"}`, json({ reason })),
  audit: async (offset = 0): Promise<AdminAudit[]> => (await call(`/api/admin/audit?limit=50&offset=${offset}`)).json(),
  settings: async (): Promise<AdminSetting[]> => (await call("/api/admin/settings")).json(),
  putSetting: (key: string, value: unknown, reason: string) => call(`/api/admin/settings/${encodeURIComponent(key)}`, send("PUT", { value, reason })),
  history: async (key = ""): Promise<AdminHistory[]> => (await call(`/api/admin/settings/history?key=${encodeURIComponent(key)}`)).json(),
  rollback: (id: number, reason: string) => call(`/api/admin/settings/history/${id}/rollback`, json({ reason })),
};

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
  usage: async (): Promise<{ today_usd: number; day_limit_usd: number; paused: boolean; billing_enabled: boolean; points_balance: number | null; points_granted: number | null }> => (await call("/api/usage")).json(),
  command: (sid: string, c: Command) => call(`/api/sessions/${sid}/commands`, json(c)),
  files: async (sid: string, path: string): Promise<FileEntry[]> =>
    (await call(`/api/sessions/${sid}/files?path=${encodeURIComponent(path)}`)).json(),
  download: async (sid: string, path: string): Promise<Blob> =>
    (await call(`/api/sessions/${sid}/files/raw?path=${encodeURIComponent(path)}`)).blob(),
  /** path is relative to the workspace root. */
  upload: (sid: string, path: string, data: Blob) =>
    call(`/api/sessions/${sid}/files/raw?path=${encodeURIComponent(path)}`, { method: "PUT", body: data }),
  /** A file or a whole folder. Returns the workspace usage after the delete. */
  deleteFile: async (sid: string, path: string): Promise<WorkspaceUsage> =>
    (await call(`/api/sessions/${sid}/files?path=${encodeURIComponent(path)}`, { method: "DELETE" })).json(),
  workspace: async (): Promise<WorkspaceUsage> => (await call("/api/workspace")).json(),
  /** html/pdf preview: base URL on the separate preview origin; iframe src = base + path. */
  preview: async (sid: string): Promise<{ base: string }> => (await call(`/api/sessions/${sid}/preview`, { method: "POST" })).json(),
  apps: async (): Promise<AppItem[]> => (await call("/api/apps")).json(),
  setApp: (app: string, on: boolean) => call(`/api/apps/${app}/${on ? "enable" : "disable"}`, { method: "POST" }),
  appDetail: async (app: string): Promise<AppDetail> => (await call(`/api/apps/${app}`)).json(),
  /** linkId: add this app's scopes to that account; none: Google's account chooser (add an account). */
  connect: async (app: string, linkId?: string): Promise<{ url: string }> =>
    (await call(`/api/apps/${app}/connect`, linkId ? json({ link_id: linkId }) : { method: "POST" })).json(),
  saveToken: (provider: string, token: string) => call(`/api/connections/${provider}/token`, json({ token })),
  disconnect: (linkId: string) => call(`/api/connections/${linkId}`, { method: "DELETE" }),
  memories: async (): Promise<MemoryItem[]> => (await call("/api/memories")).json(),
  addMemory: (content: string) => call("/api/memories", json({ content })),
  editMemory: (id: string, content: string) => call(`/api/memories/${id}`, { ...json({ content }), method: "PATCH" }),
  deleteMemory: (id: string) => call(`/api/memories/${id}`, { method: "DELETE" }),
  persona: async (): Promise<Persona> => (await call("/api/persona")).json(),
  savePersona: (p: Persona) => call("/api/persona", { ...json(p), method: "PUT" }),
  generatePersona: async (b: { description: string; profile: string; slot: "hat" | "bottom"; other?: string; code?: string; error?: string }, signal?: AbortSignal): Promise<{ code: string }> =>
    (await call("/api/persona/generate", { ...json(b), signal })).json(),
  outfits: async (): Promise<Outfit[]> => (await call("/api/outfits")).json(),
  addOutfit: async (o: Omit<Outfit, "id" | "created">): Promise<{ id: string }> => (await call("/api/outfits", json(o))).json(),
  deleteOutfit: (id: string) => call(`/api/outfits/${id}`, { method: "DELETE" }),
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
