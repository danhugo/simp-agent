import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const token = () => readFileSync("/tmp/simp-e2e/token", "utf8").trim();
async function login(p: Page, hash = "") {
  await p.goto("/" + hash);
  await p.click("text=Use an access token instead");
  await p.fill("input[aria-label=Token]", token());
  await p.click("text=Sign in");
}

test("connections: list (mocked API), disconnect, OAuth return message", async ({ page }) => {
  let conns = [{ app: "google", label: "Google", connected: true, email: "me@example.com", status: "ok" }];
  const deleted: string[] = [];
  await page.route("**/api/connections", (r) => r.fulfill({ json: conns }));
  await page.route("**/api/connections/*", (r) => {
    deleted.push(r.request().method() + " " + new URL(r.request().url()).pathname);
    conns = [{ app: "google", label: "Google", connected: false, email: null, status: null }];
    return r.fulfill({ json: { ok: true } });
  });
  await login(page, "#connections?ok=google");
  await expect(page.getByRole("status")).toHaveText("Your account is connected.");
  const card = page.getByRole("listitem", { name: "Google" });
  await expect(card).toContainText("Connected as me@example.com");

  const btn = card.getByRole("button", { name: "Disconnect" });
  await btn.click();
  await expect(btn).toHaveText("Disconnect?");
  await btn.click();
  await expect(card.getByRole("button", { name: "Connect" })).toBeVisible();
  expect(deleted).toEqual(["DELETE /api/connections/google"]);
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
