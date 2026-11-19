import { expect, test } from "vitest";
import { parseSetting, showSetting } from "./Admin";

test("parseSetting keeps the current value's type", () => {
  expect(parseSetting(" 2.5 ", 1)).toBe(2.5);
  expect(parseSetting("abc", 1)).toBe("abc");  // the server rejects it with a message
  expect(parseSetting("a@x.com, b@y.com\nc@z.com", [])).toEqual(["a@x.com", "b@y.com", "c@z.com"]);
  expect(parseSetting("", ["a"])).toEqual([]);
  expect(parseSetting(" fast ", "slow")).toBe("fast");
  expect(showSetting(["a", "b"])).toBe("a, b");
});
