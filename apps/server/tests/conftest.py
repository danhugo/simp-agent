import shutil
import subprocess

import pytest


@pytest.fixture(scope="session")
def minio():
    """Dev MinIO (simp_server.devminio) for tests that need an S3 store: [workspace] settings dict. Skips without
    docker; removed after the session unless it was already running."""
    from simp_server import devminio
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode:
        pytest.skip("docker not available")
    was_running = devminio._port() is not None
    try:
        w = devminio.start()
    except (SystemExit, subprocess.CalledProcessError) as e:
        pytest.skip(f"MinIO did not start: {e}")
    yield w
    if not was_running:
        devminio.stop()


@pytest.fixture
def s3_settings(minio):
    return lambda tmp_path, prefix="users/{user_id}/", **sandbox: _s3_settings(tmp_path, minio, prefix, **sandbox)


def _s3_settings(tmp_path, w, prefix, **sandbox):
    """Server settings for an S3Store on the dev MinIO (keys passed as the `keys` dict, like <data_dir>/.env)."""
    settings = {"data_dir": str(tmp_path), "workspace": {**{k: w[k] for k in ("store", "endpoint", "bucket", "region")},
                                                        "prefix": prefix}, "sandbox": sandbox}
    keys = {"S3_ACCESS_KEY_ID": w["access_key"], "S3_SECRET_ACCESS_KEY": w["secret_key"]}
    return settings, keys


@pytest.fixture
def ask_all(monkeypatch):
    """Every tool call goes to the approval prompt (tests of the approval flow itself, not of the policy)."""
    monkeypatch.setattr("simp_server.policy.classify", lambda call, mcp_write, available, net_blocked=True: ("ask", ""))
