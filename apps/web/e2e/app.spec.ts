import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const token = () => readFileSync("/tmp/simp-e2e/token", "utf8").trim();
const last = (p: Page) => p.locator(".msg.assistant .md").last();
const badge = (p: Page) => p.locator(".chat header .badge");

async function login(p: Page) {
  await p.goto("/");
  await p.click("text=Use an access token instead");
  await p.fill("input[aria-label=Token]", token());
  await p.click("text=Sign in");
  // New session only opens the hero now; tests that need a session before the first send get one via the API.
  const headers = { Authorization: `Bearer ${token()}` };
  const [profile] = await (await p.request.get("/api/profiles", { headers })).json();
  const s = await (await p.request.post("/api/sessions", { headers, data: { profile } })).json();
  await p.goto(`/#${s.id}`);
}
async function openMenuItem(p: Page, name: string) {
  await p.locator(".chat header").getByRole("button", { name: "More" }).click();
  await p.getByRole("menu", { name: "Session actions" }).getByRole(/^Files$/.test(name) ? "menuitemcheckbox" : "menuitem", { name }).click();
}
async function say(p: Page, text: string) {
  await p.fill("textarea", text);
  await p.keyboard.press("Enter");
}

test("wrong token is rejected", async ({ page }) => {
  await page.goto("/");
  await page.click("text=Use an access token instead");
  await page.fill("input[aria-label=Token]", "nope");
  await page.click("text=Sign in");
  await expect(page.locator(".login .error")).toHaveText("That token was not accepted.");
});

test("streaming answer", async ({ page }) => {
  await login(page);
  await say(page, "hello there");
  await expect(last(page)).toHaveText("Echo: hello there");
  await expect(badge(page)).toHaveText("idle");
});

test("tool call: Allow shows the result, Deny is reported", async ({ page }) => {
  await login(page);
  await say(page, "tool please");
  await page.locator(".approval-card").getByRole("button", { name: "Allow" }).click();
  await expect(last(page)).toContainText("Tool said: hi-from-tool");
  await expect(page.locator(".tool.done")).toHaveCount(1);
  await say(page, "tool again");
  await page.locator(".approval-card").getByRole("button", { name: "Deny" }).click();
  await expect(badge(page)).toHaveText("idle");
  await expect(page.locator(".tool").last()).toContainText("Decision: deny");
});

test("reload mid-stream continues with no gaps or dups; pending approval restored", async ({ page }) => {
  await login(page);
  await say(page, "slow");
  await expect(page.locator(".streaming .md")).toContainText("w3 ");
  await page.reload();
  await expect(last(page)).toHaveText(Array.from({ length: 40 }, (_, i) => `w${i}`).join(" "), { timeout: 15000 });
  await say(page, "tool");
  await expect(page.locator(".approval-card")).toBeVisible();
  await page.reload();
  await page.locator(".approval-card").getByRole("button", { name: "Allow" }).click();
  await expect(last(page)).toContainText("Tool said: hi-from-tool");
});

test("Stop aborts", async ({ page }) => {
  await login(page);
  await say(page, "slow");
  await expect(page.locator(".streaming .md")).toContainText("w2 ");
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(badge(page)).toHaveText("idle");
  await expect(page.locator(".notice.warning")).toHaveText("run aborted");
});

test("steer while running", async ({ page }) => {
  await login(page);
  await say(page, "slow");
  await expect(page.locator(".streaming .md")).toContainText("w1 ");
  await say(page, "turn left");
  await expect(last(page)).toHaveText("Echo: turn left", { timeout: 15000 });
  await expect(page.locator(".msg.user").last()).toHaveText("turn left");
});

test("steer shows at once as pending, then exactly once", async ({ page }) => {
  await login(page);
  await say(page, "slow");
  await expect(page.locator(".streaming .md")).toContainText("w1 ");
  await say(page, "go right");
  await expect(page.locator(".msg.user.pending")).toHaveText("go rightPending");
  await expect(page.locator(".streaming")).toBeVisible();  // still mid-turn
  await page.screenshot({ path: "test-results/pending-steer.png" });
  await expect(badge(page)).toHaveText("idle", { timeout: 15000 });
  await expect(page.locator(".msg.user", { hasText: "go right" })).toHaveCount(1);
  await expect(page.locator(".msg.user.pending")).toHaveCount(0);
});

test("a second tab sees the same events", async ({ page, context }) => {
  await login(page);
  const two = await context.newPage();
  await two.goto(page.url());
  await say(page, "slow");
  await expect(badge(two)).toHaveText("running");
  await expect(badge(page)).toHaveText("idle", { timeout: 15000 });
  await expect(last(two)).toHaveText(await last(page).innerText());
});

test("file upload, list, download", async ({ page }) => {
  await login(page);
  await openMenuItem(page, "Files");
  await page.setInputFiles(".files input[type=file]", { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await expect(page.locator(".files")).toContainText("notes.txt");
  const dl = page.waitForEvent("download");
  await page.locator(".files").getByRole("button", { name: "notes.txt" }).click();
  expect(readFileSync(await (await dl).path()!, "utf8")).toBe("hello");
});

test("budget: header shows spend", async ({ page }) => {
  await login(page);
  await say(page, "hello there");  // FakeLLM reports 1 input token -> $0.01 per call
  await expect(badge(page)).toHaveText("idle");
  await expect(page.locator(".chat header .spend")).toHaveText(/^\$0\.(0[1-9]|[1-9]\d) \/ \$1$/);
});

test("plan mode: toggle shows a notice and a tool call is blocked", async ({ page }) => {
  await login(page);
  const plan = page.locator(".composer").getByRole("button", { name: "Plan" });
  await plan.click();
  await expect(page.locator(".notice").last()).toHaveText("plan mode on");
  await expect(plan).toHaveAttribute("aria-pressed", "true");
  await say(page, "tool please");
  await expect(page.locator(".tool.error")).toContainText("plan mode is on");
  await expect(badge(page)).toHaveText("idle");
  await plan.click();
  await expect(page.locator(".notice").last()).toHaveText("plan mode off");
  await expect(plan).toHaveAttribute("aria-pressed", "false");
});

test("compact produces a compaction item", async ({ page }) => {
  await login(page);
  await say(page, "hello one");
  await expect(last(page)).toHaveText("Echo: hello one");
  await say(page, "hello two");
  await expect(last(page)).toHaveText("Echo: hello two");
  await openMenuItem(page, "Compact");
  await expect(page.locator(".notice").last()).toContainText("Context compacted");
  await expect(badge(page)).toHaveText("idle");
});

test("a new session gets a title in the sidebar", async ({ page }) => {
  await login(page);
  await say(page, "hello title");
  await expect(page.locator(".session.active")).toContainText("Fake title");
  await expect(page.locator(".chat header strong")).toHaveText("Fake title");
});

test("composer attach uploads to the workspace", async ({ page }) => {
  await login(page);
  await page.setInputFiles(".composer input[type=file]", { name: "att.txt", mimeType: "text/plain", buffer: Buffer.from("x") });
  await expect(page.locator(".attached")).toContainText("att.txt");
  await openMenuItem(page, "Files");
  await expect(page.locator(".files")).toContainText("att.txt");
});

test("header keeps only status; actions live in More", async ({ page }) => {
  await login(page);
  const header = page.locator(".chat header");
  for (const name of ["Plan", "Compact", "Files"]) await expect(header.getByRole("button", { name, exact: true })).toHaveCount(0);
  await header.getByRole("button", { name: "More" }).click();
  const menu = page.getByRole("menu", { name: "Session actions" });
  await expect(menu.getByRole("menuitemcheckbox", { name: "Notify when hidden" })).toHaveAttribute("aria-checked", "false");
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
});

test("model picker: pill opens a listbox, keyboard picks, Esc closes", async ({ page }) => {
  await login(page);
  await page.goto("/");
  const btn = page.locator(".model-btn");
  await btn.click();
  const list = page.getByRole("listbox", { name: "Model" });
  await expect(list).toBeVisible();
  await expect(list.locator('[aria-selected="true"]')).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(list).toBeHidden();
  await expect(btn).toHaveAttribute("aria-expanded", "false");
  await btn.click();
  await page.mouse.click(5, 5);
  await expect(list).toBeHidden();
});
