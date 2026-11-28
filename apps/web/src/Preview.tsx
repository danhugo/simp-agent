import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, AuthError, type FileEntry } from "./api";
import { downloadFile, errorText, Md } from "./Chat";
import { fmt } from "./Files";
import { IconClose, IconDownload, IconFolder, IconRefresh } from "./icons";
import { Maximize2, Minimize2 } from "lucide-react";
import { ext, hasRaw, kindOf, LANGS, tooBig } from "./fileKind";

// each viewer is its own chunk, loaded only when a file needs it
const Code = lazy(() => import("./viewers/Code"));
const Sheet = lazy(() => import("./viewers/Sheet"));

type Built = { view: string; file?: string; label: string; source: string };  // preview, office file, source
type Loaded = { entry?: FileEntry; text?: string; data?: ArrayBuffer; img?: string; src?: string; deck?: Built };

/** A source and what office_build made from it, side by side: show the preview, offer the office file.
 * name.jsx + name.html (+ name.pptx): a React deck, its .html is a slide viewer.
 * name.md + name.pdf (+ name.docx): a document, its .pdf shows the pages. */
function deckOf(path: string, siblings: FileEntry[]): Built | undefined {
  const m = /^(.*)\.(pptx|jsx|html|docx|md|pdf)$/i.exec(path);
  if (!m) return undefined;
  const base = m[1].split("/").pop()!, has = (x: string) => siblings.some((e) => e.name === `${base}.${x}` && !e.is_dir);
  const dir = path.slice(0, path.length - path.split("/").pop()!.length), at = (x: string) => `${dir}${base}.${x}`;
  const e = m[2].toLowerCase();
  if (["pptx", "jsx", "html"].includes(e) && has("jsx") && has("html"))
    return { view: at("html"), file: has("pptx") ? at("pptx") : undefined, label: "PPTX", source: at("jsx") };
  if (["docx", "md", "pdf"].includes(e) && has("md") && has("pdf") && has("docx"))
    return { view: at("pdf"), file: at("docx"), label: "DOCX", source: at("md") };
  return undefined;
}

/** One file, read-only. `writes` goes up each time the chat shows the agent wrote this file: then it reloads. */
export function Preview({ sid, path, writes, onClose, onError, filesOpen, onToggleFiles, children }: {
  sid: string; path: string; writes: number; onClose: () => void; onError: (e: unknown) => void;
  filesOpen?: boolean; onToggleFiles?: () => void; children?: ReactNode;  // children: the Files list, shown over the body
}) {
  const name = path.split("/").pop() || path, kind = kindOf(path);
  const [wide, setWide] = useState(false);  // the panel over the whole app (chat hidden); Esc or the button again
  useEffect(() => {
    if (!wide) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setWide(false); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [wide]);
  const [raw, setRaw] = useState(false);
  const [n, setN] = useState(0);  // refresh counter
  const [got, setGot] = useState<Loaded>();
  const [error, setError] = useState<string>();
  const [shown, setShown] = useState<string>();  // the iframe src that finished loading
  const frame = useRef<HTMLIFrameElement>(null);
  // a deck presents full screen: the frame can't go full screen by itself, so the viewer asks us (or our button does)
  const present = useCallback(() => { frame.current?.requestFullscreen?.().catch(() => {}); }, []);
  useEffect(() => {
    const ask = (e: MessageEvent) => { if (e.source === frame.current?.contentWindow && e.data?.simpDeck === "present") present(); };
    const tell = () => frame.current?.contentWindow?.postMessage({ simpDeck: "presenting", on: document.fullscreenElement === frame.current }, "*");
    window.addEventListener("message", ask); document.addEventListener("fullscreenchange", tell);
    return () => { window.removeEventListener("message", ask); document.removeEventListener("fullscreenchange", tell); };
  }, [present]);
  const fail = useCallback((e: unknown) => { onError(e); if (!(e instanceof AuthError)) setError(errorText(e)); }, [onError]);
  useEffect(() => setRaw(false), [path]);

  useEffect(() => {
    let live = true, img: string | undefined;
    setGot(undefined); setError(undefined);
    (async () => {
      const i = path.lastIndexOf("/");
      const siblings = await api.files(sid, i < 0 ? "." : path.slice(0, i));
      const entry = siblings.find((e) => e.name === name && !e.is_dir);
      if (!entry) throw new Error("File not found");
      const built = deckOf(path, siblings);
      const r: Loaded = { entry, deck: built };
      if (raw && built) r.text = await (await api.download(sid, built.source)).text();  // Raw: the source it came from
      else if (built) {  // a deck's own viewer page, or a document's pages (pdf), from the preview origin
        r.src = (await api.preview(sid)).base + built.view.split("/").map(encodeURIComponent).join("/") + `?v=${n + writes}`;
      } else if (!tooBig(kind, entry.size)) {
        if (kind === "code" || raw) r.text = await (await api.download(sid, path)).text();
        else if (kind === "html" || kind === "pdf" || kind === "office" || ext(path) === "svg") {
          // svg can hold scripts: load it from the preview origin, never as a blob on our origin
          const url = (await api.preview(sid)).base + path.split("/").map(encodeURIComponent).join("/") + `?${kind === "office" ? "render=html&" : ""}v=${n + writes}`;
          // a failed office render comes back as a short page inside the frame (the header has Download)
          if (kind === "image") r.img = url; else r.src = url;
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
    : !got ? <Skeleton name={path} />
    : e && (tooBig(kind, e.size) || kind === "info") ? (
      <div className="preview-info pad">
        <p><strong>{name}</strong> · {fmt(e.size)}</p>
        <p className="muted small">{kind === "info" ? "No preview for this file type." : "This file is too big to preview."}</p>
        <button onClick={() => downloadFile(sid, path).catch(fail)}><IconDownload size={16} /> Download</button>
      </div>
    )
    : got.text !== undefined && (raw || kind === "code") ? <Code text={got.text} lang={LANGS[ext(path)] ?? ""} />
    : got.text !== undefined ? <div className="pad"><Md text={got.text} /></div>
    : got.img ? <div className="image-view"><img src={got.img} alt={name} /></div>
    : got.src ? <>
      {shown !== got.src && <Skeleton name={path} />}
      <iframe ref={frame} className="frame fade-in" title={name} src={got.src} onLoad={() => setShown(got.src)} hidden={shown !== got.src}
        sandbox={got.deck ? (got.deck.view.endsWith(".html") ? "allow-scripts" : undefined)  // a pdf can't show sandboxed
          : kind === "html" || kind === "office" ? "allow-scripts" : undefined}
        allow={got.deck ? "fullscreen" : undefined} />
    </>
    : got.data && kind === "sheet" ? <Sheet data={got.data} tsv={ext(path) === "tsv"} /> : null;

  return (
    <aside className={`files preview${wide ? " wide" : ""}`} aria-label={`Preview ${name}`}>
      <header>
        {onToggleFiles && (
          <button className="icon-btn" onClick={onToggleFiles} aria-expanded={!!filesOpen} aria-controls="preview-files" title="Files" aria-label="Files"><IconFolder size={16} /></button>
        )}
        <strong className="preview-name" title={path}>{name}</strong>
        {got?.entry && <span className="preview-size">{fmt(got.entry.size)}</span>}
        <span className="spacer" />
        {got?.deck?.file && (
          <button className="ghost small" onClick={() => downloadFile(sid, got.deck!.file!).catch(fail)} title={`Download the ${got.deck.label} file`}>
            <IconDownload size={14} /> {got.deck.label}</button>
        )}
        {(hasRaw(kind) || got?.deck || /\.(jsx|md)$/i.test(path)) && (
          <div className="seg" role="group" aria-label="View">
            <button aria-pressed={!raw} onClick={() => setRaw(false)}>Rendered</button>
            <button aria-pressed={raw} onClick={() => setRaw(true)}>Raw</button>
          </div>
        )}
        <button className="icon-btn" onClick={() => setWide(!wide)} aria-pressed={wide}
          title={wide ? "Back to the side panel (Esc)" : "Expand to the whole window"} aria-label={wide ? "Shrink preview" : "Expand preview"}>
          {wide ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button>
        <button className="icon-btn" onClick={() => setN(n + 1)} title="Refresh" aria-label="Refresh"><IconRefresh size={16} /></button>
        <button className="icon-btn" onClick={() => downloadFile(sid, path).catch(fail)} title="Download" aria-label="Download"><IconDownload size={16} /></button>
        <button className="icon-btn" onClick={onClose} title="Close preview" aria-label="Close preview"><IconClose size={16} /></button>
      </header>
      {children && (
        <div className="files-pop" id="preview-files" onKeyDown={(e) => { if (e.key === "Escape") onToggleFiles?.(); }}>{children}</div>
      )}
      <div className="preview-body"><Suspense fallback={<Skeleton name={path} />}>{body}</Suspense></div>
    </aside>
  );
}

/** A placeholder shaped like the file while it loads; after 1.5 s it says the first render can take a moment. */
function Skeleton({ name }: { name: string }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => { const t = setTimeout(() => setSlow(true), 1500); return () => clearTimeout(t); }, []);
  const x = ext(name), k = kindOf(name);
  const shape = ["pptx", "ppt", "key", "odp"].includes(x) ? "slide"
    : ["xlsx", "xls", "ods", "csv", "tsv"].includes(x) ? "grid"
    : k === "image" ? "image" : k === "code" || k === "markdown" ? "lines" : "page";
  return (
    <div className={`skeleton ${shape}`} role="status" aria-label="Loading preview">
      {shape === "grid" ? (
        <div className="sheet">{Array.from({ length: 48 }, (_, i) => <i key={i} />)}</div>
      ) : shape === "slide" ? (
        <>{[0, 1].map((n) => <div key={n} className="sheet"><i /><i /><i /></div>)}</>
      ) : (
        <div className="sheet">{Array.from({ length: shape === "image" ? 0 : 7 }, (_, i) => <i key={i} />)}</div>
      )}
      {slow && <p className="muted small">Đang chuẩn bị bản xem…</p>}
    </div>
  );
}
