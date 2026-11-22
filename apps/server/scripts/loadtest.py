"""Load test: how many concurrent agent runs can one server process handle (tools off, fake model at realistic speed).

    uv run python apps/server/scripts/loadtest.py                      # levels 10,25,50,100,200,400
    uv run python apps/server/scripts/loadtest.py --levels 50,100 --tokens 400 --tps 50 --ttft 0.8 --workers 4

Starts `simp-server run --fake-llm` on a free port with a throwaway SIMP_SERVER_HOME (fake profile with `tools = []`,
max_open_sessions 5000, huge budgets), signs up one user per concurrent run, then per level: each run opens a fresh
session + SSE stream, all prompts fire at the same instant, and we time first text_delta (TTFT) and run_state idle.
The client is split over --workers processes so it is not the bottleneck. Server CPU% / RSS come from `ps` every 0.5s
(CPU% > 100 is impossible for one uvicorn process doing real work: a single asyncio loop saturates at ~100%).

Reading the table: ideal = ttft + tokens/tps. A healthy level has run p95 close to ideal and TTFT p95 close to --ttft.
The knee is the first level where failures > 5% or run p95 > 2x ideal; the run stops there.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[3]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pct(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


# ---- one run (in a worker process) ----------------------------------------------------------------------------------

async def one_run(c: httpx.AsyncClient, token: str, start_at: float, timeout: float) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    r = {"ok": False, "ttft": None, "run": None, "deltas": 0, "err": None}
    try:
        s = await c.post("/api/sessions", json={}, headers=h)
        s.raise_for_status()
        sid = s.json()["id"]
        async with c.stream("GET", f"/api/sessions/{sid}/events", headers=h, timeout=None) as ev:
            ev.raise_for_status()
            lines = ev.aiter_lines()
            async for line in lines:  # wait for the snapshot: we are subscribed
                if line.startswith("data:") and json.loads(line[5:])["type"] == "snapshot":
                    break
            await asyncio.sleep(max(0.0, start_at - time.time()))
            t0 = time.perf_counter()
            pr = await c.post(f"/api/sessions/{sid}/commands", json={"type": "prompt", "text": "hello"}, headers=h)
            if pr.status_code != 200:
                r["err"] = f"HTTP {pr.status_code}"
                return r
            running = False

            async def read():
                nonlocal running
                async for line in lines:
                    if not line.startswith("data:"):
                        continue
                    e = json.loads(line[5:])
                    if e["type"] == "text_delta":
                        r["deltas"] += 1
                        if r["ttft"] is None:
                            r["ttft"] = time.perf_counter() - t0
                    elif e["type"] == "run_state":
                        running = running or e["state"] == "running"
                        if e["state"] == "idle" and running:
                            r["run"], r["ok"] = time.perf_counter() - t0, True
                            return
                r["err"] = "stream dropped"
            await asyncio.wait_for(read(), timeout)
    except TimeoutError:
        r["err"] = "timeout"
    except httpx.HTTPStatusError as e:
        r["err"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        r["err"] = type(e).__name__
    return r


def worker(base: str, tokens: list[str], start_at: float, timeout: float) -> list[dict]:
    async def go():
        lim = httpx.Limits(max_connections=None, max_keepalive_connections=None)
        async with httpx.AsyncClient(base_url=base, limits=lim, timeout=30) as c:
            return await asyncio.gather(*(one_run(c, t, start_at, timeout) for t in tokens))
    return asyncio.run(go())


# ---- server process + sampling --------------------------------------------------------------------------------------

class Sampler(threading.Thread):
    def __init__(self, pid: int):
        super().__init__(daemon=True)
        self.pid, self.on, self.samples, self.stop_ev = pid, False, [], threading.Event()

    def run(self):
        while not self.stop_ev.wait(0.5):
            if self.on:
                out = subprocess.run(["ps", "-o", "%cpu=,rss=", "-p", str(self.pid)], capture_output=True, text=True)
                if out.stdout.split():
                    cpu, rss = out.stdout.split()
                    self.samples.append((float(cpu), int(rss) / 1024))


async def seed_users(home: Path, n: int) -> list[str]:
    from simp_server.store import SqliteStore
    s = SqliteStore({"data_dir": str(home)})
    await s.open()
    try:
        return [await s.add_user(f"u{i}") for i in range(n)]
    finally:
        await s.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", default="10,25,50,100,200,400")
    ap.add_argument("--tokens", type=int, default=400)
    ap.add_argument("--tps", type=float, default=50)
    ap.add_argument("--ttft", type=float, default=0.8)
    ap.add_argument("--workers", type=int, default=4, help="client processes")
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free one")
    a = ap.parse_args()
    levels = [int(x) for x in a.levels.split(",")]
    ideal = a.ttft + a.tokens / a.tps

    home = Path(tempfile.mkdtemp(prefix="simp-load-"))
    (home / "settings.toml").write_text(
        'allow_local_sandbox = true\nmax_open_sessions = 5000\n'
        '[profiles.fake]\napi = "fake"\nmodel = "fake"\nprice_in = 0\nprice_out = 0\ntools = []\n'
        '[budget]\nrun_usd = 1000000\n')
    port = a.port or free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "SIMP_SERVER_HOME": str(home), "SIMP_FAKE_TOKENS": str(a.tokens),
           "SIMP_FAKE_TPS": str(a.tps), "SIMP_FAKE_TTFT": str(a.ttft)}
    log = open(home / "server.log", "w")
    # exec the venv's entry point directly so the pid we sample is the server itself, not a `uv` wrapper
    exe = shutil.which("simp-server", path=str(REPO / ".venv" / "bin")) or "simp-server"
    srv = subprocess.Popen([exe, "run", "--port", str(port), "--fake-llm"], env=env, cwd=REPO, stdout=log,
                           stderr=subprocess.STDOUT, start_new_session=True)
    sampler = Sampler(srv.pid)
    sampler.start()

    def cleanup(*_):
        sampler.stop_ev.set()
        if srv.poll() is None:
            os.killpg(srv.pid, signal.SIGTERM)
            try:
                srv.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(srv.pid, signal.SIGKILL)
        shutil.rmtree(home, ignore_errors=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    try:
        for _ in range(100):
            try:
                if httpx.get(base + "/api/me").status_code == 401:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            raise SystemExit(f"server did not start; log:\n{(home / 'server.log').read_text()}")
        print(f"server pid {srv.pid} on {base}; home {home}; ideal run {ideal:.1f}s "
              f"({a.ttft}s ttft + {a.tokens} tok @ {a.tps}/s); {a.workers} client processes", flush=True)
        n_users = max(levels)
        t = time.time()
        tokens = asyncio.run(seed_users(home, n_users))
        print(f"seeded {n_users} users in {time.time() - t:.0f}s\n", flush=True)
        hdr = (f"{'n':>5} {'ok':>5} {'fail':>5} {'ttft p50':>9} {'ttft p95':>9} {'run p50':>8} {'run p95':>8} "
               f"{'ideal':>6} {'deltas/s':>9} {'cpu avg':>8} {'cpu max':>8} {'rss max':>8}  errors")
        print(hdr + "\n" + "-" * len(hdr), flush=True)
        knee = None
        ctx = mp.get_context("spawn")
        with ctx.Pool(a.workers) as pool:
            for n in levels:
                start_at = time.time() + 2 + n / 100  # time to create sessions + subscribe before the gun
                chunks = [tokens[i:n:a.workers] for i in range(a.workers)]
                sampler.samples, sampler.on = [], True
                t0 = time.time()
                res = [r for part in pool.starmap(worker, [(base, ch, start_at, ideal * 4 + 30) for ch in chunks if ch])
                       for r in part]
                sampler.on = False
                wall = time.time() - max(t0, start_at)
                ok = [r for r in res if r["ok"]]
                errs = {}
                for r in res:
                    if r["err"]:
                        errs[r["err"]] = errs.get(r["err"], 0) + 1
                ttft = [r["ttft"] for r in ok if r["ttft"] is not None]
                run = [r["run"] for r in ok]
                cpu = [s[0] for s in sampler.samples] or [float("nan")]
                rss = [s[1] for s in sampler.samples] or [float("nan")]
                fail = n - len(ok)
                print(f"{n:>5} {len(ok):>5} {fail:>5} {pct(ttft, .5):>8.2f}s {pct(ttft, .95):>8.2f}s "
                      f"{pct(run, .5):>7.1f}s {pct(run, .95):>7.1f}s {ideal:>5.1f}s "
                      f"{sum(r['deltas'] for r in res) / wall:>9.0f} {statistics.mean(cpu):>7.0f}% {max(cpu):>7.0f}% "
                      f"{max(rss):>6.0f}MB  {errs or ''}", flush=True)
                if fail > 0.05 * n or (run and pct(run, .95) > 2 * ideal) or not run:
                    knee = n
                    break
                time.sleep(2)
        print(f"\nknee: {knee} concurrent runs" if knee else f"\nno knee up to {max(levels)} concurrent runs")
    except KeyboardInterrupt:
        print("interrupted")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
