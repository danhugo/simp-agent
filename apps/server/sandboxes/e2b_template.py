"""Build the E2B template for `[sandbox] kind = "e2b"` (design 2026-11-16 step 3).

    E2B_API_KEY=... uv run python apps/server/sandboxes/e2b_template.py [--alias NAME] [--no-office] [--if-missing]

Toolset: simp_server.sandboxes.toolset, installed read-only in /opt/simp. Chromium (headless, about 380 MB) is on by default:
officecli screenshots pages with it (office_run, the office skills); --no-office leaves it out. User `user` (E2B's default, uid 1000), /work is the mount point of
the user's bucket prefix, /home/user/repos holds git repos."""

import argparse

from e2b import Template, default_build_logger

from pathlib import Path

from simp_server.sandboxes.toolset import (template_alias, APT, NODE_DIR, NPM, OFFICE_APT, PIP, RUN_ENV, SKILLS_DIR, VENV, OFFICE_REFERENCE_DOCX,
                                           officecli_install)

APP = Path(__file__).parents[1]  # apps/server: the build context, so skills/ copies in


def template(office: bool = True):
    t = (Template(file_context_path=str(APP)).from_python_image("3.13")
         .set_user("root")
         .apt_install(APT + (OFFICE_APT if office else []), no_install_recommends=True)
         .run_cmd(["ln -sf /usr/bin/fdfind /usr/local/bin/fd",
                   "id -u user >/dev/null 2>&1 || useradd -u 1000 -m -d /home/user -s /bin/bash user",
                   "mkdir -p /work /home/user/repos && chown user:user /work /home/user/repos",
                   "echo user_allow_other >> /etc/fuse.conf"])
         # the fixed toolset: root-owned and read-only for `user` (see simp_server.sandboxes.toolset)
         .run_cmd([f"python -m venv {VENV}", f"{VENV}/bin/pip install --no-cache-dir " + " ".join(PIP),
                   f"mkdir -p {NODE_DIR} && npm install --prefix {NODE_DIR} --no-fund --no-audit " + " ".join(NPM)])
         .run_cmd([officecli_install()]))
    if office:  # how officecli starts chromium in the sandbox
        t = t.copy("sandboxes/chromium.sh", "/usr/local/bin/chromium").run_cmd(["chmod 755 /usr/local/bin/chromium"])
    t = (t
         .copy("sandboxes/reference.docx", OFFICE_REFERENCE_DOCX)
         .run_cmd([f"mkdir -p {SKILLS_DIR}"])  # filled per user at run time
         .run_cmd(["chown -R root:root /opt/simp", "chmod -R go-w /opt/simp"])
         # `user` must not get root: commands run as user, only the mount runs as root (via envd, not sudo).
         # The python base image has no sudo; E2B's own provisioning may add a sudoers entry, so remove sudo and
         # any rule naming user, then assert. E2BSandbox also checks `sudo -n true` fails at every create.
         .run_cmd(["apt-get purge -y sudo >/dev/null 2>&1 || true",
                   "rm -f /usr/bin/sudo /etc/sudoers.d/* && (sed -i '/^user[[:space:]]/d' /etc/sudoers 2>/dev/null || true)",
                   "! su -s /bin/sh user -c 'sudo -n true' >/dev/null 2>&1"])
         .set_envs(RUN_ENV)  # build-time only on E2B; at run time E2BSandbox exports RUN_ENV in every command
         .set_user("user")
         .set_workdir("/work"))
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alias", help="default: the content-hashed name the server uses ([sandbox] template = auto)")
    ap.add_argument("--if-missing", action="store_true", help="skip the build when the alias already exists")
    ap.add_argument("--no-office", dest="office", action="store_false", help="leave out chromium (officecli screenshots need it)")
    ap.add_argument("--cpus", type=int, default=2)
    ap.add_argument("--memory-mb", type=int, default=2048)
    a = ap.parse_args()
    a.alias = a.alias or template_alias(a.office)
    if a.if_missing and Template.alias_exists(a.alias):
        return print(f"{a.alias} exists, nothing to build")
    info = Template.build(template(a.office), alias=a.alias, cpu_count=a.cpus, memory_mb=a.memory_mb,
                          on_build_logs=default_build_logger())
    print(info)


if __name__ == "__main__":
    main()
