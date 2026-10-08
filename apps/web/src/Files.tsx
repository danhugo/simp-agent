import { useCallback, useEffect, useRef, useState } from "react";
import { api, type FileEntry } from "./api";

export function Files({ sid, onError }: { sid: string; onError: (e: unknown) => void }) {
  const [path, setPath] = useState(".");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const load = useCallback(() => api.files(sid, path).then(setEntries).catch(onError), [sid, path, onError]);
  useEffect(() => { load(); }, [load]);
  const picker = useRef<HTMLInputElement>(null);
  const join = (name: string) => (path === "." ? name : `${path}/${name}`);

  const download = async (name: string) => {
    try {
      const url = URL.createObjectURL(await api.download(sid, join(name)));
      Object.assign(document.createElement("a"), { href: url, download: name }).click();
      URL.revokeObjectURL(url);
    } catch (e) { onError(e); }
  };
  const upload = async (files: FileList | null) => {
    try {
      for (const f of files ?? []) await api.upload(sid, join(f.name), f);
      load();
    } catch (e) { onError(e); }
  };

  return (
    <aside className="files">
      <header>
        <strong>Files</strong>
        <span className="spacer" />
        <button className="ghost" onClick={load} title="Refresh">↻</button>
        <button onClick={() => picker.current?.click()}>Upload</button>
        <input ref={picker} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
      </header>
      <div className="path small muted">{path}</div>
      <ul>
        {path !== "." && <li><button className="ghost" onClick={() => setPath(path.split("/").slice(0, -1).join("/") || ".")}>..</button></li>}
        {entries.map((e) => (
          <li key={e.name}>
            <button className="ghost" onClick={() => (e.is_dir ? setPath(join(e.name)) : download(e.name))} title={e.is_dir ? "Open" : "Download"}>
              {e.is_dir ? "📁" : "📄"} {e.name}
            </button>
            {!e.is_dir && <span className="small muted">{fmt(e.size)}</span>}
          </li>
        ))}
        {entries.length === 0 && <li className="small muted">Empty</li>}
      </ul>
    </aside>
  );
}

const fmt = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);
