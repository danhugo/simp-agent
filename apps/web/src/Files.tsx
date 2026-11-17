import { useCallback, useEffect, useRef, useState } from "react";
import { api, AuthError, type FileEntry } from "./api";
import { errorText } from "./Chat";
import { IconClose, IconFolder, IconRefresh, IconUpload, KindIcons } from "./icons";
import { kindOf } from "./fileKind";

const dirOf = (p: string) => { const i = p.replace(/^\.\//, "").lastIndexOf("/"); return i <= 0 ? (i === 0 ? "/" : ".") : p.replace(/^\.\//, "").slice(0, i); };
const baseOf = (p: string) => p.split("/").pop() ?? p;

/** `focus`: a file path to start at (its folder) and highlight. */
export function Files({ sid, onError, onClose, onPreview, focus }: { sid: string; onError: (e: unknown) => void; onClose: () => void; onPreview: (path: string) => void; focus?: string }) {
  const [path, setPath] = useState(focus ? dirOf(focus) : ".");
  useEffect(() => { if (focus) setPath(dirOf(focus)); }, [focus]);
  const hl = focus && path === dirOf(focus) ? baseOf(focus) : undefined;
  // the list remembers which folder it is for: a slow reply for an old folder never shows under the new one
  const [listed, setListed] = useState<{ key: string; entries: FileEntry[] }>({ key: "", entries: [] });
  const entries = listed.key === `${sid}:${path}` ? listed.entries : [];
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string>();
  // onError still sees every failure (AuthError logs out); non-auth ones are also shown in the panel.
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);
  const load = useCallback(() => {
    setLoading(true);
    return api.files(sid, path)
      .then((es) => { setListed({ key: `${sid}:${path}`, entries: es }); setError(undefined); }, fail)
      .finally(() => setLoading(false));
  }, [sid, path, fail]);
  useEffect(() => { load(); }, [load, focus]);
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
    }
  };

  return (
    <aside className="files" aria-label="Files">
      <header>
        <strong>Files</strong>
        <span className="spacer" />
        <button className="icon-btn" onClick={load} title="Refresh" aria-label="Refresh"><IconRefresh size={16} /></button>
        <button className="upload" onClick={() => picker.current?.click()} disabled={uploading}>
          <IconUpload size={16} />{uploading ? "Uploading…" : "Upload"}
        </button>
        <input ref={picker} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
        <button className="icon-btn" onClick={onClose} title="Close files" aria-label="Close files"><IconClose size={16} /></button>
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
              {e.is_dir ? <IconFolder size={16} /> : (() => { const K = KindIcons[kindOf(e.name)]; return <K size={16} />; })()}<span>{e.name}</span>
            </button>
            {!e.is_dir && <span className="size">{fmt(e.size)}</span>}
          </li>
        ))}
        {entries.length === 0 && <li className="empty">{loading ? "Loading…" : error ? "" : "Empty"}</li>}
      </ul>
    </aside>
  );
}

export const fmt = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);
