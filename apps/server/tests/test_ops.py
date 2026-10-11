import json
import logging
import sqlite3
import tarfile

from simp_server import ops


def test_json_log_line(capsys):
    ops.setup_logging()
    logging.getLogger("simp_server").info("run start", extra={"run_id": "r1", "session": "s1"})
    line = capsys.readouterr().err.strip().splitlines()[-1]
    d = json.loads(line)
    assert d["msg"] == "run start" and d["run_id"] == "r1" and d["session"] == "s1" and d["level"] == "INFO"


def test_backup_and_restore(tmp_path):
    home, out = tmp_path / "home", tmp_path / "out"
    home.mkdir()
    db = sqlite3.connect(home / "simp.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE t(x)")
    db.execute("INSERT INTO t VALUES(42)")
    db.commit()  # left open on purpose: backup must work while the server holds the db
    (home / ".env").write_text("OPENAI_API_KEY=secret")
    (home / "settings.toml").write_text("x = 1")
    (home / "workspaces" / "s1").mkdir(parents=True)
    (home / "workspaces" / "s1" / "a.txt").write_text("hi")

    f = ops.backup(home, out)
    names = tarfile.open(f).getnames()
    assert ".env" not in names and "settings.toml" in names and "workspaces/s1/a.txt" in names

    restored = tmp_path / "restored"
    tarfile.open(f).extractall(restored, filter="data")
    assert sqlite3.connect(restored / "simp.db").execute("SELECT x FROM t").fetchone() == (42,)
    db.close()


def test_backup_keeps_newest(tmp_path):
    home, out = tmp_path / "home", tmp_path / "out"
    (home).mkdir()
    out.mkdir()
    for i in range(5):
        (out / f"simp-2026010{i}-000000.tar.gz").write_bytes(b"x")
    (out / "other.txt").write_text("keep me")
    f = ops.backup(home, out, keep=3)
    left = sorted(p.name for p in out.iterdir())
    assert left == ["other.txt", "simp-20260103-000000.tar.gz", "simp-20260104-000000.tar.gz", f.name]
