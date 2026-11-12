import { useCallback, useEffect, useState } from "react";
import { api, AuthError, type MemoryItem } from "./api";
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
              {list.length === 0 && <p className="muted small">{empty}</p>}
              <ul>
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
                          <span>{new Date(m.created * 1000).toLocaleDateString()}</span>
                          {m.source_run_id && <span title={`Saved during run ${m.source_run_id}`}>from a chat</span>}
                          <button className={`ghost del ${confirm === m.id ? "confirm" : "icon"}`} aria-label="Delete memory"
                            title="Delete memory" onClick={() => remove(m.id)} onBlur={() => setConfirm("")}>
                            {confirm === m.id ? "Delete?" : <IconTrash size={16} />}
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </main>
  );
}
