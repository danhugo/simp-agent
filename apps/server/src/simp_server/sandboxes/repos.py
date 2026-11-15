"""Repo backup (design 2026-11-16 "Home snapshot / Repo backup"): git repos live on the sandbox's local disk
(/home/user/repos/<name>); after each tool call every changed repo is pushed to a bare mirror on the workspace
(/work/.simp/repos/<name>.git) with its working tree as a WIP commit, and its gitignored files go to an archive.
Both functions run one Python script inside the env (python3 + git are in the sandbox image), so they work on any
ExecutionEnv. Failures are logged, never raised: backup must not fail the user's tool call."""

from __future__ import annotations

import asyncio
import logging
import shlex

log = logging.getLogger("simp_server")

_COMMON = r'''
import hashlib, io, json, os, shutil, subprocess, sys, tarfile, tempfile
SKIP = {"node_modules", ".venv", "__pycache__", "dist", "build", ".cache", "target"}
FILE_CAP, ARCHIVE_CAP = 10 * 2**20, 50 * 2**20
MANIFEST = ".simp-not-backed-up.txt"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "simp", "GIT_AUTHOR_EMAIL": "simp@localhost",
       "GIT_COMMITTER_NAME": "simp", "GIT_COMMITTER_EMAIL": "simp@localhost", "GIT_TERMINAL_PROMPT": "0"}

def git(repo, *a, env=None, check=True):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, env=env or ENV)
    if check and r.returncode:
        raise RuntimeError(f"git {a[0]} in {repo}: {r.stderr.strip()}")
    return r.stdout.strip()
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
                ignored.append((rel, st.st_size, st.st_mtime_ns))
        sig = hashlib.sha256(json.dumps([head, tree, refs, sid]).encode()).hexdigest()
        isig = hashlib.sha256(json.dumps(ignored).encode()).hexdigest()
        state_f = os.path.join(gitdir, "simp-mirror-state")
        last = json.load(open(state_f)) if os.path.exists(state_f) else {}
        mirror = os.path.join(mirrors, name + ".git")
        if last.get("sig") != sig or not os.path.isdir(mirror):
            if not os.path.isdir(mirror):
                os.makedirs(mirrors, exist_ok=True)
                subprocess.run(["git", "init", "-q", "--bare", mirror], check=True, capture_output=True)
                git(mirror, "config", "receive.unpackLimit", "1")
            branch = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
            msg = f"simp wip\n\nbranch: {branch}\n"
            wip = git(repo, "commit-tree", tree, *(["-p", head] if head else []), "-m", msg)
            git(repo, "push", "-q", "--force", mirror, "refs/heads/*:refs/heads/*", "refs/tags/*:refs/tags/*",
                f"{wip}:refs/simp/wip/{sid}")
            remotes = {r: git(repo, "remote", "get-url", r) for r in git(repo, "remote").split()}
            with open(os.path.join(mirrors, name + ".remotes.json"), "w") as f:
                json.dump(remotes, f)
            last["sig"] = sig
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
                for ext in (".zst", ".gz"):
                    if os.path.exists(base + ext):
                        os.remove(base + ext)
                if shutil.which("zstd"):
                    subprocess.run(["zstd", "-q", "-f", tar_path, "-o", base + ".zst"], check=True)
                else:
                    subprocess.run(f"gzip -c {tar_path!r} > {base + '.gz'!r}", shell=True, check=True)
            last["isig"] = isig
        with open(state_f, "w") as f:
            json.dump(last, f)
        print(f"ok {name}")
    except Exception as e:
        print(f"FAIL {name}: {e}")
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
    try:
        os.makedirs(repos_dir, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--no-checkout", mirror, repo], check=True, capture_output=True, env=ENV)
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
            git(repo, "checkout", "-q", wip, "--", ".")  # WIP tree into the working tree...
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
        base = os.path.join(mirrors, name + ".ignored.tar")
        tar_path = None
        if os.path.exists(base + ".zst"):
            tar_path = os.path.join(repo, ".git", "simp-ignored.tar")
            subprocess.run(["zstd", "-q", "-d", "-f", base + ".zst", "-o", tar_path], check=True)
        elif os.path.exists(base + ".gz"):
            tar_path = base + ".gz"
        if tar_path:
            with tarfile.open(tar_path) as tar:
                members = [x for x in tar.getmembers() if x.name != MANIFEST]
                tar.extractall(repo, members=members, filter="data")
            if tar_path.endswith("simp-ignored.tar"):
                os.remove(tar_path)
        print(f"restored {name}")
    except Exception as e:
        shutil.rmtree(repo, ignore_errors=True)  # half a restore would block the next try
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


__all__ = ["mirror_repos", "restore_repos"]
