"""Repo backup (design 2026-11-16 "Home snapshot / Repo backup"): git repos live on the sandbox's local disk
(/home/user/repos/<name>); after each tool call every changed repo is pushed to a bare mirror on the workspace
(/work/.simp/repos/<name>.git) with its working tree as a WIP commit, and its gitignored files go to an archive.
Both functions run one Python script inside the env (python3 + git are in the sandbox image), so they work on any
ExecutionEnv. Failures are logged, never raised: backup must not fail the user's tool call."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shlex

log = logging.getLogger("simp_server")

_COMMON = r'''
import hashlib, io, json, os, shutil, stat, subprocess, sys, tarfile, tempfile, time
SKIP = {"node_modules", ".venv", "__pycache__", "dist", "build", ".cache", "target"}
FILE_CAP, ARCHIVE_CAP = 10 * 2**20, 50 * 2**20
MANIFEST = ".simp-not-backed-up.txt"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "simp", "GIT_AUTHOR_EMAIL": "simp@localhost",
       "GIT_COMMITTER_NAME": "simp", "GIT_COMMITTER_EMAIL": "simp@localhost", "GIT_TERMINAL_PROMPT": "0"}

# repo config is the user's (and the agent's): never run its hooks or fsmonitor command from our backup
SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]

def git(repo, *a, env=None, check=True):
    r = subprocess.run(["git", *SAFE, "-C", repo, *a], capture_output=True, text=True, env=env or ENV)
    if check and r.returncode:
        raise RuntimeError(f"git {a[0]} in {repo}: {r.stderr.strip()}")
    return r.stdout.strip()

def put(path, write):
    """write(tmp_path) then rename over path: a reader (or a concurrent mirror) never sees half a file."""
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

def put_json(path, obj):
    def w(tmp):
        with open(tmp, "w") as f:
            json.dump(obj, f)
    put(path, w)
'''

_MIRROR = _COMMON + r'''
repos_dir, mirrors, sid = sys.argv[1:4]
for name in sorted(os.listdir(repos_dir)) if os.path.isdir(repos_dir) else []:
    repo = os.path.join(repos_dir, name)
    gitdir = os.path.join(repo, ".git")
    if not os.path.isdir(gitdir):
        continue
    try:
        # WIP tree from a temp index seeded with the real one (add -A only rehashes changed files); the user's
        # index and branches are untouched
        head = git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False)
        with tempfile.TemporaryDirectory() as tmp:
            idx = os.path.join(tmp, "index")
            if os.path.exists(os.path.join(gitdir, "index")):
                shutil.copy(os.path.join(gitdir, "index"), idx)
            env = {**ENV, "GIT_INDEX_FILE": idx}
            git(repo, "add", "-A", env=env)
            tree = git(repo, "write-tree", env=env)
        refs = git(repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads", "refs/tags")
        ignored = []
        for rel in git(repo, "ls-files", "-z", "--others", "--ignored", "--exclude-standard").split("\0"):
            if rel and not SKIP & set(rel.split("/")[:-1]):
                st = os.lstat(os.path.join(repo, rel))
                if not stat.S_ISREG(st.st_mode):
                    continue  # symlinks (maybe absolute, pointing anywhere) and specials are not backed up
                ignored.append((rel, st.st_size, st.st_mtime_ns))
        sig = hashlib.sha256(json.dumps([head, tree, refs, sid]).encode()).hexdigest()
        isig = hashlib.sha256(json.dumps(ignored).encode()).hexdigest()
        state_f = os.path.join(gitdir, "simp-mirror-state")
        last = json.load(open(state_f)) if os.path.exists(state_f) else {}
        mirror = os.path.join(mirrors, name + ".git")
        if last.get("sig") != sig or not os.path.isdir(mirror):
            if not os.path.isdir(mirror):
                os.makedirs(mirrors, exist_ok=True)
                subprocess.run(["git", *SAFE, "init", "-q", "--bare", mirror], check=True, capture_output=True)
                git(mirror, "config", "receive.unpackLimit", "1")
            branch = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
            msg = f"simp wip\n\nbranch: {branch}\n"
            wip = git(repo, "commit-tree", tree, *(["-p", head] if head else []), "-m", msg)
            git(repo, "push", "-q", "--no-verify", "--force", mirror, "refs/heads/*:refs/heads/*", "refs/tags/*:refs/tags/*",
                f"{wip}:refs/simp/wip/{sid}")
            remotes = {r: git(repo, "remote", "get-url", r) for r in git(repo, "remote").split()}
            put_json(os.path.join(mirrors, name + ".remotes.json"), remotes)
            last["sig"] = sig
            put_json(os.path.join(mirrors, name + ".status"), {"ok_at": time.time(), "session": sid})
        if last.get("isig") != isig:
            skipped, total = [], 0
            with tempfile.TemporaryDirectory() as tmp:
                tar_path = os.path.join(tmp, "ignored.tar")
                with tarfile.open(tar_path, "w") as tar:
                    for rel, size, _ in ignored:
                        if size > FILE_CAP or total + size > ARCHIVE_CAP:
                            skipped.append(f"{rel}\t{size} bytes")
                            continue
                        total += size
                        tar.add(os.path.join(repo, rel), rel, recursive=False)
                    data = ("\n".join(skipped) + "\n").encode() if skipped else b""
                    info = tarfile.TarInfo(MANIFEST)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
                base = os.path.join(mirrors, name + ".ignored.tar")
                ext = ".zst" if shutil.which("zstd") else ".gz"
                if ext == ".zst":
                    put(base + ext, lambda t: subprocess.run(["zstd", "-q", "-f", tar_path, "-o", t], check=True))
                else:
                    put(base + ext, lambda t: subprocess.run(f"gzip -c {tar_path!r} > {t!r}", shell=True, check=True))
                other = base + (".gz" if ext == ".zst" else ".zst")
                if os.path.exists(other):
                    os.remove(other)
            last["isig"] = isig
        with open(state_f, "w") as f:
            json.dump(last, f)
        print(f"ok {name}")
    except Exception as e:
        print(f"FAIL {name}: {e}")
        try:
            sf = os.path.join(mirrors, name + ".status")
            old = json.load(open(sf)) if os.path.exists(sf) else {}
            put_json(sf, {**old, "failed_at": time.time(), "error": str(e)[:500]})
        except Exception:
            pass
print("SIMP_DONE")
'''

_RESTORE = _COMMON + r'''
repos_dir, mirrors = sys.argv[1:3]
for m in sorted(os.listdir(mirrors)) if os.path.isdir(mirrors) else []:
    if not m.endswith(".git"):
        continue
    name, mirror = m[:-4], os.path.join(mirrors, m)
    repo = os.path.join(repos_dir, name)
    if os.path.exists(repo):
        continue
    git_done = False
    try:
        os.makedirs(repos_dir, exist_ok=True)
        subprocess.run(["git", *SAFE, "clone", "-q", "--no-checkout", mirror, repo], check=True, capture_output=True, env=ENV)
        git(repo, "fetch", "-q", "origin", "+refs/simp/*:refs/simp/*")
        wip = git(repo, "for-each-ref", "--sort=-committerdate", "--count=1", "--format=%(objectname)", "refs/simp/wip")
        if wip:
            body = git(repo, "log", "-1", "--format=%B", wip)
            branch = next((l[8:].strip() for l in body.splitlines() if l.startswith("branch: ")), "")
            parent = git(repo, "rev-parse", "-q", "--verify", wip + "^", check=False)
            if branch and parent and git(repo, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}", check=False):
                git(repo, "checkout", "-q", "-B", branch, f"refs/remotes/origin/{branch}")
            elif parent:
                git(repo, "checkout", "-q", "--detach", parent)
            elif branch:
                git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
            git(repo, "read-tree", "-u", "--reset", wip)  # WIP tree into index + working tree (deletions too)...
            if parent:
                git(repo, "reset", "-q")  # ...and the index back to HEAD: changes show as uncommitted again
            else:
                git(repo, "rm", "-q", "-r", "--cached", ".")
        else:
            git(repo, "checkout", "-q", check=False)
        # local branches for every mirrored branch, like the original repo
        for ref in git(repo, "for-each-ref", "--format=%(refname:strip=3)", "refs/remotes/origin").split():
            if ref != "HEAD" and not git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{ref}", check=False):
                git(repo, "branch", "-q", ref, f"refs/remotes/origin/{ref}")
        git(repo, "remote", "remove", "origin")
        rf = os.path.join(mirrors, name + ".remotes.json")
        for r, url in (json.load(open(rf)) if os.path.exists(rf) else {}).items():
            git(repo, "remote", "add", r, url, check=False)
        git_done = True  # from here on a failure only loses ignored files: never remove the repo
        base = os.path.join(mirrors, name + ".ignored.tar")
        tar_path = None
        if os.path.exists(base + ".zst"):
            tar_path = os.path.join(repo, ".git", "simp-ignored.tar")
            subprocess.run(["zstd", "-q", "-d", "-f", base + ".zst", "-o", tar_path], check=True)
        elif os.path.exists(base + ".gz"):
            tar_path = base + ".gz"
        if tar_path:
            with tarfile.open(tar_path) as tar:
                for x in tar.getmembers():
                    if x.name == MANIFEST or not x.isfile():
                        continue
                    try:
                        tar.extract(x, repo, filter="data")
                    except Exception as e:
                        print(f"skip {name}/{x.name}: {e}")
            if tar_path.endswith("simp-ignored.tar"):
                os.remove(tar_path)
        print(f"restored {name}")
    except Exception as e:
        if not git_done:
            shutil.rmtree(repo, ignore_errors=True)  # half a git restore would block the next try
        print(f"FAIL {name}: {e}")
'''


async def _run_script(env, script: str, args: list[str], what: str, timeout: float, cwd: str) -> str:
    cmd = "python3 - " + shlex.join(args) + " <<'SIMP_PY'\n" + script + "\nSIMP_PY"
    try:
        code, out = await env.exec(cmd, cwd, timeout, asyncio.Event())
    except Exception as e:
        log.warning("repo %s failed: %s", what, e)
        return ""
    if code != 0 or "FAIL " in out:
        log.warning("repo %s: exit %s: %s", what, code, out.strip()[-2000:])
    return out


async def mirror_repos(env, repos_dir: str, mirrors_dir: str, session_id: str, cwd: str = "/", timeout: float = 120) -> str:
    """Push every changed repo under repos_dir to mirrors_dir/<name>.git (+ ignored-files archive)."""
    return await _run_script(env, _MIRROR, [repos_dir, mirrors_dir, session_id], "mirror", timeout, cwd)


async def restore_repos(env, repos_dir: str, mirrors_dir: str, cwd: str = "/", timeout: float = 300) -> str:
    """Clone each mirror whose repo is missing from repos_dir, check out its latest WIP, unpack ignored files."""
    return await _run_script(env, _RESTORE, [repos_dir, mirrors_dir], "restore", timeout, cwd)


MIRROR_FG_S = 30  # the after-tool mirror holds up the tool call at most this long


async def mirror_locked(env, box, repos_dir: str, mirrors_dir: str, session_id: str, cwd: str = "/",
                        fg_timeout: float | None = None, timeout: float = 120) -> None:
    """The after-tool mirror (review M6/M7): one at a time per user (box.mirror_lock), at most `fg_timeout` in the
    foreground; a longer one goes on in the background still holding the lock, so pause/kill (which take the lock)
    wait for it. Sets box.mirror_failed (checked before a kill or a recreate). Never raises."""
    async def job():
        async with box.mirror_lock:
            out = await mirror_repos(env, repos_dir, mirrors_dir, session_id, cwd=cwd, timeout=timeout)
            box.mirror_failed = "SIMP_DONE" not in out or "FAIL " in out
            box.mirror_sid = session_id
            if box.mirror_failed:
                log.error("REPO MIRROR FAILED for user %s: repos on the sandbox disk are not backed up; see "
                          "%s/<name>.status", box.user_id, mirrors_dir, extra={"user": box.user_id})

    task = asyncio.ensure_future(job())
    done, _ = await asyncio.wait({task}, timeout=MIRROR_FG_S if fg_timeout is None else fg_timeout)
    if not done:
        log.warning("repo mirror is slow: continuing in the background", extra={"user": box.user_id})
        box.mirror_bg = task  # keep a reference; pause/kill wait on box.mirror_lock
        return
    with contextlib.suppress(Exception):
        task.result()


async def remirror_if_failed(box, repos_dir: str, mirrors_dir: str, cwd: str = "/work") -> None:
    """Before a kill (the disk is gone after it): if the last mirror failed, try once more on the raw box and say so
    loudly either way. Caller holds box.mirror_lock."""
    if not getattr(box, "mirror_failed", False):
        return
    log.error("last repo mirror failed: retrying before the sandbox is removed", extra={"user": box.user_id})
    out = await mirror_repos(box, repos_dir, mirrors_dir, box.mirror_sid or "kill", cwd=cwd)
    box.mirror_failed = "SIMP_DONE" not in out or "FAIL " in out
    if box.mirror_failed:
        log.error("REPO MIRROR STILL FAILING: removing the sandbox anyway; repo changes since the last good mirror "
                  "are lost (home volume/snapshot may still have them)", extra={"user": box.user_id})


__all__ = ["mirror_repos", "restore_repos", "mirror_locked", "remirror_if_failed"]
