import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("idle chat: Simp comes out on the message box, keeps playing while you type, goes home when you send", async ({ page }) => {
  const token = readFileSync("/tmp/simp-e2e/token", "utf8").trim();
  await page.addInitScript(() => localStorage.setItem("simp.idleMs", "800"));
  await page.goto(`/#login=${token}`);
  await page.fill("textarea", "hi");
  await page.keyboard.press("Enter");
  await expect(page.locator(".idle-mascot")).toBeVisible();
  const simp = page.locator(".idle-simp.on canvas");
  await expect(simp).toBeAttached({ timeout: 5000 });
  await page.waitForTimeout(1500);
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/idle-simp.png` });
  await page.keyboard.type("again");
  await page.mouse.move(200, 200);
  await expect(simp).toBeAttached();  // typing and mouse moves don't send it home
  await page.evaluate(() => localStorage.setItem("simp.idleMs", "60000"));  // so it doesn't come straight back after the reply
  await page.keyboard.press("Enter");
  await expect(simp).toHaveCount(0);
});
