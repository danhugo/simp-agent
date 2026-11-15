"""Git on the FUSE mount vs local disk (design 2026-11-16, step 2: decides whether repos can live on /work).

    uv run python apps/server/scripts/bench_git_mount.py --docker   # dev MinIO + a fuse-mode DockerSandbox, then cleans up

Inside a sandbox it takes dirs: `python3 - /work/bench /home/user/bench < this`. For each dir: a repo of N small files in nested dirs, then times init+add+commit, status (clean), edit 5 files,
status (dirty), commit."""

import os
import shutil
import subprocess
import sys
import time

N = int(os.environ.get("BENCH_FILES", "300"))
ENV = {**os.environ, "GIT_AUTHOR_NAME": "b", "GIT_AUTHOR_EMAIL": "b@b", "GIT_COMMITTER_NAME": "b", "GIT_COMMITTER_EMAIL": "b@b"}


def timed(repo, *cmds):
    t = time.monotonic()
    for c in cmds:
        subprocess.run(c, cwd=repo, shell=True, check=True, capture_output=True, env=ENV)
    return time.monotonic() - t


def docker_main():
    import asyncio
    import pathlib
    import tempfile

    from simp_server import devminio
    from simp_server.sandboxes.docker import DockerSandbox
    from simp_server.workspace import S3Store

    async def run():
        was_running, w = devminio._port() is not None, devminio.start()
        with tempfile.TemporaryDirectory() as tmp:
            settings = {"data_dir": tmp, "sandbox": {"mount": "fuse"}, "workspace": {
                "store": "s3", "endpoint": w["endpoint"], "bucket": w["bucket"], "prefix": "bench/{user_id}/"}}
            sb = DockerSandbox(settings)
            sb.store = S3Store(settings, {"S3_ACCESS_KEY_ID": w["access_key"], "S3_SECRET_ACCESS_KEY": w["secret_key"]})
            env = await sb.open("s-bench", "bench")
            try:
                await env.write_bytes("/tmp/bench.py", pathlib.Path(__file__).read_bytes())
                code, out = await env.exec(f"BENCH_FILES={N} python3 /tmp/bench.py /work/bench /home/user/bench /tmp/bench",
                                           "/work", 1800, asyncio.Event())
                print(out)
            finally:
                await sb.close_all()
                subprocess.run(["docker", "volume", "rm", "-f", "simp-home-bench"], capture_output=True)
                if not was_running:
                    devminio.stop()

    asyncio.run(run())


if sys.argv[1:] == ["--docker"]:
    docker_main()
    sys.exit()
for root in sys.argv[1:]:
    shutil.rmtree(root, ignore_errors=True)
    t = time.monotonic()
    for i in range(N):
        d = os.path.join(root, f"pkg{i % 10}", f"mod{i % 7}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"f{i}.py"), "w") as f:
            f.write(f"x = {i}\n" * 20)
    write = time.monotonic() - t
    r = {"write files": write,
         "init+add+commit": timed(root, "git init -q", "git add -A", "git commit -qm init"),
         "status clean": timed(root, "git status --porcelain"),
         "status dirty": timed(root, *(f"echo y >> pkg{i}/mod{i}/f{i}.py" for i in range(5)), "git status --porcelain"),
         "commit 5 files": timed(root, "git commit -qam edit")}
    print(root, N, "files:", ", ".join(f"{k} {v:.2f}s" for k, v in r.items()))
    shutil.rmtree(root, ignore_errors=True)
