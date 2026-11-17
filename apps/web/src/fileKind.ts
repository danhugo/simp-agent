/** Which viewer a file opens in, by extension. "info" = file info + Download only. */
export type Kind = "code" | "markdown" | "image" | "sheet" | "docx" | "html" | "pdf" | "info";

const KINDS: Record<string, Kind> = {
  md: "markdown", markdown: "markdown", html: "html", htm: "html", pdf: "pdf", docx: "docx",
  csv: "sheet", tsv: "sheet", xlsx: "sheet", xls: "sheet",
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image", svg: "image", bmp: "image", ico: "image", avif: "image",
};
/** Text files shown in the code viewer. The value is the highlight.js language ("" = plain text). */
export const LANGS: Record<string, string> = {
  py: "python", js: "javascript", jsx: "javascript", mjs: "javascript", cjs: "javascript", ts: "typescript", tsx: "typescript",
  json: "json", sh: "bash", bash: "bash", zsh: "bash", css: "css", html: "xml", htm: "xml", xml: "xml", md: "markdown",
  yaml: "yaml", yml: "yaml", sql: "sql", txt: "", log: "", toml: "", ini: "", cfg: "", env: "", gitignore: "", csv: "", tsv: "",
};

export const ext = (name: string) => { const b = name.split("/").pop() ?? name, i = b.lastIndexOf("."); return i < 0 ? "" : b.slice(i + 1).toLowerCase(); };
export const kindOf = (name: string): Kind => KINDS[ext(name)] ?? (ext(name) in LANGS || !ext(name) ? "code" : "info");

const MB = 1024 * 1024;
/** Too big to fetch for preview: text over 2 MB, anything else over 20 MB. */
export const tooBig = (kind: Kind, size: number) => size > (kind === "code" || kind === "markdown" ? 2 * MB : 20 * MB);
/** Kinds with a Rendered/Raw switch (Raw = code viewer). */
export const hasRaw = (kind: Kind) => kind === "markdown" || kind === "html";
