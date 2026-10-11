import { expect, test } from "@playwright/test";

// serve.sh sets signup_code = "e2e-code".
test("create account, sign out, sign in with password", async ({ page }) => {
  const name = `acct-${Date.now()}`;
  await page.goto("/");
  await page.click("text=Create account");
  await page.fill("input[aria-label=Username]", name);
  await page.fill("input[aria-label=Password]", "password123");
  await page.fill("input[aria-label='Invite code']", "e2e-code");
  await page.click("button:text('Create account')");
  await expect(page.locator("text=New session")).toBeVisible();

  await page.click("text=Sign out");
  await expect(page.locator("input[aria-label=Username]")).toBeVisible();
  await page.fill("input[aria-label=Username]", name);
  await page.fill("input[aria-label=Password]", "wrong-password");
  await page.click("button:text('Sign in')");
  await expect(page.locator(".login .error")).toHaveText("Wrong username or password.");
  await page.fill("input[aria-label=Password]", "password123");
  await page.click("button:text('Sign in')");
  await expect(page.locator("text=New session")).toBeVisible();
});

test("wrong invite code is refused", async ({ page }) => {
  await page.goto("/");
  await page.click("text=Create account");
  await page.fill("input[aria-label=Username]", `nope-${Date.now()}`);
  await page.fill("input[aria-label=Password]", "password123");
  await page.fill("input[aria-label='Invite code']", "wrong");
  await page.click("button:text('Create account')");
  await expect(page.locator(".login .error")).toContainText("invite code");
});
