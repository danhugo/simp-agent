import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const token = () => readFileSync("/tmp/simp-e2e/token", "utf8").trim();
async function login(p: Page, hash = "") {
  await p.goto("/" + hash);
  await p.click("text=Use an access token instead");
  await p.fill("input[aria-label=Token]", token());
  await p.click("text=Sign in");
}

const APPS = [["gmail", "Gmail"], ["drive", "Google Drive"], ["calendar", "Google Calendar"]];
const apps = (connected: boolean, off: string[] = []) => APPS.map(([app, label]) => ({
  app, label, description: `${label} for the agent`, icon: app, provider: "google",
  connected, enabled: connected && !off.includes(app), email: connected ? "me@example.com" : null, status: connected ? "ok" : null,
}));

test("apps: connect state, toggle drive off/on, disconnect (mocked API)", async ({ page }) => {
  let connected = false, off: string[] = [];
  const calls: string[] = [];
  await page.route("**/api/apps", (r) => r.fulfill({ json: apps(connected, off) }));
  await page.route(/\/api\/(apps\/\w+\/\w+|connections\/google(\/start)?)$/, (r) => {
    const path = new URL(r.request().url()).pathname;
    calls.push(r.request().method() + " " + path);
    const m = path.match(/apps\/(\w+)\/(enable|disable)/);
    if (m) off = m[2] === "disable" ? [...off, m[1]] : off.filter((a) => a !== m[1]);
    if (path.endsWith("/start")) return r.fulfill({ json: { url: "/?oauth=1#apps?ok=google" } });
    if (r.request().method() === "DELETE") connected = false;
    return r.fulfill({ json: { ok: true } });
  });
  await login(page, "#apps");
  const available = page.getByRole("region", { name: "Available" });
  await expect(available.getByRole("listitem")).toHaveCount(3);
  await expect(page.getByRole("region", { name: "Connected" })).toHaveCount(0);

  connected = true;  // the fake OAuth "start" url returns straight to #apps?ok=google
  await available.getByRole("button", { name: "Connect Gmail" }).click();
  await expect(page.getByRole("status")).toHaveText("Your account is connected.");
  const on = page.getByRole("region", { name: "Connected" });
  await expect(on.getByRole("listitem")).toHaveCount(3);
  await expect(page.locator(".account-line")).toContainText("Google account: me@example.com");

  await on.getByRole("switch", { name: "Use Google Drive" }).click();
  const drive = available.getByRole("switch", { name: "Use Google Drive" });
  await expect(drive).toHaveAttribute("aria-checked", "false");
  await drive.click();
  await expect(on.getByRole("switch", { name: "Use Google Drive" })).toHaveAttribute("aria-checked", "true");

  const dis = page.locator(".account-line").getByRole("button", { name: "Disconnect" });
  await dis.click();
  await expect(dis).toHaveText("Disconnect?");
  await dis.click();
  await expect(available.getByRole("button", { name: "Connect Gmail" })).toBeVisible();
  expect(calls).toEqual(["POST /api/connections/google/start", "POST /api/apps/drive/disable", "POST /api/apps/drive/enable", "DELETE /api/connections/google"]);
});

test("approval card for an MCP tool shows app + action and readable args", async ({ page }) => {
  const headers = { Authorization: `Bearer ${token()}` };
  const [profile] = await (await page.request.get("/api/profiles", { headers })).json();
  const s = await (await page.request.post("/api/sessions", { headers, data: { profile } })).json();
  const snapshot = {
    type: "snapshot", last_seq: 0, run_state: "waiting_approval", title: "t",
    in_flight: { msg_id: null, thinking: "", text: "", tool_outputs: {} },
    pending_approval: { call_id: "c1", tool: "gmail__create_draft", args: { to: "a@b.c", subject: "Hi", body: "x".repeat(300) } },
  };
  await page.route(`**/api/sessions/${s.id}/events`, (r) =>
    r.fulfill({ headers: { "content-type": "text/event-stream" }, body: `data: ${JSON.stringify(snapshot)}\n\n` }));
  await login(page, `#${s.id}`);
  const card = page.locator(".approval-card");
  await expect(card).toContainText("Allow Gmail · create draft?");
  await expect(card.locator("li").first()).toHaveText("to: a@b.c");
  await expect(card.locator("pre")).toHaveCount(0);
  for (const n of ["Allow", "Always", "Deny"]) await expect(card.getByRole("button", { name: n })).toBeVisible();
});
