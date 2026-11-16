import { expect, test } from "vitest";
import { ago } from "./Memory";

test("ago: relative times, then a date", () => {
  const now = 1_800_000_000;
  expect(ago(now - 20, now)).toBe("just now");
  expect(ago(now - 5 * 60, now)).toBe("5 min ago");
  expect(ago(now - 3 * 3600, now)).toBe("3 hours ago");
  expect(ago(now - 30 * 3600, now)).toBe("yesterday");
  expect(ago(now - 4 * 86400, now)).toBe("4 days ago");
  expect(ago(now - 60 * 86400, now)).not.toMatch(/ago/);
});
