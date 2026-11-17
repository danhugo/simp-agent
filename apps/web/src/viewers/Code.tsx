import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

for (const [n, l] of Object.entries({ bash, css, javascript, json, markdown, python, sql, typescript, xml, yaml })) hljs.registerLanguage(n, l);

/** Line numbers + highlight.js (its output escapes the source, so the HTML is safe). */
export default function Code({ text, lang }: { text: string; lang: string }) {
  const html = lang && hljs.getLanguage(lang) ? hljs.highlight(text, { language: lang }).value : undefined;
  const n = text.split("\n").length;
  return (
    <div className="code-view">
      <pre className="gutter" aria-hidden="true">{Array.from({ length: n }, (_, i) => i + 1).join("\n")}</pre>
      {html !== undefined ? <pre><code className="hljs" dangerouslySetInnerHTML={{ __html: html }} /></pre> : <pre><code>{text}</code></pre>}
    </div>
  );
}
