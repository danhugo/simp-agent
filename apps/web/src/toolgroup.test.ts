import { expect, test } from "vitest";
import { groupSummary } from "./Chat";

const c = (name: string) => ({ id: name + Math.random(), name, arguments: {} });
test("groupSummary counts calls by kind in plain words", () => {
  expect(groupSummary([c("web_search"), c("web_search"), ...Array.from({ length: 18 }, () => c("web_fetch"))]))
    .toBe("Searched the web 2 times, opened 18 pages");
  expect(groupSummary([c("read"), c("bash"), c("bash")])).toBe("Read 1 file, ran 2 commands");
  expect(groupSummary([c("gmail__search"), c("gmail__read")])).toBe("Used Gmail 2 times");
});
