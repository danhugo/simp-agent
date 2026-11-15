"""Dev MinIO (design 2026-11-16, step 2: "dev with prod semantics"): MinIO in Docker on a free port, one bucket with
versioning ON, and a non-root user (`simp-dev`) for the server, because MinIO refuses STS AssumeRole for the root
user and the server hands each sandbox a credential scoped to users/<user_id>/ via AssumeRole.

    uv run python -m simp_server.devminio start   # prints the settings.toml [workspace] table and .env lines
    uv run python -m simp_server.devminio stop    # removes the container and its data
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time

NAME, IMAGE, MC = "simp-minio", "cgr.dev/chainguard/minio:latest", "cgr.dev/chainguard/minio-client:latest"  # Docker Hub minio is gone
ROOT_USER, ROOT_PASS = "simp-root", "simp-root-secret"
DEV_KEY, DEV_SECRET = "simp-dev", "simp-dev-secret"
BUCKET = "simp-dev"
POLICY = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:*"], "Resource": ["arn:aws:s3:::*"]}]}


def _free_port(start: int = 9100) -> int:
    for port in range(start, start + 100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)):
                return port
    raise SystemExit("no free port for MinIO")


def _port() -> int | None:
    r = subprocess.run(["docker", "port", NAME, "9000/tcp"], capture_output=True, text=True)
    return int(r.stdout.split(":")[-1]) if r.returncode == 0 and r.stdout.strip() else None


def _mc(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    # mc in its own container on MinIO's network namespace
    return subprocess.run(["docker", "run", "--rm", "-i", "--network", f"container:{NAME}",
                           "-e", f"MC_HOST_local=http://{ROOT_USER}:{ROOT_PASS}@127.0.0.1:9000", MC, *args],
                          input=stdin, capture_output=True)


def start() -> dict:
    """Start (or reuse) the dev MinIO; returns the [workspace] settings and credentials for it."""
    port = _port()
    if port is None:
        stop()
        port = _free_port()
        subprocess.run(["docker", "run", "-d", "--name", NAME, "-p", f"127.0.0.1:{port}:9000",
                        "-e", f"MINIO_ROOT_USER={ROOT_USER}", "-e", f"MINIO_ROOT_PASSWORD={ROOT_PASS}",
                        IMAGE, "server", "/data"], check=True)
        for _ in range(100):
            if _mc("ready", "local").returncode == 0:
                break
            time.sleep(0.2)
        for args, stdin in ((("mb", "--ignore-existing", f"local/{BUCKET}"), None),
                            (("version", "enable", f"local/{BUCKET}"), None),
                            (("admin", "policy", "create", "local", "simp-dev", "/dev/stdin"), json.dumps(POLICY).encode()),
                            (("admin", "user", "add", "local", DEV_KEY, DEV_SECRET), None),
                            (("admin", "policy", "attach", "local", "simp-dev", "--user", DEV_KEY), None)):
            if (r := _mc(*args, stdin=stdin)).returncode:
                raise SystemExit(f"mc {args[0]} failed: {(r.stdout + r.stderr).decode().strip()}")
    return {"store": "s3", "endpoint": f"http://127.0.0.1:{port}", "bucket": BUCKET, "region": "us-east-1",
            "access_key": DEV_KEY, "secret_key": DEV_SECRET}


def stop() -> None:
    subprocess.run(["docker", "rm", "-f", "-v", NAME], capture_output=True)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "stop":
        stop()
        return print("stopped")
    w = start()
    print(f'# settings.toml\n[workspace]\nstore = "s3"\nendpoint = "{w["endpoint"]}"\nbucket = "{w["bucket"]}"\n'
          f'access_key_env = "S3_ACCESS_KEY_ID"\nsecret_key_env = "S3_SECRET_ACCESS_KEY"\n\n'
          f'# .env\nS3_ACCESS_KEY_ID={w["access_key"]}\nS3_SECRET_ACCESS_KEY={w["secret_key"]}')


if __name__ == "__main__":
    main()
