"""Office benchmark: real agent runs that make decks, documents and workbooks; time, turns, cost and output checks.

    uv run python apps/server/scripts/office_bench.py --cases all --parallel 3 --out /tmp/bench

Starts `simp-server run` on a free port with a throwaway SIMP_SERVER_HOME: the local Docker sandbox (image
simp-sandbox:office, bind-mounted workspaces), and the chat profile copied from ~/.simp-server (keys from its .env).
Each case gets its own user (own sandbox), sends one prompt, waits for the run to end, then checks the produced file
with officecli on the host (validate + issues) and renders pptx/docx page grids into --out for a look.
Prints one row per case and p50/p95 per kind."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[3]
HOME_SRC = Path("~/.simp-server").expanduser()

CASES = {
    "deck-vi-10": ("pptx", "Làm cho tôi bộ slide 10 trang giới thiệu về lịch sử và văn hoá cà phê Việt Nam."),
    "deck-en-10": ("pptx", "Make a 10-slide deck pitching an AI note-taking app for doctors to seed investors."),
    "deck-vi-15": ("pptx", "Tạo slide 15 trang về chuyển đổi số trong ngân hàng Việt Nam: hiện trạng, số liệu, thách thức, đề xuất."),
    "deck-en-20": ("pptx", "Create a 20-slide training deck on cybersecurity basics for new employees."),
    "deck-anime": ("pptx", "làm slide 10 trang về Demon Slayer"),
    "doc-vi": ("docx", "Viết báo cáo khoảng 4 trang (file Word) về thị trường xe điện Việt Nam 2025, có bảng số liệu."),
    "doc-en": ("docx", "Write a 2-page project proposal (Word) for a community composting program, with a budget table."),
    "xlsx-sales": ("xlsx", "Tạo file Excel 10 sheet: doanh số 12 tháng cho 9 chi nhánh (mỗi chi nhánh 1 sheet, có doanh thu, chi phí, lợi nhuận, biên lợi nhuận bằng công thức và biểu đồ) và 1 sheet tổng hợp có biểu đồ."),
    "xlsx-budget": ("xlsx", "Build a 10-sheet household budget workbook for 2026: one sheet per category (housing, food, transport, utilities, health, education, savings, leisure, misc) with monthly plan vs actual, variance formulas and a chart, plus a dashboard sheet with totals and charts."),
}


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def settings(home: Path, profile: str, effort: str | None, turns: int, run_usd: float) -> None:
    import tomllib
    src = tomllib.loads((HOME_SRC / "settings.toml").read_text())
    p = dict(src["profiles"][profile])
    p.setdefault("price_in", 0.051)
    p.setdefault("price_out", 0.567)
    p["vision"] = True
    lines = [f'default_profile = "bench"', f'title_profile = "bench"', "allow_local_sandbox = true", "",
             "[profiles.bench]"]
    for k, v in p.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {json.dumps(v)}")
    lines += ["[profiles.bench.compat]"] + ([f'reasoning_effort = "{effort}"'] if effort else [])
    for k, v in (p.get("compat") or {}).items():
        if k != "reasoning_effort":
            lines.append(f"{k} = {json.dumps(v)}")
    lines += ["", "[budget]", f"run_usd = {run_usd}", f"run_turns = {turns}", "",
              "[workspace]", 'store = "local"', "",
              "[sandbox]", 'kind = "docker"', 'image = "simp-sandbox:office"', 'mount = "bind"', "cpus = 2",
              "memory_mb = 2048", "max_running = 12", "day_minutes = 100000"]
    (home / "settings.toml").write_text("\n".join(lines) + "\n")
    env = (HOME_SRC / ".env").read_text().splitlines()
    keep = [ln for ln in env if ln.split("=", 1)[0] in (p.get("api_key_env", ""), "TAVILY_API_KEY")]
    (home / ".env").write_text("\n".join(keep) + "\n")


async def seed(home: Path, n: int) -> list[str]:
    sys.path.insert(0, str(REPO / "apps/server/src"))
    from simp_server.store import SqliteStore
    s = SqliteStore({"data_dir": str(home)})
    await s.open()
    try:
        return [await s.add_user(f"bench{i}") for i in range(n)]
    finally:
        await s.close()


async def one(c: httpx.AsyncClient, token: str, name: str, prompt: str, timeout: float) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    r = {"case": name, "ok": False, "secs": None, "turns": 0, "tools": 0, "notices": [], "text": "", "sid": None}
    s = await c.post("/api/sessions", json={}, headers=h)
    s.raise_for_status()
    sid = r["sid"] = s.json()["id"]
    async with c.stream("GET", f"/api/sessions/{sid}/events", headers=h, timeout=None) as ev:
        lines = ev.aiter_lines()
        async for line in lines:
            if line.startswith("data:") and json.loads(line[5:])["type"] == "snapshot":
                break
        t0 = time.perf_counter()
        pr = await c.post(f"/api/sessions/{sid}/commands", json={"type": "prompt", "text": prompt}, headers=h)
        pr.raise_for_status()
        running = False

        async def read():
            nonlocal running
            async for line in lines:
                if not line.startswith("data:"):
                    continue
                e = json.loads(line[5:])
                t = e["type"]
                if t == "assistant_message":
                    r["turns"] += 1
                    r["tools"] += len(e.get("tool_calls") or [])
                    r["text"] = e.get("text") or r["text"]
                elif t == "notice":
                    r["notices"].append(e.get("text"))
                elif t == "run_state":
                    running = running or e["state"] == "running"
                    if e["state"] in ("idle", "error") and running:
                        r["secs"], r["ok"] = time.perf_counter() - t0, e["state"] == "idle"
                        return
        try:
            await asyncio.wait_for(read(), timeout)
        except TimeoutError:
            r["notices"].append("bench timeout")
            r["secs"] = timeout
    return r


def check(kind: str, path: Path, out: Path, name: str) -> dict:
    q = {"file": str(path), "valid": None, "issues": None, "pages": None}
    if not path:
        return q
    v = subprocess.run(["officecli", "validate", str(path)], capture_output=True, text=True).stdout
    q["valid"] = "passed" in v.lower()
    iss = subprocess.run(["officecli", "view", str(path), "issues"], capture_output=True, text=True).stdout
    q["issues"] = sum(1 for ln in iss.splitlines() if ln.strip().startswith("["))
    q["issue_lines"] = [ln.strip() for ln in iss.splitlines() if ln.strip().startswith("[")][:8]
    if kind == "pptx":
        o = subprocess.run(["officecli", "view", str(path), "outline"], capture_output=True, text=True).stdout
        q["pages"] = o.count("├── Slide") + o.count("└── Slide")
    if kind in ("pptx", "docx"):
        png = out / f"{name}.png"
        try:
            subprocess.run(["officecli", "view", str(path), "screenshot", "--grid", "4", "-o", str(png)],
                           capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            pass
    subprocess.run(["officecli", "close", str(path)], capture_output=True)
    return q


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else float("nan")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default="all", help="comma list or 'all' or a kind (pptx/docx/xlsx)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--profile", default="deepseek")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--turns", type=int, default=20)
    ap.add_argument("--run-usd", type=float, default=2.0)
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--out", default=None)
    ap.add_argument("--keep", action="store_true", help="keep the server home")
    a = ap.parse_args()
    names = list(CASES) if a.cases == "all" else [n for n in CASES if CASES[n][0] == a.cases] or a.cases.split(",")
    jobs = [(n, i) for i in range(a.repeat) for n in names]
    out = Path(a.out or tempfile.mkdtemp(prefix="office-bench-"))
    out.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="simp-bench-"))
    settings(home, a.profile, a.effort, a.turns, a.run_usd)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    exe = shutil.which("simp-server", path=str(REPO / ".venv" / "bin")) or "simp-server"
    log = open(home / "server.log", "w")
    try:  # macOS Pythons ship no CA bundle (Linux servers use the system one)
        import certifi
        certs = {"SSL_CERT_FILE": certifi.where()}
    except ImportError:
        certs = {}
    srv = subprocess.Popen([exe, "run", "--port", str(port)], env={**os.environ, **certs, "SIMP_SERVER_HOME": str(home)},
                           cwd=REPO, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        for _ in range(150):
            try:
                if httpx.get(base + "/api/me").status_code == 401:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            raise SystemExit(f"server did not start:\n{(home / 'server.log').read_text()[-3000:]}")
        tokens = asyncio.run(seed(home, len(jobs)))
        print(f"server {base}, home {home}, out {out}, {len(jobs)} runs, parallel {a.parallel}", flush=True)

        async def run_all():
            sem = asyncio.Semaphore(a.parallel)
            async with httpx.AsyncClient(base_url=base, timeout=60) as c:
                async def go(k, job):
                    async with sem:
                        n, i = job
                        r = await one(c, tokens[k], n, CASES[n][1], a.timeout)
                        r["case"] = f"{n}#{i}" if a.repeat > 1 else n
                        print(f"  done {r['case']}: {r['secs']:.0f}s {r['turns']} turns {r['notices']}", flush=True)
                        return r
                return await asyncio.gather(*(go(k, j) for k, j in enumerate(jobs)))
        results = asyncio.run(run_all())
        db = sqlite3.connect(home / "simp.db")
        ws_root = home / "workspaces"
        rows = []
        for r in results:
            kind = CASES[r["case"].split("#")[0]][0]
            u = db.execute("select count(*), coalesce(sum(cost),0), coalesce(sum(input),0), coalesce(sum(output),0) "
                           "from usage where session_id=?", (r["sid"],)).fetchone()
            uid = db.execute("select user_id from sessions where id=?", (r["sid"],)).fetchone()[0]
            files = sorted((ws_root / uid).rglob(f"*.{kind}"), key=lambda p: p.stat().st_mtime) if (ws_root / uid).exists() else []
            f = files[-1] if files else None
            q = check(kind, f, out, r["case"]) if f else {"file": None}
            if f:
                shutil.copy(f, out / f"{r['case']}.{kind}")
            r["notices"] += [json.loads(j).get("text") for (j,) in db.execute(
                "select json from entries where session_id=? and type='notice'", (r["sid"],))]
            r["ok"] = r["ok"] and not any("stopped" in (n or "") or "budget" in (n or "") for n in r["notices"])
            rows.append({**r, "kind": kind, "calls": u[0], "cost": u[1], "in": u[2], "outtok": u[3], **q})
        hdr = f"{'case':<16}{'kind':<6}{'ok':<4}{'secs':>6}{'turns':>6}{'calls':>6}{'cost$':>8}{'out tok':>8}  file/valid/issues/pages  notices"
        print("\n" + hdr + "\n" + "-" * len(hdr))
        for x in rows:
            print(f"{x['case']:<16}{x['kind']:<6}{'y' if x['ok'] else 'n':<4}{x['secs'] or 0:>6.0f}{x['turns']:>6}{x['calls']:>6}"
                  f"{x['cost']:>8.3f}{x['outtok']:>8}  {Path(x['file']).name if x.get('file') else '-'}"
                  f"/{x.get('valid')}/{x.get('issues')}/{x.get('pages')}  {'; '.join(n for n in x['notices'] if n)[:60]}")
            for ln in x.get("issue_lines") or []:
                print(f"{'':<22}{ln[:110]}")
        print()
        for kind in sorted({x["kind"] for x in rows}):
            ts = [x["secs"] for x in rows if x["kind"] == kind and x["secs"]]
            print(f"{kind}: n={len(ts)} p50={pct(ts, 0.5):.0f}s p95={pct(ts, 0.95):.0f}s "
                  f"mean turns={statistics.mean(x['turns'] for x in rows if x['kind'] == kind):.1f} "
                  f"made={sum(1 for x in rows if x['kind'] == kind and x.get('file'))}/{sum(1 for x in rows if x['kind'] == kind)}")
        (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
        print(f"\nresults: {out}/results.json; grids: {out}/*.png; server log: {home}/server.log")
    finally:
        if srv.poll() is None:
            os.killpg(srv.pid, signal.SIGTERM)
            try:
                srv.wait(15)
            except subprocess.TimeoutExpired:
                os.killpg(srv.pid, signal.SIGKILL)
        if not a.keep:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
