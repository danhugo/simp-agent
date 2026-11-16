import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const token = () => readFileSync("/tmp/simp-e2e/token", "utf8").trim();
const sql = (q: string) => execFileSync("sqlite3", ["/tmp/simp-e2e/simp.db", q], { encoding: "utf8" });

test("memory page: list, edit, delete", async ({ page }) => {
  // the seeded user's default agent exists once they have signed in (any request creates it)
  await page.request.get("/api/memories", { headers: { Authorization: `Bearer ${token()}` } });
  const uid = sql("SELECT user_id FROM agents ORDER BY created LIMIT 1").trim();
  sql("DELETE FROM memories;" +
    `INSERT INTO memories VALUES('m1','${uid}',NULL,'global','Likes short answers',strftime('%s','now'),NULL);` +
    `INSERT INTO memories VALUES('m2','${uid}',(SELECT id FROM agents WHERE user_id='${uid}' ORDER BY created LIMIT 1),'agent','Uses uv for Python',strftime('%s','now'),'r1');`);

  await page.goto(`/#login=${token()}`);
  await page.getByRole("button", { name: "Memory" }).click();

  const about = page.getByRole("region", { name: "About you" });
  const learned = page.getByRole("region", { name: "What the agent learned" });
  await expect(about.locator(".mem-text")).toHaveText(["Likes short answers"]);
  await expect(learned.locator(".mem-text")).toHaveText(["Uses uv for Python"]);
  await expect(learned).toContainText("from a deleted chat");  // r1 is not a chat that exists

  await about.getByRole("button", { name: "Edit memory: Likes short answers" }).click();  // the visible Edit button
  await page.keyboard.press("Escape");
  await about.locator(".mem-text").click();  // clicking the text works too
  await page.fill("textarea[aria-label='Memory text']", "Likes very short answers");
  await page.click("text=Save");
  await expect(about.locator(".mem-text")).toHaveText(["Likes very short answers"]);

  await about.getByLabel("Add a memory").fill("Call me D");
  await about.getByRole("button", { name: "Add" }).click();
  await expect(about.locator(".mem-text")).toHaveText(["Call me D", "Likes very short answers"]);
  await expect(about.getByLabel("Add a memory")).toHaveValue("");

  const del = learned.getByRole("button", { name: "Delete memory" });
  await del.click();
  await expect(del).toHaveText("Delete?");
  await del.click();
  await expect(learned).toContainText("The agent has not saved anything yet.");
  expect(sql("SELECT content FROM memories ORDER BY created").trim().split("\n")).toEqual(["Likes very short answers", "Call me D"]);
});
