import { renderAsync } from "docx-preview";
import { useEffect, useRef, useState } from "react";

// inside the iframe: a light backdrop (not docx-preview's gray band) and pages with a soft shadow, like Google Docs
const LOOK = `<style>html,body{margin:0;background:#f1f3f4}.docx-wrapper{background:#f1f3f4!important;padding:16px!important}
.docx-wrapper>section.docx{box-shadow:0 1px 3px rgb(0 0 0/.12),0 4px 14px rgb(0 0 0/.08)!important;margin:0 auto 16px!important}</style>`;
const PAD = 32;  // the wrapper's padding, both sides

/** px width of the widest page (docx-preview writes "595.3pt"; a landscape section can be wider), 0 if unknown */
const px = (w: string) => { const n = parseFloat(w) || 0; return w.endsWith("pt") ? n * 96 / 72 : w.endsWith("in") ? n * 96 : w.endsWith("cm") ? n * 96 / 2.54 : n; };
const pageWidth = (doc: Document) => Math.max(0, ...[...doc.querySelectorAll<HTMLElement>("section.docx")].map((e) => px(e.style.width)));

/** docx-preview renders into a detached element (never our page); the HTML is shown in an iframe with no scripts and an opaque origin.
 * The iframe cannot be touched from here, so a page wider than the panel is fitted by scaling the iframe itself. */
export default function Docx({ data, onError }: { data: ArrayBuffer; onError: (e: unknown) => void }) {
  const [got, setGot] = useState<{ html: string; width: number }>();
  const box = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState({ w: 0, h: 0 });
  useEffect(() => {
    let live = true;
    const doc = document.implementation.createHTMLDocument("");
    renderAsync(data, doc.body, doc.head, { useBase64URL: true, inWrapper: true })
      .then(() => { doc.head.insertAdjacentHTML("beforeend", LOOK); if (live) setGot({ html: doc.documentElement.outerHTML, width: pageWidth(doc) }); },
        (e) => live && onError(e));
    return () => { live = false; };
  }, [data, onError]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setRoom({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [got]);
  if (!got) return <p className="muted small pad">Loading…</p>;
  const need = got.width + PAD, s = got.width && room.w && room.w < need ? room.w / need : 1;
  return (
    <div ref={box} className="docx-fit">
      <iframe className="frame" title="Document" sandbox="" srcDoc={got.html}
        style={!room.w ? { visibility: "hidden" }  // not measured yet: don't flash the page at full size
          : s < 1 ? { width: need, height: room.h / s, transform: `scale(${s})`, transformOrigin: "0 0" } : undefined} />
    </div>
  );
}
