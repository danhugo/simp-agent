"""Build the E2B template for `[sandbox] kind = "e2b"` (design 2026-11-16 step 3).

    E2B_API_KEY=... uv run python apps/server/sandboxes/e2b_template.py [--alias simp-sandbox] [--office]

Toolset: simp_server.sandboxes.toolset, installed read-only in /opt/simp. LibreOffice (headless) is optional
(--office): it adds about 500 MB to the template. User `user` (E2B's default, uid 1000), /work is the mount point of
the user's bucket prefix, /home/user/repos holds git repos."""

import argparse

from e2b import Template, default_build_logger

from simp_server.sandboxes.toolset import APT, OFFICE_APT, PIP

VENV = "/opt/simp/venv"


def template(office: bool = False):
    t = (Template().from_python_image("3.13")
         .set_user("root")
         .apt_install(APT + (OFFICE_APT if office else []), no_install_recommends=True)
         .run_cmd(["ln -sf /usr/bin/fdfind /usr/local/bin/fd",
                   "id -u user >/dev/null 2>&1 || useradd -u 1000 -m -d /home/user -s /bin/bash user",
                   "mkdir -p /work /home/user/repos && chown user:user /work /home/user/repos",
                   "echo user_allow_other >> /etc/fuse.conf"])
         # the fixed toolset: root-owned and read-only for `user` (see simp_server.sandboxes.toolset)
         .run_cmd([f"python -m venv {VENV}", f"{VENV}/bin/pip install --no-cache-dir " + " ".join(PIP),
                   "chown -R root:root /opt/simp", "chmod -R go-w /opt/simp"])
         # `user` must not get root: commands run as user, only the mount runs as root (via envd, not sudo).
         # The python base image has no sudo; E2B's own provisioning may add a sudoers entry, so remove sudo and
         # any rule naming user, then assert. E2BSandbox also checks `sudo -n true` fails at every create.
         .run_cmd(["apt-get purge -y sudo >/dev/null 2>&1 || true",
                   "rm -f /usr/bin/sudo /etc/sudoers.d/* && (sed -i '/^user[[:space:]]/d' /etc/sudoers 2>/dev/null || true)",
                   "! su -s /bin/sh user -c 'sudo -n true' >/dev/null 2>&1"])
         .set_envs({"PYTHONNOUSERSITE": "1",
                    "PATH": f"{VENV}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"})
         .set_user("user")
         .set_workdir("/work"))
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alias", default="simp-sandbox")
    ap.add_argument("--office", action="store_true", help="add LibreOffice headless (large)")
    ap.add_argument("--cpus", type=int, default=2)
    ap.add_argument("--memory-mb", type=int, default=2048)
    a = ap.parse_args()
    info = Template.build(template(a.office), alias=a.alias, cpu_count=a.cpus, memory_mb=a.memory_mb,
                          on_build_logs=default_build_logger())
    print(info)


if __name__ == "__main__":
    main()
