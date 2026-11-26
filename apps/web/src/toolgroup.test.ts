import { expect, test } from "vitest";
import { groupSummary } from "./Chat";

const c = (name: string) => ({ id: name + Math.random(), name, arguments: {} });
test("groupSummary counts calls by kind in plain words", () => {
  expect(groupSummary([c("web_search"), c("web_search"), ...Array.from({ length: 18 }, () => c("web_fetch"))]))
    .toBe("Searched the web 2 times, opened 18 pages");
  expect(groupSummary([c("read"), c("bash"), c("bash")])).toBe("Read 1 file, ran 2 commands");
  expect(groupSummary([c("gmail__search"), c("gmail__read")])).toBe("Used Gmail 2 times");
});

test("parallelBatches groups 2+ read-only calls in a row of one message", async () => {
  const { parallelBatches } = await import("./Chat");
  const [r1, r2, b, r3, s1, s2] = [c("read"), c("read"), c("bash"), c("read"), c("web_search"), c("web_search")];
  const m = parallelBatches([[r1, r2, b, r3], [s1, s2]], new Set(["read", "web_search"]));
  expect(m.get(r1.id)).toBe(m.get(r2.id));
  expect(m.has(b.id) || m.has(r3.id)).toBe(false);
  expect(m.get(s1.id)).toBe(m.get(s2.id));
  expect(m.get(s1.id)).not.toBe(m.get(r1.id));
});

test("parallelBatches follows the server's list: a tool it does not mark parallel is never grouped", async () => {
  const { parallelBatches } = await import("./Chat");
  const [d1, d2] = [c("web_download"), c("web_download")];
  expect(parallelBatches([[d1, d2]], new Set(["read"])).size).toBe(0);
  expect(parallelBatches([[d1, d2]], new Set(["web_download"])).get(d1.id)).toBe(1);
});
