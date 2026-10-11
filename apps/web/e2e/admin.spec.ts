import { execFileSync } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";

// Stage 2 admin features against the real e2e server (serve.sh: SIMP_SERVER_HOME=/tmp/simp-e2e).
// Each test seeds its own user so rotating/revoking never touches the shared e2e token.
const cli = (...args: string[]) =>
  execFileSync("uv", ["run", "simp-server", ...args], { env: { ...process.env, SIMP_SERVER_HOME: "/tmp/simp-e2e" } })
    .toString().trim();

async function login(p: Page, token: string) {
  await p.goto("/");
  await p.fill("input[aria-label=Token]", token);
  await p.click("text=Sign in");
  await expect(p.locator("text=New session")).toBeVisible();
}

test("delete session: first click asks, second deletes", async ({ page }) => {
  await login(page, cli("seed", "--name", `del-${Date.now()}`));
  await page.click("text=New session");
  await page.click("text=New session");
  const rows = page.locator(".session-row");
  await expect(rows).toHaveCount(2);
  const del = rows.first().locator("button[aria-label='Delete session']");
  await del.click();
  await expect(del).toHaveText("Delete?");
  await expect(rows).toHaveCount(2);
  await del.click();
  await expect(rows).toHaveCount(1);
  await page.reload();
  await expect(page.locator(".session-row")).toHaveCount(1);
});

test("rotate then revoke: old token logged out, new one works until revoked", async ({ page }) => {
  const name = `rot-${Date.now()}`;
  const old = cli("seed", "--name", name);
  await login(page, old);
  const fresh = cli("rotate", "--name", name);
  await page.reload();  // next API call with the old token -> 401 -> back to login
  await expect(page.locator("input[aria-label=Token]")).toBeVisible();
  await login(page, fresh);
  expect(cli("users")).toContain(`${name}\tactive`);
  cli("revoke", "--name", name);
  expect(cli("users")).toContain(`${name}\trevoked`);
  await page.reload();
  await expect(page.locator("input[aria-label=Token]")).toBeVisible();
});
