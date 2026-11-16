import { useCallback, useEffect, useState } from "react";
import { api, AuthError, type MemoryItem } from "./api";
import { chatName } from "./App";
import { errorText } from "./Chat";
import { IconDownload, IconEdit, IconPlus, IconSearch, IconTrash } from "./icons";
import { Mascot3D } from "./Mascot3D";

const SECTIONS = [
  { scope: "global", title: "About you", about: "Simp uses these everywhere, in every chat.",
    empty: "Tell me something about you. I'll remember it in every chat." },
  { scope: "agent", title: "Simp's notes", about: "What Simp wrote down while working with you, to do it better next time.",
    empty: "Simp hasn't saved anything from your chats yet." },
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
  const [q, setQ] = useState("");  // search: content or the chat it came from
  const [searching, setSearching] = useState(false);  // the search icon opens the field
  const [view, setView] = useState<"all" | "global" | "agent">("all");
  const [addOpen, setAddOpen] = useState(false);  // "New memory" opens the add field
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adding.trim()) return;
    try { await api.addMemory(adding.trim()); setAdding(""); setAddOpen(false); await load(); } catch (e) { fail(e); }
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
      <header className="home-head">{menuButton}</header>
      <div className="memory-body">
        {/* like claude.ai's Projects/Artifacts: the title alone, then tabs on the left and tools + one primary action on the right */}
        <h1 className="page-title">Memory</h1>
        <div className="mem-toolbar">
          <div className="tabs" role="tablist">
            {([["all", "All"], ["global", "About you"], ["agent", "Simp's notes"]] as const).map(([v, label]) => (
              <button key={v} role="tab" aria-selected={view === v} className="tab" onClick={() => setView(v)}>{label}</button>
            ))}
          </div>
          <span className="spacer" />
          {searching || q ? (
            <label className="mem-search"><IconSearch size={16} />
              <input type="search" autoFocus value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => !q && setSearching(false)}
                onKeyDown={(e) => e.key === "Escape" && (setQ(""), setSearching(false))} placeholder="Search memory…" aria-label="Search memory" />
            </label>
          ) : (
            <button className="ghost icon" aria-label="Search" title="Search" disabled={!items?.length} onClick={() => setSearching(true)}><IconSearch /></button>
          )}
          <button className="ghost icon" onClick={exportAll} disabled={!items?.length} aria-label="Export" title="Export all as JSON"><IconDownload /></button>
          <button className="primary new-mem" onClick={() => { setAddOpen(true); setView((v) => (v === "agent" ? "all" : v)); }}>New memory</button>
        </div>
        {addOpen && (
          <form className="mem-add" onSubmit={add}>
            <IconPlus size={16} />
            <input value={adding} autoFocus onChange={(e) => setAdding(e.target.value)} maxLength={500}
              onKeyDown={(e) => e.key === "Escape" && (setAdding(""), setAddOpen(false))}
              placeholder="Something Simp should know about you…" aria-label="Add a memory" />
            <button className="primary" disabled={!adding.trim()}>Add</button>
            <button type="button" className="ghost" onClick={() => { setAdding(""); setAddOpen(false); }}>Cancel</button>
          </form>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        {items === null ? !error && <p className="muted">Loading…</p> : SECTIONS.filter(({ scope }) => view === "all" || view === scope).map(({ scope, title, about, empty }) => {
          const all = items.filter((m) => m.scope === scope), needle = q.trim().toLowerCase();
          const list = needle ? all.filter((m) => `${m.content} ${m.source_title ?? ""}`.toLowerCase().includes(needle)) : all;
          return (
            <section key={scope} aria-label={title}>
              <h2>{title}</h2>
              <p className="muted small mem-about">{about}</p>
              {needle && all.length > 0 && list.length === 0 && <p className="muted small">No notes match “{q.trim()}”.</p>}
              {all.length === 0 && (scope === "global"
                ? <div className="mem-empty"><Mascot3D size={40} pixels={48} mood="asking" /><p className="muted">{empty}</p>
                    {!addOpen && <button className="ghost" onClick={() => setAddOpen(true)}>New memory</button>}</div>
                : <p className="muted small">{empty}</p>)}
              {list.length > 0 && <ul className={`mem-list ${scope}`}>
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
                          {/* fixed columns, so dates and sources line up down the list */}
                          {!m.source_run_id ? <span className="mem-src" />
                            : m.source_title != null
                            ? <a className="mem-src" href={`#${m.source_run_id}`} title="Open the chat this came from">
                                {chatName({ title: m.source_title, created: m.source_created ?? undefined })}</a>
                            : <span className="mem-src" title="The chat this came from was deleted">Deleted chat</span>}
                          <span className="mem-date" title={new Date(m.created * 1000).toLocaleString()}>{ago(m.created)}</span>
                          <button className="ghost icon edit" aria-label={`Edit memory: ${m.content}`} title="Edit memory"
                            onClick={() => { setEditing(m.id); setDraft(m.content); }}><IconEdit size={14} /></button>
                          <button className={`ghost del ${confirm === m.id ? "confirm" : "icon"}`} aria-label="Delete memory"
                            title="Delete memory" onClick={() => remove(m.id)} onBlur={() => setConfirm("")}>
                            {confirm === m.id ? "Delete?" : <IconTrash size={14} />}
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
