import { expect, test } from "vitest";
import { parse } from "./Sheet";

test("csv parse", () => {
  expect(parse('a,b\n"x, y","say ""hi"""\r\n1,\n', ",")).toEqual([["a", "b"], ["x, y", 'say "hi"'], ["1", ""]]);
  expect(parse("a\tb\nc\td", "\t")).toEqual([["a", "b"], ["c", "d"]]);
});
