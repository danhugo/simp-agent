import { useCallback, useEffect, useRef, useState } from "react";
import { api, AuthError, type FileEntry } from "./api";
import { errorText } from "./Chat";
import { IconClose, IconFile, IconFolder, IconRefresh, IconUpload } from "./icons";

const dirOf = (p: string) => { const i = p.replace(/^\.\//, "").lastIndexOf("/"); return i <= 0 ? (i === 0 ? "/" : ".") : p.replace(/^\.\//, "").slice(0, i); };
const baseOf = (p: string) => p.split("/").pop() ?? p;

/** `focus`: a file path to start at (its folder) and highlight. */
export function Files({ sid, onError, onClose, focus }: { sid: string; onError: (e: unknown) => void; onClose: () => void; focus?: string }) {
  const [path, setPath] = useState(focus ? dirOf(focus) : ".");
  useEffect(() => { if (focus) setPath(dirOf(focus)); }, [focus]);
  const hl = focus && path === dirOf(focus) ? baseOf(focus) : undefined;
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string>();
  // onError still sees every failure (AuthError logs out); non-auth ones are also shown in the panel.
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);
  const load = useCallback(() => {
    setLoading(true);
    return api.files(sid, path)
      .then((es) => { setEntries(es); setError(undefined); }, fail)
      .finally(() => setLoading(false));
  }, [sid, path, fail]);
  useEffect(() => { load(); }, [load, focus]);
  const picker = useRef<HTMLInputElement>(null);
  const join = (name: string) => (path === "." ? name : `${path}/${name}`);

  const download = async (name: string) => {
    try {
      const url = URL.createObjectURL(await api.download(sid, join(name)));
      Object.assign(document.createElement("a"), { href: url, download: name }).click();
      URL.revokeObjectURL(url);
    } catch (e) { fail(e); }
  };
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
      <div className="path">{path}</div>
      {error && <div className="error" role="alert">{error}</div>}
      <ul aria-busy={loading}>
        {path !== "." && (
          <li><button onClick={() => setPath(path.split("/").slice(0, -1).join("/") || ".")} title="Up one folder">
            <IconFolder size={16} /><span>..</span>
          </button></li>
        )}
        {entries.map((e) => (
          <li key={e.name} className={e.name === hl ? "focus" : undefined} aria-current={e.name === hl || undefined}>
            <button onClick={() => (e.is_dir ? setPath(join(e.name)) : download(e.name))} title={e.is_dir ? "Open" : "Download"}>
              {e.is_dir ? <IconFolder size={16} /> : <IconFile size={16} />}<span>{e.name}</span>
            </button>
            {!e.is_dir && <span className="size">{fmt(e.size)}</span>}
          </li>
        ))}
        {entries.length === 0 && <li className="empty">{loading ? "Loading…" : error ? "" : "Empty"}</li>}
      </ul>
    </aside>
  );
}

const fmt = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);
