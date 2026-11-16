import { useCallback, useEffect, useState } from "react";
import { api, AuthError, type MemoryItem } from "./api";
import { chatName } from "./App";
import { errorText } from "./Chat";
import { IconDownload, IconTrash } from "./icons";

const SECTIONS = [
  { scope: "global", title: "About you", empty: "The agent does not know anything about you yet." },
  { scope: "agent", title: "What the agent learned", empty: "The agent has not saved anything yet." },
] as const;

/** What the agent remembers: view, edit, delete, export. */
export function Memory({ onError, menuButton }: { onError: (e: unknown) => void; menuButton: React.ReactNode }) {
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState("");  // id being edited
  const [draft, setDraft] = useState("");
  const [confirm, setConfirm] = useState("");  // id whose delete was clicked once
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);
  const load = useCallback(() => api.memories().then((m) => { setItems(m); setError(""); }, fail), [fail]);
  useEffect(() => { load(); }, [load]);

  const save = async (id: string) => {
    try { await api.editMemory(id, draft.trim()); setEditing(""); await load(); } catch (e) { fail(e); }
  };
  const [adding, setAdding] = useState("");
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adding.trim()) return;
    try { await api.addMemory(adding.trim()); setAdding(""); await load(); } catch (e) { fail(e); }
  };
  const remove = async (id: string) => {
    if (confirm !== id) return setConfirm(id);  // first click asks, second deletes (like session delete)
    setConfirm("");
    try { await api.deleteMemory(id); await load(); } catch (e) { fail(e); }
  };
  const exportAll = async () => {
    try {
      const url = URL.createObjectURL(await api.exportMemories());
      Object.assign(document.createElement("a"), { href: url, download: "memories.json" }).click();
      URL.revokeObjectURL(url);
    } catch (e) { fail(e); }
  };

  return (
    <main className="memory">
      <header className="home-head">{menuButton}<h1>Memory</h1>
        <button className="ghost export" onClick={exportAll} disabled={!items?.length}><IconDownload /><span>Export</span></button>
      </header>
      <div className="memory-body">
        <p className="muted">Things the agent remembers between chats. You can fix or remove anything here.</p>
        {error && <p className="error" role="alert">{error}</p>}
        {items === null ? !error && <p className="muted">Loading…</p> : SECTIONS.map(({ scope, title, empty }) => {
          const list = items.filter((m) => m.scope === scope);
          return (
            <section key={scope} aria-label={title}>
              <h2>{title}</h2>
              {scope === "global" && (
                <form className="mem-add" onSubmit={add}>
                  <input value={adding} onChange={(e) => setAdding(e.target.value)} maxLength={500}
                    placeholder="Add something Simp should know about you…" aria-label="Add a memory" />
                  <button className="primary" disabled={!adding.trim()}>Add</button>
                </form>
              )}
              {list.length === 0 && <p className="muted small">{empty}</p>}
              {list.length > 0 && <ul className="mem-list">
                {list.map((m) => (
                  <li key={m.id} className="mem">
                    {editing === m.id ? (
                      <form onSubmit={(e) => { e.preventDefault(); save(m.id); }}>
                        <textarea aria-label="Memory text" value={draft} autoFocus rows={3}
                          onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setEditing("")} />
                        <div className="row">
                          <button className="primary" disabled={!draft.trim()}>Save</button>
                          <button type="button" className="ghost" onClick={() => setEditing("")}>Cancel</button>
                        </div>
                      </form>
                    ) : (
                      <>
                        <button className="ghost mem-text" title="Edit" aria-label={`Edit: ${m.content}`}
                          onClick={() => { setEditing(m.id); setDraft(m.content); }}>{m.content}</button>
                        <div className="mem-meta muted small">
                          <span title={new Date(m.created * 1000).toLocaleString()}>{ago(m.created)}</span>
                          {m.source_run_id && (m.source_title != null
                            ? <a className="mem-src" href={`#${m.source_run_id}`} title="Open the chat this came from">
                                {chatName({ title: m.source_title, created: m.source_created ?? undefined })}</a>
                            : <span title="That chat was deleted">from a deleted chat</span>)}
                          <button className="ghost small edit" aria-label={`Edit memory: ${m.content}`}
                            onClick={() => { setEditing(m.id); setDraft(m.content); }}>Edit</button>
                          <button className={`ghost del ${confirm === m.id ? "confirm" : "icon"}`} aria-label="Delete memory"
                            title="Delete memory" onClick={() => remove(m.id)} onBlur={() => setConfirm("")}>
                            {confirm === m.id ? "Delete?" : <IconTrash size={16} />}
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>}
            </section>
          );
        })}
      </div>
    </main>
  );
}

/** "just now", "5 min ago", "3 hours ago", "yesterday", "4 days ago", then a short date. */
export function ago(t: number, now = Date.now() / 1000): string {
  const s = Math.max(0, now - t), m = s / 60, h = m / 60, d = h / 24;
  if (m < 1) return "just now";
  if (h < 1) return `${Math.floor(m)} min ago`;
  if (d < 1) return `${Math.floor(h)} hour${Math.floor(h) > 1 ? "s" : ""} ago`;
  if (d < 2) return "yesterday";
  if (d < 30) return `${Math.floor(d)} days ago`;
  return new Date(t * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}
