# User sandbox design, v2: mounted workspace (plan b)

Date: 2026-11-16 · Status: steps 1–4 implemented (step 5 design only)
Replaces the sync-based design of 2026-11-15: instead of copying files in and out of the sandbox, the user's
workspace is **mounted** into it. One sandbox per user, short lifetime, secrets outside and a pluggable
backend carry over.

## Goal

Each user has a personal computer: their files and installed libraries persist across sessions and days, and
several chat sessions can work at once. We pay only for compute in use, user data survives the loss of a
sandbox (within the window stated below), and the system can scale to many sandboxes and servers without a
redesign.

## Core idea

**The workspace is the disk. The sandbox is CPU and RAM that mounts the disk.** No sync code for ordinary
files: the sandbox sees the workspace at `/work` through a mount, like a USB drive plugged into a fresh computer.

| Part | Dev (this machine) | Production / scale | Lifetime |
|---|---|---|---|
| Workspace (user files) | `~/.simp-server/workspaces/<user_id>/` | bucket prefix `users/<user_id>/` (R2 or S3), versioned | account life |
| How the sandbox sees it | Docker bind mount at `/work` | FUSE mount of our bucket at `/work` (`s3fs` / Mountpoint / Archil) | while the sandbox runs |
| Git repos and libraries | sandbox local disk (`/home/user`) | same | snapshot archive in the store |
| Sandbox (compute) | Docker container | E2B sandbox | pause when idle, kill at max life |
| Sessions, messages, usage | SQLite on the server | SQLite, later Postgres | permanent |

The workspace store is the source of truth for files. Its durability comes from bucket versioning, not from the
sandbox.

### How the mount works (no sync step)

There is no "copy our storage to the provider's storage" step. The sandbox mounts **our** bucket directly over
the network:

```
our bucket (R2/S3) <──── FUSE mount over the network ──── E2B sandbox (/work)
```

- A FUSE driver inside the sandbox turns file operations into object-store calls at the moment they happen:
  read → GET (ranged, cached), write → buffered locally, PUT on close, `ls` → LIST (cached a few seconds),
  `rm` → DELETE. Nothing is downloaded up front.
- The sandbox's own disk holds only the OS, libraries, repos and `/tmp`; user files are never stored there.
- **The local store only pairs with local Docker.** A cloud sandbox cannot mount a folder on our server, so
  `store = "local"` + `kind = "e2b"` is an invalid config (the server refuses to start). Moving to E2B means
  moving workspaces to a bucket first (one-time upload).
- **E2B Volumes is a different model:** files would live in E2B's storage, not ours. That conflicts with "our
  store is the source of truth" (provider lock-in, migration needed to leave). Use our bucket + s3fs/Mountpoint/
  Archil as the default; Volumes only as an experiment.

## Rules

1. **One writer.** Every change to user files, repos or libraries happens inside the sandbox. All agent tools that
   touch files run there: `bash`, `read`, `write`, `edit`, `ls`, `grep`, `find`.
2. **Files panel exception.** List, download and upload from the web UI go straight to the store (local dir or
   bucket API), so browsing never wakes a sandbox. Upload is a plain object write; last write wins in v1. The
   sandbox may see an upload a few seconds late (FUSE metadata cache, kept short).
3. **Agent loop and secrets stay outside.** LLM loop, model keys, OAuth tokens and chat history live on the
   server. The only credential that may enter a sandbox is a scoped mount credential (see Security).
4. **Lazy compute.** A sandbox is created on a user's first tool call, not when a session opens. Pure chat, web
   search and memory never start one.
5. **Durable after every tool call.** After each tool call the runtime pushes changed repos to their mirror (see
   below), runs `sync` and waits for the mount to upload closed files (s3fs and Mountpoint upload on close). A file still open in a running command is not
   durable yet. **Data-loss window: writes from a command that is running when the sandbox dies.**
6. **Edit check by content.** `edit` fails if the file's content hash changed since this session last read it
   (FUSE mtimes are not reliable), and the agent re-reads.

## Where things live inside the sandbox

| Path | Backed by | Use |
|---|---|---|
| `/work` | the mount | user documents, media, outputs: anything the user should see in the Files panel |
| `/home/user/repos/<name>` | local disk, mirrored to `/work/.simp/repos` after each change | git repositories (many small files, lock files and renames, which FUSE handles badly; Mountpoint has no rename) |
| `/home/user/.local`, `~/.npm-global`, `~/.venvs/<project>` | local disk, snapshot to the store | user-installed libraries |
| `/tmp` | local disk, not kept | intermediates (video frames, build outputs), databases |

Template env: `PIP_USER=1`, `NPM_CONFIG_PREFIX=~/.npm-global`, `PATH` with `~/.local/bin` and
`~/.npm-global/bin`, project virtualenvs under `~/.venvs/<project>` (e.g. `UV_PROJECT_ENVIRONMENT`). The agent's
prompt says where to put repos, databases and intermediates.

### Home snapshot (repos and libraries)

- `/home/user/repos` and the library dirs are packed into one archive, `users/<user_id>/.simp/home.tar.zst`, at
  **every pause**, **every 15 min while running**, and **before kill**. Restored at create (one download).
- If the archive is missing or stale: repos come back from the last snapshot, and the agent can reinstall libraries
  from manifests in the repo (`requirements.txt`, `package-lock.json`, `uv.lock`). Repos with a remote should be
  pushed; the prompt nudges the agent to commit and push.
- Size cap on the archive; over the cap, libraries are skipped and reinstalled from manifests.
- **Repo backup after every tool call that changed a repo** (code is the most valuable data, so a 15-min
  window is not acceptable). After the call, for each repo whose state changed (cheap check: `git status
  --porcelain` and `HEAD`), the runtime:
  1. captures the working tree, including uncommitted and untracked files, as a commit object without touching
     the user's index or branches: with a temporary index (`GIT_INDEX_FILE=<tmp>`), run `git add -A`, then
     `git write-tree` and `git commit-tree` with `HEAD` as parent (`git stash create` alone does not include
     untracked files);
  2. pushes branches, tags and that work-in-progress commit as `refs/simp/wip/<session>` to a **bare mirror on
     the mount**, `/work/.simp/repos/<name>.git`, configured to keep objects packed (`receive.unpackLimit=1`), so
     each push writes one small pack file rather than many loose files.
  3. **Ignored files** (matched by `.gitignore`: `.env`, local config, data files the user made) are not in any
     commit, so they are packed separately into `/work/.simp/repos/<name>.ignored.tar.zst` when they changed.
     Rebuildable dirs are skipped (`node_modules`, `.venv`, `__pycache__`, `dist`, `build`, `.cache`, `target`),
     each file is capped at 10 MB and the archive at 50 MB; anything over the caps is listed in the archive as
     "not backed up" and the agent tells the user.
  Restore: clone the mirror into `/home/user/repos/<name>`, check out the latest WIP commit, then unpack the
  ignored-files archive.
- **Data-loss window for repos: one command** (the one running when the sandbox dies), the same as `/work`. The
  15-min home snapshot then only matters for libraries, which can always be reinstalled.
- Measure git on the mount in step 2: if `git status` and `git commit` are fast enough directly on the chosen
  FUSE driver, repos can move to `/work` and the mirror is not needed.

## Lifecycle

```
none ──first tool call──> create (mount /work, restore home snapshot) ──> running
running ──idle──> snapshot home ──> pause ──next tool call──> resume ──> check mount, remount ──> running
running ──max life──> snapshot home, sync, unmount ──> kill ──next use──> create fresh
```

- **Idle** = no foreground tool call running, no session streaming a reply, and no preview HTTP traffic for
  10 min. A running background process alone (a dev server) does not keep the sandbox awake.
- **Kill at max life** waits for a running **foreground** tool call to finish. Background processes do not block
  it: they are stopped, and the user is told that dev servers will restart.
- **After resume:** check that the FUSE mount is alive and its credential is valid; refresh the credential and
  remount if not, before running the tool.
- If a resume fails, create a new sandbox: files are on the mount, home comes from the snapshot.
- **Max life:** 55 min on E2B Hobby (`max_life_s = 3300`, under the 1 h continuous-runtime cap) until we confirm
  that a pause resets that counter; then 1–2 h.
- **Safety net:** every E2B sandbox is created with a short provider-side timeout whose action is **pause**, so it
  stops billing even if our server dies.
- On server start: list sandboxes by metadata (`user_id`), reuse or kill orphans.

## Concurrent sessions

- All sessions of a user share one sandbox, one `/work` and one `/home/user`.
- Each session has its own cwd (or a git worktree under `/home/user/repos`), and its processes are tagged with the
  session id so they can be listed and killed per session.
- No file locks; the content-hash check on `edit` catches concurrent changes.

## Mount caveats (for users and the agent)

- No reliable file locks, weak rename/append semantics: no databases, no git repos on `/work` (until measured).
- Many small files are slow: dependencies and build outputs stay off `/work`.
- Big files stream over the mount: process in `/tmp`, write the final result to `/work`.

## Security

- One sandbox per user; it can mount only that user's prefix.
- Mount credential: scoped to `users/<user_id>/`, short-lived, refreshed on resume. (E2B Volumes would avoid a key
  in the sandbox, but put the data in E2B's storage; see "How the mount works".)
- A prompt-injected command could still delete or overwrite the user's prefix. Protection: **bucket versioning
  plus a lifecycle rule** that keeps deleted or overwritten versions for 30 days, and a "restore workspace to time
  T" admin command. This replaces the old "backed up with the DB".
- Agent-generated code is untrusted. Network egress is allowed (downloads are a core use) and logged; long term,
  an egress proxy injects real tokens so the sandbox only sees placeholders.
- CPU, RAM and disk quotas per sandbox; a compute-minutes budget per user per day.

## Pluggable backends

Two slots in `settings.toml`:

```toml
[workspace]
store = "local"     # "local" (dir on this server) or "s3" (bucket, R2/S3/MinIO)

[sandbox]
kind = "docker"     # "docker" or "e2b"
mount = "bind"      # "bind" (docker + local store only) or "fuse" (our bucket via s3fs / Mountpoint / Archil)
idle_pause_s = 600
max_life_s = 3300
snapshot_every_s = 900
```

- Daily dev: `local` + `docker` + `bind` (free, today's setup).
- **Dev with prod semantics:** `s3` (MinIO in Docker) + `docker` + `fuse` (s3fs in the container). The test suite
  runs in this mode too, so FUSE bugs (locks, rename, stale cache) show up before production.
- Scale: `s3` (R2/S3) + `e2b` + `fuse`.

Agent code and tools do not change: they always see `/work` and `/home/user`.

## Cost (2–3 users, E2B Hobby)

Compute only while a sandbox runs: about $0.07/h (1 vCPU, 1 GB) to $0.27/h (4 vCPU, 4 GB). With auto-pause, a
light-to-medium month is about 45–90 sandbox-hours, roughly $5–11, inside the $100 one-time credit. A few GB
in a versioned bucket costs cents (R2 has no egress fees). The main risk is a sandbox left running (about $85 a
month each), prevented by our idle pause, the provider-side pause timeout and the daily compute budget.

## Plan

1. **Tools in the sandbox, lazily.** Route all file tools through the sandbox; create it on the first tool call;
   `sync` and repo mirror push after each call; content-hash check in `edit`; Docker backend with bind mount. Done when chat-only
   sessions start no container and all tests pass.
2. **Workspace store slot + FUSE dev mode.** `local` and `s3` stores; MinIO + s3fs mode for Docker; Files panel
   and admin restore go through the store; bucket versioning on. Run the test suite in FUSE mode. Measure git
   on the mount here (decides where repos live).
3. **E2B backend.** Template build script; create, pause, resume (with mount check and remount), kill; mount the
   user's prefix of our bucket (s3fs/Mountpoint/Archil; Volumes only as an experiment); home snapshot at pause, every 15 min and
   before kill; orphan cleanup; provider-side pause timeout. Live test gated on `E2B_API_KEY`.
4. **Cost and ops.** Sandbox seconds as usage with cost; daily compute budget; concurrency limit with a clear UI
   message; `simp-server sandboxes` admin command; workspace restore command.
5. **Scale (design only now).** Several server processes need run state out of process memory and Postgres;
   per-user sandbox lookup moves to the DB. Steps 1–4 must not assume a single server.

## Implementation notes (deviations)

- **E2B SDK 2.64:** the provider-side pause is `lifecycle={"on_timeout": "pause", "auto_resume": False}` on create;
  resume is `AsyncSandbox.connect(id)`; list by metadata `{app, user_id}`. Not run live yet (no bucket).
- **MinIO:** the Docker Hub `minio/minio` image is gone; dev uses `cgr.dev/chainguard/minio` (+ `minio-client`).
- **Docker fuse mode** needs a network to reach the store (default `bridge`, not `none`), `/dev/fuse`,
  `CAP_SYS_ADMIN` (used only by one `docker exec -u 0` for the mount; commands run as 1000 with no caps) and
  AppArmor unconfined. The container restarts at `max_life_s` when idle so the 1 h mount credential never expires.
- **Usage rows:** sandbox time is a usage row with model `sandbox:<kind>`, seconds in `input`, cost from
  `price_vcpu_s`/`price_gib_s`; it counts toward the money budget too. `day_minutes` (e2b default 240, docker off)
  and `max_running` (default 10) raise a clear tool error.
- **Kill at max life** does not yet tell the user that background processes (dev servers) stopped.

### Review fixes (2026-11-16)

- **Home snapshot excludes `repos/`.** The mirror is the only source of truth for repos; restore unpacks old
  snapshots with `--exclude=repos`. Over `snapshot_max_mb` no new snapshot is written.
- **Pause/kill vs a new call.** Pause and kill take the box's mirror lock, then its lock, re-check `active == 0`
  and set state `stopping` before snapshotting; `ensure()` only fast-paths on `running`, so a new call waits and
  then resumes. Same rule for Docker's idle stop / max life.
- **Docker gone container.** `docker exec` errors ("No such container") are detected before the pid line; the box
  is marked stopped and the command (which never started) runs once on a new container.
- **No re-run of a command lost mid-run** (E2B `SandboxLost`); only calls that never started retry. The tick
  refreshes the provider timeout while a call runs.
- **Mount credential expiry** is tracked per box (`expires_in` from the store); refresh + remount at an idle point,
  and before any call whose timeout would outlive it (refused while another call uses the mount).
- **Mirror:** one per user at a time (lock), capped at 30 s in the foreground then continued in the background
  holding the lock (pause/kill wait for it); archives and json written to a temp file then renamed;
  `<name>.status` records the last good mirror (`ok_at`) or the failure. A failed mirror is retried before a kill
  and logged as an error; a recreate after a failed mirror is logged as an error.
- **Restore** uses `git read-tree -u --reset <wip>` (WIP deletions stay deleted), skips symlinks and bad members in
  the ignored-files archive, and never removes a repo whose git restore succeeded. git runs without hooks/fsmonitor.
- **Budget** enforced in the tick (pause/stop after the current call); `max_running` slots reserved under a global
  lock before create.
- **Docker fuse stop:** SIGTERM user processes, wait, `umount /work` as root, then `docker rm -f`.
- **Config:** Docker `mount = "fuse"` needs `dev_fuse = true` (test only: bridge network reaches the host);
  `mount_scope = "none"` needs `dev_unscoped_mount = true`.
- **Bind mode host file IO** (LocalEnv with a root, LocalStore / Files panel) walks with `O_NOFOLLOW` from the root
  dir fd: all symlinks are refused, so a container cannot race a symlink swap toward the server's files.
- Two simp instances must not share a Docker host's sandbox names or an E2B key (README).

## Open questions

- Compare `s3fs`, Mountpoint (no rename) and Archil on git and many
  small files.
  **Measured (step 2, s3fs 1.95 → MinIO on the same Mac, Docker Desktop; `apps/server/scripts/bench_git_mount.py --docker`):**

  | | write files | init+add+commit | status clean | status dirty | commit 5 files |
  |---|---|---|---|---|---|
  | 300 files, `/work` (s3fs) | 3.3 s | 15.0 s | 0.41 s | 0.31 s | 0.70 s |
  | 300 files, `/home/user` (volume) | 0.02 s | 0.05 s | <0.01 s | 0.01 s | 0.01 s |
  | 2000 files, `/work` (s3fs) | 16.4 s | 67.4 s | 2.3 s | 0.70 s | 1.2 s |
  | 2000 files, `/home/user` (volume) | 0.08 s | 0.25 s | 0.02 s | 0.03 s | 0.03 s |

  100–300x slower with the store on the same machine; over the internet (R2/S3) it can only be worse. **Decision:
  repos stay on local disk with the mirror.** Mountpoint/Archil not measured.
- Does paused time count toward the Hobby 1 h continuous-runtime limit, and is paused storage billed?
- R2 vs S3 for per-prefix, short-lived credentials usable by a FUSE mount.
  Implemented: `[workspace] mount_scope = "sts"` (default) = STS AssumeRole with a session policy limited to
  `users/<id>/` (AWS needs `role_arn`; MinIO accepts any ARN but refuses AssumeRole for its root user, so
  `make minio` creates a `simp-dev` user). R2 has no STS: use `mount_scope = "none"` (the store key goes into the
  sandbox) until R2 temporary credentials are wired in.
- Network policy for E2B sandboxes (what can be blocked).

## Status and remaining work (paused 2026-11-17)

Done and pushed (`79faa70` … `242a647`): steps 1–4, README + guidebook ch 29a, independent review with
critical/major fixes (`c4ae988`), live E2B lifecycle test against real E2B (`test_e2b_live.py`: template
`simp-sandbox`, exec, files, no sudo, pause/resume keeps /home/user, adoption, max-life kill; create ~3.4 s,
resume ~0.4 s).

Not verified yet: anything that needs a real bucket reachable from E2B.

1. **Create the bucket** (R2 or S3), versioning on, lifecycle rule keeping noncurrent versions 30 days; an
   API token limited to that bucket. Put `SIMP_TEST_S3_*` (see `tests/test_e2b_sandbox.py::test_live_e2b`)
   and the production `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` into `~/.simp-server/.env` yourself.
2. **Run `test_live_e2b`** (real s3fs mount in E2B): mount with scoped creds, `/work` writes reach the
   bucket after `after_tool`, resume remount, credential refresh before expiry, home archive restore on a
   fresh sandbox, repo mirror push/restore through the bucket. On R2 (no STS) this needs
   `mount_scope = "none"` + `dev_unscoped_mount = true`; decide whether that is acceptable or use S3 + STS.
3. **Provider-side pause firing** on timeout (create with a short timeout, wait, check `paused`).
4. **Switch the real server**: migrate `~/.simp-server/workspaces/<user_id>/` to `users/<user_id>/` in the
   bucket, set `[workspace] store = "s3"`, `[sandbox] kind = "e2b"`, restart, smoke-test from the web UI.

Deferred on purpose (reviewed as minor or documented): instance-scoped sandbox names/tags (M9: one simp
per Docker host / E2B key), container auto-restart for file ops on `/home/user` (C1 covers `exec` only),
Mountpoint/Archil benchmark, UI for mirror status and "dev servers were restarted" notices, the remaining
minor review items.
