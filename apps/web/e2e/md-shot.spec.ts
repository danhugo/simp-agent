import { readFileSync } from "node:fs";
import { test } from "@playwright/test";

// Not a real test: renders one message with every markdown element and saves light/dark screenshots. Run with SHOTS=dir.
const MD = `# Heading 1
## Heading 2
### Heading 3
#### Heading 4

A paragraph with **bold**, *italic*, \`inline code\` and a [link](https://example.com).

Second paragraph.

- One
- Two
  - Nested a
  - Nested b
- Three

1. First
2. Second
   1. Sub

> A blockquote with some wise words.

\`\`\`python
def hello():
    print("hi" * 100, "a very long line that should scroll horizontally inside the block ...........")
\`\`\`

| Name | Role | Score |
|------|------|------:|
| Ann | Dev | 10 |
| Bob | PM | 7 |
| Cy | QA | 9 |

---

![alt text](https://example.com/x.png)`;

for (const theme of ["light", "dark"]) {
  test(`md shot ${theme}`, async ({ page }) => {
    test.skip(!process.env.SHOTS);
    const token = readFileSync("/tmp/simp-e2e/token", "utf8").trim();
    await page.setViewportSize({ width: 900, height: 1500 });
    await page.addInitScript((t) => localStorage.setItem("simp.theme", t), theme);
    await page.goto("/");
    await page.click("text=Use an access token instead");
    await page.fill("input[aria-label=Token]", token);
    await page.click("text=Sign in");
    await page.fill("textarea", MD);
    await page.keyboard.press("Enter");
    const msg = page.locator(".msg.assistant").last();
    await msg.locator("table").waitFor();
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${process.env.SHOTS}/md-${theme}.png` });
  });
}
