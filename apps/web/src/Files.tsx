import { useCallback, useEffect, useRef, useState } from "react";
import { api, AuthError, type FileEntry, type WorkspaceUsage } from "./api";
import { errorText } from "./Chat";
import { IconClose, IconFolder, IconRefresh, IconTrash, IconUpload, fileIcon } from "./icons";
import { kindOf } from "./fileKind";

const dirOf = (p: string) => { const i = p.replace(/^\.\//, "").lastIndexOf("/"); return i <= 0 ? (i === 0 ? "/" : ".") : p.replace(/^\.\//, "").slice(0, i); };
const baseOf = (p: string) => p.split("/").pop() ?? p;

/** `focus`: a file path to start at (its folder) and highlight. sid "" = no session (the Files page): the workspace is
 * the user's either way. `onClose` omitted = the list is the page itself, not a side panel. */
export function Files({ sid, onError, onClose, onPreview, focus }: { sid: string; onError: (e: unknown) => void; onClose?: () => void; onPreview: (path: string) => void; focus?: string }) {
  const [path, setPath] = useState(focus ? dirOf(focus) : ".");
  useEffect(() => { if (focus) setPath(dirOf(focus)); }, [focus]);
  const hl = focus && path === dirOf(focus) ? baseOf(focus) : undefined;
  // the list remembers which folder it is for: a slow reply for an old folder never shows under the new one
  const [listed, setListed] = useState<{ key: string; entries: FileEntry[] }>({ key: "", entries: [] });
  const entries = listed.key === `${sid}:${path}` ? listed.entries : [];
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string>();
  const [usage, setUsage] = useState<WorkspaceUsage>();
  const [armed, setArmed] = useState<string>();  // the entry whose delete button asks "Delete?" (second click deletes)
  // onError still sees every failure (AuthError logs out); non-auth ones are also shown in the panel.
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);
  const load = useCallback(() => {
    setLoading(true);
    return api.files(sid, path)
      .then((es) => { setListed({ key: `${sid}:${path}`, entries: es }); setError(undefined); }, fail)
      .finally(() => setLoading(false));
  }, [sid, path, fail]);
  const loadUsage = useCallback(() => { api.workspace().then(setUsage, () => {}); }, []);
  useEffect(() => { load(); loadUsage(); }, [load, focus, loadUsage]);
  useEffect(() => setArmed(undefined), [path]);
  const picker = useRef<HTMLInputElement>(null);
  const join = (name: string) => (path === "." ? name : `${path}/${name}`);

  const upload = async (files: FileList | null) => {
    setUploading(true);
    try {
      for (const f of files ?? []) await api.upload(sid, join(f.name), f);
      setError(undefined);
    } catch (e) { fail(e); }
    finally {
      setUploading(false);
      if (picker.current) picker.current.value = "";  // so picking the same file again fires onChange
      load();
      loadUsage();
    }
  };

  const remove = async (name: string) => {
    if (armed !== name) { setArmed(name); return; }
    setArmed(undefined);
    try { setUsage(await api.deleteFile(sid, join(name))); setError(undefined); } catch (e) { fail(e); }
    load();
  };

  return (
    <aside className={`files${onClose ? "" : " files-standalone"}`} aria-label="Files">
      <header>
        <strong>Files</strong>
        <span className="spacer" />
        <button className="icon-btn" onClick={() => { load(); loadUsage(); }} title="Refresh" aria-label="Refresh"><IconRefresh size={16} /></button>
        <button className="upload" onClick={() => picker.current?.click()} disabled={uploading}>
          <IconUpload size={16} />{uploading ? "Uploading…" : "Upload"}
        </button>
        <input ref={picker} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
        {onClose && <button className="icon-btn" onClick={onClose} title="Close files" aria-label="Close files"><IconClose size={16} /></button>}
      </header>
      <nav className="path" aria-label="Folder">
        {/* "work" is the workspace root (/work in the sandbox); each part opens that folder */}
        {["work", ...path.split("/").filter((x) => x && x !== ".")].map((part, i, all) => (
          <span key={i}>
            {i > 0 && <span className="sep" aria-hidden>/</span>}
            {i === all.length - 1 ? <strong aria-current="location">{part}</strong>
              : <button onClick={() => setPath(all.slice(1, i + 1).join("/") || ".")}>{part}</button>}
          </span>
        ))}
      </nav>
      {error && <div className="error" role="alert">{error}</div>}
      <ul aria-busy={loading}>
        {path !== "." && (
          <li><button onClick={() => setPath(path.split("/").slice(0, -1).join("/") || ".")} title="Up one folder">
            <IconFolder size={16} /><span>..</span>
          </button></li>
        )}
        {entries.map((e) => (
          <li key={e.name} className={e.name === hl ? "focus" : undefined} aria-current={e.name === hl || undefined}>
            <button onClick={() => (e.is_dir ? setPath(join(e.name)) : onPreview(join(e.name)))} title={e.name}>
              {e.is_dir ? <IconFolder size={16} /> : (() => { const K = fileIcon(e.name, kindOf(e.name)); return <K size={16} />; })()}<span>{e.name}</span>
            </button>
            {!e.is_dir && <span className="size">{fmt(e.size)}</span>}
            <button className={`del${armed === e.name ? " armed" : ""}`} onClick={() => remove(e.name)} onBlur={() => armed === e.name && setArmed(undefined)}
              title={armed === e.name ? `Click again to delete ${e.name}${e.is_dir ? " and everything in it" : ""}` : `Delete ${e.name}`}
              aria-label={armed === e.name ? `Confirm delete ${e.name}` : `Delete ${e.name}`}>
              {armed === e.name ? "Delete?" : <IconTrash size={14} />}
            </button>
          </li>
        ))}
        {entries.length === 0 && <li className="empty">{loading ? "Loading…" : error ? "" : path === "." && !onClose
          ? "Nothing here yet. Upload a file, or ask Simp in a chat to make one." : "Empty"}</li>}
      </ul>
      {usage && usage.state !== "off" && <Storage u={usage} />}
    </aside>
  );
}

/** Storage used of the quota: amber at 80% (warn), red at 95% (full: the agent can no longer write to /work). */
function Storage({ u }: { u: WorkspaceUsage }) {
  const pct = Math.min(100, (u.used / u.quota) * 100);
  const text = `${fmt(u.used)} of ${fmt(u.quota)} used`;
  return (
    <footer className="storage">
      <div className="credit-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-valuetext={text} title={text}>
        <i className={u.state === "full" ? "out" : u.state === "warn" ? "low" : undefined} style={{ width: `${pct}%` }} />
      </div>
      <span>{text}</span>
      {u.state === "full" && <p className="full" role="status">Storage full: the agent can't save files. Delete some to free space.</p>}
      {u.state === "warn" && <p className="warn">Storage almost full.</p>}
    </footer>
  );
}

export const fmt = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1073741824).toFixed(2)} GB`);
