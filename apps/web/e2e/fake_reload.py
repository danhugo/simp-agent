"""Manual check vs `simp-server fake --delay 0.12` + `pnpm dev --port 5199`: reload mid-stream, approve after reload, files.
Run from the repo root: uv run --with playwright python apps/web/e2e/fake_reload.py"""
from playwright.sync_api import sync_playwright, expect
U = "http://127.0.0.1:5199"
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 800})
    pg.goto(U); pg.fill("input[aria-label=Token]", "dev-token"); pg.click("text=Sign in")
    pg.click("text=New session"); pg.fill("textarea", "List the files please"); pg.keyboard.press("Enter")
    pg.wait_for_selector(".streaming .md"); pg.wait_for_timeout(300)
    print("before reload 1:", repr(pg.inner_text(".streaming .md")))
    pg.screenshot(path="docs/screenshots/t3/1-streaming.png")
    pg.reload()
    pg.wait_for_selector(".approval-card")
    txt = pg.locator(".msg.assistant .md").first.inner_text()
    print("after reload 1:", repr(txt)); assert txt == "Let me look at the directory.", txt
    pg.screenshot(path="docs/screenshots/t3/2-approval-after-reload.png")
    pg.click(".approval-card button:text('Allow')")
    pg.wait_for_selector(".streaming .md"); pg.wait_for_timeout(500)
    print("before reload 2:", repr(pg.inner_text(".streaming .md")))
    pg.reload()
    expect(pg.locator(".chat header .badge")).to_have_text("idle", timeout=15000)
    final = pg.locator(".msg.assistant .md").last.inner_text()
    print("after reload 2:", repr(final)); assert final == "There are two entries: README.md and src.", final
    assert pg.locator(".tool.done").count() == 1
    pg.click("text=Files"); pg.set_input_files("input[type=file]", files=[{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello"}])
    pg.wait_for_selector(".files >> text=notes.txt")
    with pg.expect_download() as d: pg.click(".files >> text=notes.txt")
    assert open(d.value.path(), "rb").read() == b"hello"; print("download ok")
    pg.click("text=Dark theme"); pg.screenshot(path="docs/screenshots/t3/3-done-dark-files.png")
    b.close()
