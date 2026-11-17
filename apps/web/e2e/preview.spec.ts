import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const token = () => readFileSync("/tmp/simp-e2e/token", "utf8").trim();
// a 1x1 red png
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==", "base64");
const FILES: Record<string, Buffer> = {
  "app.py": Buffer.from('def hello(name: str) -> str:\n    """Say hi."""\n    return f"hi {name}"  # greet\n'),
  "README.md": Buffer.from("# Title\n\nSome **bold** text.\n\n- one\n- two\n"),
  "dot.png": PNG,
  "pic.svg": Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4" fill="red"/></svg>'),
  "data.csv": Buffer.from("name,age\nAnn,31\nBo,42\n"),
  "site/index.html": Buffer.from('<link rel="stylesheet" href="style.css"><h1>Hello page</h1>'),
  "site/style.css": Buffer.from("h1 { color: rgb(255, 0, 0); }"),
  "wide.docx": readFileSync(new URL("./fixtures/wide.docx", import.meta.url)),  // a 12.5 in wide page
  "deck.pptx": Buffer.from("pptx"), "book.xlsx": Buffer.from("xlsx"), "old.pptx": Buffer.from("pptx"),  // the server renders these (stubbed)
};

async function setup(p: Page) {
  const headers = { Authorization: `Bearer ${token()}` };
  const [profile] = await (await p.request.get("/api/profiles", { headers })).json();
  const s = await (await p.request.post("/api/sessions", { headers, data: { profile } })).json();
  for (const [path, data] of Object.entries(FILES))
    await p.request.put(`/api/sessions/${s.id}/files/raw?path=${encodeURIComponent(path)}`, { headers, data });
  // stub of the preview API (server task t_5b969dab): a fake preview origin that serves the workspace files
  await p.route(`**/api/sessions/${s.id}/preview`, (r) => r.fulfill({ json: { base: "http://127.0.0.1:5198/__preview/tok/" } }));
  await p.route("**/__preview/tok/**", (r) => {
    const u = new URL(r.request().url()), path = u.pathname.replace("/__preview/tok/", "");
    // stub of OfficeCLI (server task): ?render=html -> HTML; old.pptx -> 503 (no renderer)
    if (u.searchParams.get("render") === "html") return r.fulfill(path === "old.pptx"
      ? { status: 503, body: "no renderer", headers: { "access-control-allow-origin": "*" } }
      : { body: `<h1>Rendered ${path}</h1>`, contentType: "text/html", headers: { "access-control-allow-origin": "*" } });
    r.fulfill({ body: FILES[path], contentType: path.endsWith(".css") ? "text/css" : path.endsWith(".svg") ? "image/svg+xml" : "text/html" });
  });
  await p.emulateMedia({ colorScheme: "light" });
  await p.goto(`/#login=${token()}`);
  await p.evaluate(() => localStorage.setItem("simp.theme", "light"));
  await p.goto(`/#${s.id}`);
  await p.locator(".chat header").getByRole("button", { name: "More" }).click();
  await p.getByRole("menu", { name: "Session actions" }).getByRole("menuitemcheckbox", { name: "Files" }).click();
}
const open = async (p: Page, name: string) => {
  const list = p.getByRole("complementary", { name: "Files", exact: true });
  if (!(await list.isVisible())) {  // a preview is open: Files is a list inside it, opened from its header
    await p.locator(".preview header").getByRole("button", { name: "Files" }).click();
  }
  await list.getByRole("button", { name, exact: true }).click();
  return p.getByRole("complementary", { name: `Preview ${name}` });
};

test("preview: py, md, png, office, csv, html", async ({ page }) => {
  await setup(page);

  let pv = await open(page, "app.py");
  await expect(page.locator(".app")).toHaveClass(/collapsed/);  // the sidebar folds to give the preview room
  await expect(page.getByRole("complementary", { name: "Files", exact: true })).toHaveCount(0);  // one side panel
  await expect(pv.locator(".code-view .gutter")).toHaveText("1\n2\n3\n4");
  await expect(pv.locator(".hljs-keyword").first()).toHaveText("def");
  await page.screenshot({ path: "test-results/preview-py.png" });

  pv = await open(page, "README.md");
  await expect(pv.locator(".md h1")).toHaveText("Title");
  await page.screenshot({ path: "test-results/preview-md.png" });
  await pv.getByRole("button", { name: "Raw" }).click();
  await expect(pv.locator(".code-view")).toContainText("# Title");

  pv = await open(page, "dot.png");
  await expect(pv.locator("img")).toHaveJSProperty("naturalWidth", 1);
  await page.screenshot({ path: "test-results/preview-png.png" });

  // svg can hold scripts: it must come from the preview origin, never a blob on our origin
  pv = await open(page, "pic.svg");
  await expect(pv.locator("img")).toHaveAttribute("src", /^http:\/\/127\.0\.0\.1:5198\/__preview\/tok\/pic\.svg\?v=/);
  await expect(pv.locator("img")).toHaveJSProperty("naturalWidth", 4);

  for (const f of ["wide.docx", "deck.pptx", "book.xlsx"]) {  // office files: the server's HTML, sandboxed
    pv = await open(page, f);
    const doc = pv.locator("iframe");
    await expect(doc).toHaveAttribute("sandbox", "allow-scripts");
    await expect(doc).toHaveAttribute("src", new RegExp(`/__preview/tok/${f.replace(".", "\\.")}\\?render=html&v=`));
    await expect(doc.contentFrame().getByText(`Rendered ${f}`)).toBeVisible();
    await page.screenshot({ path: `test-results/preview-${f.split(".")[1]}.png` });
  }
  pv = await open(page, "old.pptx");  // 503: no renderer on the server
  await expect(pv.getByText("No preview for this file type.")).toBeVisible();
  await expect(pv.locator(".preview-info").getByRole("button", { name: "Download" })).toBeVisible();
  await page.screenshot({ path: "test-results/preview-503.png" });

  pv = await open(page, "data.csv");
  await expect(pv.locator("th")).toHaveText(["name", "age"]);
  await expect(pv.locator("tr").nth(2)).toHaveText("Bo42");
  await page.screenshot({ path: "test-results/preview-csv.png" });

  await page.locator(".preview header").getByRole("button", { name: "Files" }).click();
  await page.screenshot({ path: "test-results/preview-files.png" });
  const files = page.getByRole("complementary", { name: "Files", exact: true });
  await expect(files.getByRole("navigation", { name: "Folder" })).toHaveText("work");  // the root shows as "work", not "."
  await expect(files.locator('li[aria-current="true"]')).toContainText("data.csv");  // the open file is marked
  await expect(files.getByRole("button", { name: "data.csv" })).toHaveAttribute("title", "data.csv");  // full name on hover
  await files.getByRole("button", { name: "site" }).click();
  await expect(files.getByRole("navigation", { name: "Folder" })).toHaveText("work/site");
  await page.screenshot({ path: "test-results/files-crumb.png" });
  await files.getByRole("navigation", { name: "Folder" }).getByRole("button", { name: "work" }).click();  // back to the root
  await expect(files.getByRole("navigation", { name: "Folder" })).toHaveText("work");
  await files.getByRole("button", { name: "site" }).click();
  pv = await open(page, "index.html");
  const frame = pv.locator("iframe");
  await expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  await expect(frame.contentFrame().locator("h1")).toHaveCSS("color", "rgb(255, 0, 0)");  // style.css next to it loaded
  await page.screenshot({ path: "test-results/preview-html.png" });
  await pv.getByRole("button", { name: "Raw" }).click();
  await expect(pv.locator(".code-view")).toContainText('<h1>Hello page</h1>');

  await pv.getByRole("button", { name: "Close preview" }).click();
  await expect(pv).toHaveCount(0);
  await expect(page.locator(".app")).not.toHaveClass(/collapsed/);  // back as it was
});
