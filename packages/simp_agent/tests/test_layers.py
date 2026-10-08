"""Layer rule: ai <- agent <- coding <- session <- plugins <- testing. A lower layer never imports a higher one; core never imports apps."""

import ast
from pathlib import Path

PKG = Path(__file__).parent.parent / "src" / "simp_agent"
LAYERS = ["ai", "agent", "coding", "session", "plugins", "testing"]
APPS = ("simp_cli", "simp_server")


def layer_of(parts: list) -> str | None:
    first = parts[0].removesuffix(".py") if parts else None
    return first if first in LAYERS else None


def imports(path: Path) -> list:
    """Imported simp_agent subpackages, as path parts relative to the package root."""
    here = list(path.relative_to(PKG).parent.parts)
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".") if node.module else []
            if node.level:
                base = here[: len(here) - node.level + 1]
            elif mod[0] == "simp_agent":
                base, mod = [], mod[1:]
            elif mod[0] in APPS:
                out.append(["APP:" + mod[0]])
                continue
            else:
                continue
            target = base + mod
            out += [target] if target else [[a.name] for a in node.names]  # `from .. import ai`
        elif isinstance(node, ast.Import):
            out += [n.name.split(".")[1:] for n in node.names if n.name.startswith("simp_agent.")]
            out += [["APP:" + n.name.split(".")[0]] for n in node.names if n.name.split(".")[0] in APPS]
    return out


def test_layers():
    bad = []
    for path in PKG.rglob("*.py"):
        src = layer_of(list(path.relative_to(PKG).parts))
        for target in imports(path):
            if target[0].startswith("APP:"):
                bad.append(f"{path.relative_to(PKG)} imports app {target[0][4:]}")
                continue
            dst = layer_of(target)
            if dst is None or src == dst:
                continue
            if src is None or LAYERS.index(dst) > LAYERS.index(src):
                bad.append(f"{path.relative_to(PKG)} imports {dst}")
    assert not bad, bad
