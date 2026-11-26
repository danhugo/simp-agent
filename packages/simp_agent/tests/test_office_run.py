"""office_run (code mode): the `office` runtime and the tool around it."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

from simp_agent.agent.env import LocalEnv
from simp_agent.plugins import office_rt
from simp_agent.plugins.office import Office

RT = office_rt.__file__
HAS_CLI = shutil.which("officecli") is not None


def run_script(tmp_path, code: str, fake: str | None = None):
    """Run code like office_run does (boot + runtime), return (exit code, output, state)."""
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    shutil.copy(RT, run / "office.py")
    (run / "main.py").write_text(textwrap.dedent(code))
    env = {**os.environ, "OFFICE_RUN_DIR": str(run), "OFFICE_SCRIPT": str(run / "main.py"), "PYTHONPATH": str(run)}
    if fake:
        env["OFFICECLI"] = fake
    boot = "import os, runpy, office\nrunpy.run_path(os.environ['OFFICE_SCRIPT'], init_globals={'office': office}, run_name='__main__')\n"
    p = subprocess.run([sys.executable, "-c", boot], cwd=tmp_path, env=env, capture_output=True, text=True)
    state = json.loads((run / "state.json").read_text()) if (run / "state.json").exists() else {}
    return p.returncode, p.stdout + p.stderr, state


@pytest.fixture
def fake_cli(tmp_path):
    """An officecli that logs its argv (and batch stdin) and answers success."""
    log = tmp_path / "calls.jsonl"
    bin_ = tmp_path / "fakecli"
    bin_.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, sys
        args = sys.argv[1:]
        stdin = sys.stdin.read() if args[0] == "batch" else None
        open({str(log)!r}, "a").write(json.dumps({{"args": args, "stdin": stdin}}) + "\\n")
        if args[0] == "batch":
            items = json.loads(stdin)
            res = [{{"index": i, "success": True, "output": f"Added x at /slide[1]/shape[@id={{100 + i}}]"}} for i in range(len(items))]
            print(json.dumps({{"success": True, "data": {{"results": res}}}}))
        else:
            print(json.dumps({{"success": True, "data": {{"results": []}}}}))
        """))
    bin_.chmod(0o755)
    (tmp_path / "a.pptx").write_bytes(b"x")

    def calls():
        return [json.loads(x) for x in log.read_text().splitlines()]
    return str(bin_), calls


def test_edits_are_queued_into_one_batch(tmp_path, fake_cli):
    bin_, calls = fake_cli
    code, out, state = run_script(tmp_path, """
        d = office.open("a.pptx")
        for i in range(10):
            d.add("/slide[1]", "shape", text=f"row {i}", bold=i == 0, font__latin="Arial")
        d.set("/slide[1]/shape[1]", y="2cm")
        d.query("shape")
    """, bin_)
    assert code == 0, out
    verbs = [c["args"][0] for c in calls()]
    assert verbs == ["open", "batch", "query", "close"], verbs
    items = json.loads(calls()[1]["stdin"])
    assert len(items) == 11
    assert items[0]["props"] == {"text": "row 0", "bold": "true", "font.latin": "Arial"}
    assert state["changed"] == [str(tmp_path / "a.pptx")]


def test_new_element_path_comes_from_the_batch(tmp_path, fake_cli):
    bin_, _ = fake_cli
    code, out, _ = run_script(tmp_path, """
        d = office.open("a.pptx")
        s = d.add("/slide[1]", "shape", text="x")
        print(s.path)
    """, bin_)
    assert code == 0 and "/slide[1]/shape[@id=100]" in out, out


def test_reads_only_do_not_mark_the_file_changed(tmp_path, fake_cli):
    bin_, _ = fake_cli
    code, out, state = run_script(tmp_path, 'office.open("a.pptx").query("shape")', bin_)
    assert code == 0 and state["changed"] == [], (out, state)


@pytest.mark.skipif(not HAS_CLI, reason="officecli not installed")
def test_failed_edit_names_the_script_line_and_applies_nothing(tmp_path):
    code, out, _ = run_script(tmp_path, """
        d = office.create("t.pptx")
        d.add("/", "slide")
        d.flush()
        d.add("/slide[1]", "shape", text="kept?")
        d.set("/slide[9]", text="x")
        try:
            d.flush()
        except office.OfficeError as e:
            print("ERR", e)
        print(len(d.query("shape")))
    """)
    assert code == 0, out
    assert 'line 6: d.set("/slide[9]", text="x")' in out and "Slide 9 not found" in out
    assert out.strip().endswith("0")  # atomic: the good add before it was rolled back too


@pytest.mark.skipif(not HAS_CLI, reason="officecli not installed")
def test_every_format(tmp_path):
    code, out, state = run_script(tmp_path, """
        p = office.create("t.pptx")
        p.add("/", "slide")
        for i in range(3):
            p.add("/slide[1]", "shape", text=f"Dòng {i} $'\\"", y=f"{i * 2}cm")
        print("pptx", len(p.query("shape")), p.validate())
        d = office.create("t.docx")
        d.add("/body", "paragraph", text="Hello")
        print("docx", d.view("text").strip())
        x = office.create("t.xlsx")
        x.set("/Sheet1/A1", value=5)
        x.set("/Sheet1/A2", formula="A1*2")
        print("xlsx", x.get("/Sheet1/A1").text)
        print("help", "shape" in office.help("pptx"))
        print("search", bool(office.search("shadow", "pptx")))
        print("dump", len(p.dump("/slide[1]")) > 0)
        print("shot", os.path.exists(p.screenshot(grid=True)))
    """.replace("os.path", "__import__('os').path"))
    assert code == 0, out
    for want in ("pptx 3 Validation passed", "Hello", "xlsx 5", "help True", "search True", "dump True", "shot True"):
        assert want in out, (want, out)
    assert len(state["changed"]) == 3 and len(state["images"]) == 1


@pytest.mark.skipif(not HAS_CLI, reason="officecli not installed")
async def test_office_run_tool(tmp_path):
    class Api:
        tools = {}

        def register_tool(self, t):
            self.tools[t.name] = t

    seen = []

    async def helper(system, text, urls):
        seen.append(len(urls))
        return "looks fine"

    class Ctx:
        env, cwd, cancel, state = LocalEnv(), str(tmp_path), asyncio.Event(), {"look": helper}

    api = Api()
    Office().setup(api, {})
    assert "office_edit" not in api.tools
    out = await api.tools["office_run"].execute({"code": textwrap.dedent("""
        d = office.create("r.pptx")
        d.add("/", "slide")
        d.add("/slide[1]", "shape", text="Hi")
        d.screenshot()
        print("done")
    """)}, Ctx())
    assert "done" in out and "Check r.pptx: no problems." in out and "looks fine" in out, out
    assert seen == [1]
    bad = await api.tools["office_run"].execute({"code": "x = 1\nraise ValueError('boom')\n"}, Ctx())
    assert 'main.py", line 2' in bad and "ValueError: boom" in bad and "runpy" not in bad, bad


def test_art_search_tint_and_icon_colour(tmp_path):
    """office.art: Iconify JSON found through NODE_PATH; whole-word search first; tint repaints by brightness."""
    for name, icons in (("fluent-emoji-flat", {"car": {"body": '<path fill="#FFCC00"/><path fill="#111111"/>'},
                                               "scarf": {"body": '<path fill="#0F0"/>'}}),
                        ("tabler", {"recycle": {"body": '<path stroke="currentColor"/>'}})):
        d = tmp_path / "node" / "@iconify-json" / name
        d.mkdir(parents=True)
        (d / "icons.json").write_text(json.dumps({"prefix": name, "width": 32, "height": 32, "icons": icons}))
    env_code = textwrap.dedent("""
        import os, builtins
        print(office.art_search("car"))
        print(builtins.open(office.art("car", tint=("#9EEFBC", "#1E2A8A"))).read())
        print(builtins.open(office.art("recycle", kind="icon", color="#ABCDEF")).read())
    """)
    run = tmp_path / "run"
    run.mkdir()
    shutil.copy(RT, run / "office.py")
    (run / "main.py").write_text(env_code)
    env = {**os.environ, "OFFICE_RUN_DIR": str(run), "OFFICE_SCRIPT": str(run / "main.py"), "PYTHONPATH": str(run),
           "NODE_PATH": str(tmp_path / "node")}
    boot = "import os, runpy, office\nrunpy.run_path(os.environ['OFFICE_SCRIPT'], init_globals={'office': office})\n"
    p = subprocess.run([sys.executable, "-c", boot], env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "['car', 'scarf']" in p.stdout
    assert 'fill="#9EEFBC"' in p.stdout and 'fill="#1E2A8A"' in p.stdout and "#FFCC00" not in p.stdout
    assert 'stroke="#ABCDEF"' in p.stdout
