import { renderAsync } from "docx-preview";
import { useEffect, useState } from "react";

/** docx-preview renders into a detached element (never our page); the HTML is shown in an iframe with no scripts and an opaque origin. */
export default function Docx({ data, onError }: { data: ArrayBuffer; onError: (e: unknown) => void }) {
  const [html, setHtml] = useState<string>();
  useEffect(() => {
    const doc = document.implementation.createHTMLDocument("");
    renderAsync(data, doc.body, doc.head, { useBase64URL: true, inWrapper: true })
      .then(() => setHtml(doc.documentElement.outerHTML), onError);
  }, [data, onError]);
  return html === undefined ? <p className="muted small pad">Loading…</p> : <iframe className="frame" title="Document" sandbox="" srcDoc={html} />;
}
