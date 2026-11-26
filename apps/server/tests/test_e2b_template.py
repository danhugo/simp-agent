import importlib.util
from pathlib import Path

from e2b import Template

from simp_server.sandboxes import toolset

_p = Path(__file__).parents[1] / "sandboxes" / "e2b_template.py"
_spec = importlib.util.spec_from_file_location("e2b_template", _p)
tpl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tpl)


def test_template_toolset_is_fixed_and_read_only():
    df = Template.to_dockerfile(tpl.template())
    assert "/opt/simp/venv" in df and all(p in df for p in toolset.PIP) and all(a in df for a in toolset.APT)
    assert "chown -R root:root /opt/simp" in df and "chmod -R go-w /opt/simp" in df
    assert "PIP_USER" not in df and "NPM_CONFIG_PREFIX" not in df
    env_path = next(line for line in df.splitlines() if "PATH=" in line)
    assert "PATH=/opt/simp/venv/bin:" in env_path and "/home/user" not in env_path
    assert " chromium" in df and "chromium" not in Template.to_dockerfile(tpl.template(office=False))
    assert "libreoffice" not in df and "npm install --prefix /opt/simp/node" in df
    assert "COPY skills" not in df  # the user's skills are written at run time
    assert "NODE_PATH=/opt/simp/node/node_modules" in env_path


def test_prompt_list():
    s = toolset.prompt_list(office=False)
    assert "pandas" in s and "ffmpeg" in s and "/opt" not in s and "chromium" not in s.lower()
    assert "chromium" in toolset.prompt_list(office=True)


def test_docker_dev_image_is_the_template(monkeypatch):
    """No second Dockerfile to keep in sync: build_image feeds the template's Dockerfile to docker build."""
    import subprocess
    from simp_server.sandboxes import docker
    seen = dict()
    monkeypatch.setattr(subprocess, "run", lambda args, input: seen.update(args=args, df=input.decode()) or subprocess.CompletedProcess(args, 0))
    assert docker.build_image() == 0
    assert seen["args"][-1].endswith("apps/server") and "/opt/simp/office/reference.docx" in seen["df"]
    assert docker.DockerSandbox.has_skills and "pptxgenjs" in docker.DockerSandbox.prompt_hint
