import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { api, AuthError, type FileEntry } from "./api";
import { downloadFile, errorText, Md } from "./Chat";
import { fmt } from "./Files";
import { IconClose, IconDownload, IconFolder, IconRefresh, KindIcons } from "./icons";
import { ext, hasRaw, kindOf, LANGS, tooBig } from "./fileKind";

// each viewer is its own chunk, loaded only when a file needs it
const Code = lazy(() => import("./viewers/Code"));
const Sheet = lazy(() => import("./viewers/Sheet"));

type Loaded = { entry?: FileEntry; text?: string; data?: ArrayBuffer; img?: string; src?: string; noRender?: boolean };

/** One file, read-only. `writes` goes up each time the chat shows the agent wrote this file: then it reloads. */
export function Preview({ sid, path, writes, onClose, onError, filesOpen, onToggleFiles, children }: {
  sid: string; path: string; writes: number; onClose: () => void; onError: (e: unknown) => void;
  filesOpen?: boolean; onToggleFiles?: () => void; children?: ReactNode;  // children: the Files list, shown over the body
}) {
  const name = path.split("/").pop() || path, kind = kindOf(path);
  const [raw, setRaw] = useState(false);
  const [n, setN] = useState(0);  // refresh counter
  const [got, setGot] = useState<Loaded>();
  const [error, setError] = useState<string>();
  const [shown, setShown] = useState<string>();  // the iframe src that finished loading
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);
  useEffect(() => setRaw(false), [path]);

  useEffect(() => {
    let live = true, img: string | undefined;
    setGot(undefined); setError(undefined);
    (async () => {
      const i = path.lastIndexOf("/");
      const entry = (await api.files(sid, i < 0 ? "." : path.slice(0, i))).find((e) => e.name === name && !e.is_dir);
      if (!entry) throw new Error("File not found");
      const r: Loaded = { entry };
      if (!tooBig(kind, entry.size)) {
        if (kind === "code" || raw) r.text = await (await api.download(sid, path)).text();
        else if (kind === "html" || kind === "pdf" || kind === "office" || ext(path) === "svg") {
          // svg can hold scripts: load it from the preview origin, never as a blob on our origin
          const url = (await api.preview(sid)).base + path.split("/").map(encodeURIComponent).join("/") + `?${kind === "office" ? "render=html&" : ""}v=${n + writes}`;
          // ponytail: renders twice (probe + iframe); the probe needs CORS on the preview origin, without it we just show the iframe
          if (kind === "office" && (await fetch(url).catch(() => undefined))?.status === 503) r.noRender = true;
          else if (kind === "image") r.img = url; else r.src = url;
        } else if (kind === "image") {
          // our own raster type, never the server's; svg never comes here (see above)
          const b = await api.download(sid, path);
          r.img = img = URL.createObjectURL(new Blob([b], { type: `image/${({ jpg: "jpeg" } as Record<string, string>)[ext(path)] ?? ext(path)}` }));
        } else if (kind === "markdown") r.text = await (await api.download(sid, path)).text();
        else if (kind !== "info") r.data = await (await api.download(sid, path)).arrayBuffer();
      }
      if (live) setGot(r);
    })().catch((e) => live && fail(e));
    return () => { live = false; if (img) URL.revokeObjectURL(img); };
  }, [sid, path, name, kind, raw, n, writes, fail]);

  const e = got?.entry;
  const body = error ? <div className="error pad" role="alert">{error}</div>
    : !got ? <p className="muted small pad">Loading…</p>
    : e && (tooBig(kind, e.size) || kind === "info" || got.noRender) ? (
      <div className="preview-info pad">
        <p><strong>{name}</strong> · {fmt(e.size)}</p>
        <p className="muted small">{kind === "info" || got.noRender ? "No preview for this file type." : "This file is too big to preview."}</p>
        <button onClick={() => downloadFile(sid, path).catch(fail)}><IconDownload size={16} /> Download</button>
      </div>
    )
    : got.text !== undefined && (raw || kind === "code") ? <Code text={got.text} lang={LANGS[ext(path)] ?? ""} />
    : got.text !== undefined ? <div className="pad"><Md text={got.text} /></div>
    : got.img ? <div className="image-view"><img src={got.img} alt={name} /></div>
    : got.src ? <>
      {shown !== got.src && <p className="muted small pad">Loading…</p>}
      <iframe className="frame" title={name} src={got.src} onLoad={() => setShown(got.src)} hidden={shown !== got.src}
        sandbox={kind === "html" || kind === "office" ? "allow-scripts" : undefined} />
    </>
    : got.data && kind === "sheet" ? <Sheet data={got.data} tsv={ext(path) === "tsv"} /> : null;

  return (
    <aside className="files preview" aria-label={`Preview ${name}`}>
      <header>
        {onToggleFiles && (
          <button className="icon-btn" onClick={onToggleFiles} aria-expanded={!!filesOpen} aria-controls="preview-files" title="Files" aria-label="Files"><IconFolder size={16} /></button>
        )}
        {(() => { const K = KindIcons[kind]; return <K size={18} className="preview-kind" />; })()}
        <strong className="preview-name" title={path}>{name}</strong>
        {got?.entry && <span className="preview-size">{fmt(got.entry.size)}</span>}
        <span className="spacer" />
        {hasRaw(kind) && (
          <div className="seg" role="group" aria-label="View">
            <button aria-pressed={!raw} onClick={() => setRaw(false)}>Rendered</button>
            <button aria-pressed={raw} onClick={() => setRaw(true)}>Raw</button>
          </div>
        )}
        <button className="icon-btn" onClick={() => setN(n + 1)} title="Refresh" aria-label="Refresh"><IconRefresh size={16} /></button>
        <button className="icon-btn" onClick={() => downloadFile(sid, path).catch(fail)} title="Download" aria-label="Download"><IconDownload size={16} /></button>
        <button className="icon-btn" onClick={onClose} title="Close preview" aria-label="Close preview"><IconClose size={16} /></button>
      </header>
      {children && (
        <div className="files-pop" id="preview-files" onKeyDown={(e) => { if (e.key === "Escape") onToggleFiles?.(); }}>{children}</div>
      )}
      <div className="preview-body"><Suspense fallback={<p className="muted small pad">Loading…</p>}>{body}</Suspense></div>
    </aside>
  );
}
