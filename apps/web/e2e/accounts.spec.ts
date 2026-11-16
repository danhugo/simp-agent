import { expect, test } from "@playwright/test";

test("login page: Google only, no password or sign-up", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
  await expect(page.locator(".login")).toHaveAttribute("action", "/api/auth/google/start");
  await expect(page.locator("input")).toHaveCount(0);
  await expect(page.locator("text=Create account")).toHaveCount(0);
});
