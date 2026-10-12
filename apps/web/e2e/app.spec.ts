import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const token = () => readFileSync("/tmp/simp-e2e/token", "utf8").trim();
const last = (p: Page) => p.locator(".msg.assistant .md").last();
const badge = (p: Page) => p.locator(".chat header .badge");

async function login(p: Page) {
  await p.goto("/");
  await p.fill("input[aria-label=Token]", token());
  await p.click("text=Sign in");
  await p.click("text=New session");
}
async function say(p: Page, text: string) {
  await p.fill("textarea", text);
  await p.keyboard.press("Enter");
}

test("wrong token is rejected", async ({ page }) => {
  await page.goto("/");
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
  await page.click(".approval-card button:text('Allow')");
  await expect(last(page)).toContainText("Tool said: hi-from-tool");
  await expect(page.locator(".tool.done")).toHaveCount(1);
  await say(page, "tool again");
  await page.click(".approval-card button:text('Deny')");
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
  await page.click(".approval-card button:text('Allow')");
  await expect(last(page)).toContainText("Tool said: hi-from-tool");
});

test("Stop aborts", async ({ page }) => {
  await login(page);
  await say(page, "slow");
  await expect(page.locator(".streaming .md")).toContainText("w2 ");
  await page.click("button:text('Stop')");
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
  await page.click("text=Files");
  await page.setInputFiles("input[type=file]", { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await expect(page.locator(".files")).toContainText("notes.txt");
  const dl = page.waitForEvent("download");
  await page.click(".files >> text=notes.txt");
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
  const plan = page.locator(".chat header button:text('Plan')");
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
  await page.click(".chat header button:text('Compact')");
  await expect(page.locator(".notice").last()).toContainText("Context compacted");
  await expect(badge(page)).toHaveText("idle");
});

test("a new session gets a title in the sidebar", async ({ page }) => {
  await login(page);
  await say(page, "hello title");
  await expect(page.locator(".session.active")).toContainText("Fake title");
  await expect(page.locator(".chat header strong")).toHaveText("Fake title");
});
