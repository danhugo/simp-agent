"""`office`: officecli as a Python API, for scripts the agent runs with office_run (code mode).

Runs inside the sandbox (stdlib only; office_run copies this file next to the script). Edits (add/set/remove/move/swap)
are queued and sent as one atomic `officecli batch` before the next read, save, close or the end of the script, so a
loop of 100 edits costs one call. Reads return Python data parsed from `--json`. Every officecli feature that works on a
file has a function here; anything else goes through office.cli(...).

    d = office.open("deck.pptx")                       # or office.create("new.pptx")
    for s in d.query("shape:contains('2025')"):
        d.set(s.path, text=s.text.replace("2025", "2026"))
    d.add("/slide[2]/table[1]", "row", text="New row")
    print(d.view("outline"))
    d.screenshot(grid=True)                             # shown to the model after the run
"""

from __future__ import annotations

import atexit
import builtins
import json
import os
import subprocess
import sys
import tempfile
import traceback

__all__ = ["open", "create", "cli", "help", "search", "merge", "OfficeError", "Node"]

BIN = os.environ.get("OFFICECLI", "officecli")
RUN_DIR = os.environ.get("OFFICE_RUN_DIR") or tempfile.mkdtemp(prefix="office-")
SCRIPT = os.environ.get("OFFICE_SCRIPT", "")  # the agent's script: errors point at its lines
_docs: dict[str, "Doc"] = {}
_images: list[str] = []
_warnings: list[str] = []
_made: set[str] = set()  # files written without a Doc (merge)


class OfficeError(Exception):
    pass


def _where() -> str:
    """'main.py:12' for the line of the agent's script that made the current call."""
    for f in reversed(traceback.extract_stack()[:-2]):
        if SCRIPT and os.path.abspath(f.filename) == os.path.abspath(SCRIPT):
            return f"line {f.lineno}: {(f.line or '').strip()}"
    return ""


def _str(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(_str(x) for x in v)
    return str(v)


def _props(props: dict) -> dict:
    return {k.replace("__", "."): _str(v) for k, v in props.items() if v is not None}


def _call(args: list, stdin: str | None = None, raw: bool = False):
    """Run officecli with --json; return its data, raise OfficeError on failure. raw: return stdout text."""
    p = subprocess.run([BIN, *[str(a) for a in args], *([] if raw else ["--json"])], input=stdin,
                       capture_output=True, text=True)
    if raw:
        if p.returncode not in (0, 2):
            raise OfficeError((p.stderr or p.stdout).strip())
        return p.stdout
    try:
        env = json.loads(p.stdout)
    except ValueError:
        if p.returncode in (0, 2):
            return p.stdout.strip()
        raise OfficeError((p.stderr or p.stdout).strip() or f"officecli exit {p.returncode}") from None
    for w in env.get("warnings") or []:
        _warnings.append(w.get("message", str(w)) if isinstance(w, dict) else str(w))
    if not env.get("success", p.returncode == 0):
        e = env.get("error")
        if isinstance(e, dict):
            msg = e.get("error", "") + (f" ({e['suggestion']})" if e.get("suggestion") else "")
        else:
            msg = e or env.get("message") or "failed"
        if env.get("warnings"):
            msg += "".join(f"\n  {w}" for w in _warnings[-len(env["warnings"]):])
        raise OfficeError(msg)
    return env.get("data")


class Node:
    """An element from get/query: .path .type .text .props (format) .children; .set(**props) and .remove() queue edits."""

    def __init__(self, doc: "Doc", d: dict):
        self.doc, self.raw = doc, d
        self.path, self.type = d.get("path", ""), d.get("type", "")
        self.text = d.get("text", d.get("preview", "")) or ""
        self.props = d.get("format") or {}
        self.children = [Node(doc, c) for c in d.get("children") or []]

    def set(self, **props) -> None:
        self.doc.set(self.path, **props)

    def remove(self) -> None:
        self.doc.remove(self.path)

    def __getitem__(self, k):
        return self.props[k]

    def __repr__(self):
        t = f" {self.text[:40]!r}" if self.text else ""
        return f"<{self.type} {self.path}{t}>"


class Pending:
    """The result of a queued add: .path flushes the queue and gives the new element's path."""

    def __init__(self, doc: "Doc"):
        self.doc, self._path = doc, None

    @property
    def path(self) -> str:
        if self._path is None:
            self.doc.flush()
        return self._path or ""

    def __str__(self):
        return self.path

    def __repr__(self):
        return f"<added {self.path}>"


class Doc:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._queue: list[tuple[dict, str, Pending | None]] = []
        self.changed = False

    # ---- edits (queued) ----
    def _q(self, item: dict, pending: Pending | None = None):
        self._queue.append((item, _where(), pending))
        self.changed = True
        return pending

    def add(self, parent: str, type: str, *, before: str | None = None, after: str | None = None,
            index: int | None = None, **props) -> Pending:
        """Add an element of `type` (slide, shape, table, row, paragraph, chart, picture, cell...) under parent.
        Props are officecli props (see office.help); use __ for a dot: font__latin='Arial'."""
        item = {"command": "add", "parent": parent, "type": type, "props": _props(props)}
        for k, v in (("before", before), ("after", after), ("index", index)):
            if v is not None:
                item[k] = _str(v)
        return self._q(item, Pending(self))

    def set(self, path: str, **props) -> None:
        self._q({"command": "set", "path": path, "props": _props(props)})

    def remove(self, path: str) -> None:
        self._q({"command": "remove", "path": path})

    def move(self, path: str, *, to: str | None = None, before: str | None = None, after: str | None = None,
             index: int | None = None) -> None:
        item = {"command": "move", "path": path}
        for k, v in (("to", to), ("before", before), ("after", after), ("index", index)):
            if v is not None:
                item[k] = _str(v)
        self._q(item)

    def swap(self, path1: str, path2: str) -> None:
        self._q({"command": "swap", "path": path1, "path2": path2})

    def flush(self) -> None:
        """Send queued edits as one atomic batch (all apply or none)."""
        if not self._queue:
            return
        queue, self._queue = self._queue, []
        p = subprocess.run([BIN, "batch", self.path, "--json"], input=json.dumps([q[0] for q in queue], ensure_ascii=False),
                           capture_output=True, text=True)
        try:
            data = json.loads(p.stdout).get("data") or {}
        except ValueError:
            raise OfficeError((p.stderr or p.stdout).strip() or "batch failed") from None
        results = data.get("results") or []
        bad = [r for r in results if not r.get("success")]
        if bad or p.returncode == 1:
            lines = [f"{len(bad) or '?'} of {len(queue)} queued edits failed; none were applied:"]
            for r in bad[:10]:
                where = queue[r["index"]][1] if r.get("index") is not None and r["index"] < len(queue) else ""
                lines.append(f"  {where or queue[r.get('index', 0)][0]} -> {r.get('error', 'failed')}")
            raise OfficeError("\n".join(lines))
        for r in results:
            pend = queue[r["index"]][2]
            out = r.get("output") or ""
            if pend is not None and " at " in out:
                pend._path = out.rsplit(" at ", 1)[1].strip()

    # ---- reads (flush first) ----
    def get(self, path: str = "/", depth: int | None = None) -> Node:
        self.flush()
        data = _call(["get", self.path, path, *(["--depth", depth] if depth is not None else [])])
        res = data.get("results", [data]) if isinstance(data, dict) else [data]
        return Node(self, res[0])

    def query(self, selector: str) -> list[Node]:
        """CSS-like selectors: 'shape', 'shape:contains(\"Q3\")', 'slide[2] > shape', 'cell[value>100]'."""
        self.flush()
        data = _call(["query", self.path, selector])
        return [Node(self, r) for r in (data or {}).get("results", [])]

    def view(self, mode: str = "outline", **opts):
        """mode: text, annotated (text with element paths), outline, stats, issues, forms, html.
        opts: start, end, max_lines, type, limit, cols, range, page. Returns text (json=True for parsed data)."""
        self.flush()
        as_json = opts.pop("json", False)
        args = ["view", self.path, mode]
        for k, v in opts.items():
            args += [f"--{k.replace('_', '-')}", _str(v)]
        return _call(args) if as_json else _call(args, raw=True)

    def issues(self, type: str | None = None) -> list:
        self.flush()
        data = _call(["view", self.path, "issues", *(["--type", type] if type else [])])
        return (data or {}).get("issues", []) if isinstance(data, dict) else data

    def stats(self):
        return self.view("stats", json=True)

    def validate(self) -> str:
        self.flush()
        return _call(["validate", self.path])

    def raw(self, part: str = "/document") -> str:
        """Raw XML of a part: /document /styles /slide[1] /Sheet1 ..."""
        self.flush()
        return _call(["raw", self.path, part], raw=True)

    def dump(self, path: str = "/") -> list:
        """The subtree as replayable batch items (feed to office.replay)."""
        self.flush()
        return _call(["dump", self.path, path])

    # ---- low level ----
    def raw_set(self, part: str, xpath: str, action: str, xml: str | None = None):
        """action: append, prepend, insertbefore, insertafter, replace, remove, setattr (xml='attr=value')."""
        self.flush()
        self.changed = True
        return _call(["raw-set", self.path, part, "--xpath", xpath, "--action", action, *(["--xml", xml] if xml else [])])

    def add_part(self, parent: str, type: str) -> str:
        """New part (chart, header, footer); returns its relationship id for raw_set."""
        self.flush()
        self.changed = True
        return _call(["add-part", self.path, parent, "--type", type])

    def refresh(self):
        """Recalculate fields (TOC, PAGE...). .docx needs Word on Windows: fails in the sandbox."""
        self.flush()
        self.changed = True
        return _call(["refresh", self.path])

    def import_csv(self, sheet: str, csv_path: str, *, header: bool = False, start_cell: str = "A1",
                   delimiter: str | None = None, decimal: str | None = None):
        """Load a CSV/TSV into an .xlsx sheet (sheet='/Sheet1')."""
        self.flush()
        self.changed = True
        args = ["import", self.path, sheet, os.path.abspath(csv_path), "--start-cell", start_cell]
        args += ["--header"] if header else []
        args += ["--delimiter", delimiter] if delimiter else []
        args += ["--decimal", decimal] if decimal else []
        return _call(args)

    def replay(self, items: list) -> None:
        """Queue raw batch items (e.g. from dump()) as they are."""
        for it in items:
            self._q(dict(it))

    # ---- look ----
    def screenshot(self, page=1, *, grid=None, range: str | None = None, width: int = 1600, height: int = 1200,
                   out: str | None = None, show: bool = True) -> str:
        """PNG of a page/slide (page=1, '2-4'), a contact sheet of all (grid=True or a column count), or one element
        (range='/slide[1]/shape[@id=3]', 'Sheet1!A1:D9'). show=True: the model sees it after the run."""
        self.flush()
        out = os.path.abspath(out or os.path.join(RUN_DIR, f"shot-{len(_images) + 1}.png"))
        args = ["view", self.path, "screenshot", "-o", out, "--screenshot-width", width, "--screenshot-height", height]
        if grid:
            args += ["--grid", "auto" if grid is True else grid]
        else:
            args += ["--page", _str(page)]
        if range:
            args += ["--range", range]
        try:
            _call(args)
        except OfficeError as e:
            if "headless browser" not in str(e) or range:
                raise
            self._shot_via_pdf(out, page, grid, width)  # no browser in the sandbox: LibreOffice -> PDF -> PNG
        if show:
            _images.append(out)
        return out

    def _shot_via_pdf(self, out: str, page, grid, width: int) -> None:
        if self.path.endswith(".xlsx"):
            raise OfficeError("screenshot of .xlsx needs a browser here; print d.view('text', range='Sheet1!A1:F20')")
        self.save()
        tmp = tempfile.mkdtemp(dir=RUN_DIR)
        p = subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp, self.path],
                           capture_output=True, text=True, timeout=180)
        pdf = os.path.join(tmp, os.path.splitext(os.path.basename(self.path))[0] + ".pdf")
        if not os.path.exists(pdf):
            raise OfficeError(f"screenshot failed (LibreOffice): {(p.stderr or p.stdout).strip()[-300:]}")
        first, _, last = _str(page).partition("-")
        rng = [] if grid else ["-f", first, "-l", last or first]
        cols = 800 if grid else width
        subprocess.run(["pdftoppm", "-png", "-scale-to-x", str(cols), "-scale-to-y", "-1", *rng, pdf, f"{tmp}/p"],
                       check=True, capture_output=True)
        pages = sorted(f for f in os.listdir(tmp) if f.startswith("p") and f.endswith(".png"))
        if not pages:
            raise OfficeError(f"no page {page}")
        if len(pages) == 1:
            os.replace(os.path.join(tmp, pages[0]), out)
            return
        n = grid if isinstance(grid, int) and grid is not True else max(1, round(len(pages) ** 0.5 + 0.49))
        subprocess.run(["montage", *[os.path.join(tmp, f) for f in pages], "-tile", f"{n}x", "-geometry", "+8+8",
                        "-background", "#888888", out], check=True, capture_output=True)

    def export(self, out: str, mode: str | None = None) -> str:
        """Write pdf / html / svg (mode from out's extension)."""
        self.flush()
        mode = mode or os.path.splitext(out)[1].lstrip(".").lower()
        _call(["view", self.path, mode, "-o", os.path.abspath(out)])
        return out

    # ---- lifecycle ----
    def save(self) -> None:
        self.flush()
        _call(["save", self.path])

    def close(self) -> None:
        try:
            self.flush()
        finally:
            if self.changed:
                _made.add(self.path)
            _call(["close", self.path])
            _docs.pop(self.path, None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f"<office doc {self.path}>"


def open(path: str) -> Doc:  # noqa: A001 - the API reads best as office.open
    """Open an existing .pptx/.docx/.xlsx (kept in memory for fast calls; closed at the end of the script)."""
    p = os.path.abspath(path)
    if p in _docs:
        return _docs[p]
    if not os.path.exists(p):
        raise OfficeError(f"{path} does not exist (office.create makes a new file)")
    _call(["open", p])
    _docs[p] = d = Doc(p)
    return d


def create(path: str, *, force: bool = False, locale: str | None = None) -> Doc:
    """A blank .pptx/.docx/.xlsx. force=True replaces an existing file."""
    p = os.path.abspath(path)
    if os.path.exists(p):
        if not force:
            raise OfficeError(f"{path} exists; office.open it, or create(..., force=True) to replace it")
        if p in _docs:
            _docs.pop(p)._queue.clear()
        subprocess.run([BIN, "close", p], capture_output=True)
        os.remove(p)
    _call(["create", p, *(["--locale", locale] if locale else [])])
    _call(["open", p])
    _docs[p] = d = Doc(p)
    d.changed = True
    return d


def merge(template: str, out: str, data: dict, *, force: bool = False) -> str:
    """Fill {{key}} placeholders of a template file into out."""
    _call(["merge", os.path.abspath(template), os.path.abspath(out), "--data", json.dumps(data, ensure_ascii=False),
           *(["--force"] if force else [])])
    _made.add(os.path.abspath(out))
    return out


def help(fmt: str, element: str | None = None, verb: str | None = None) -> str:  # noqa: A001
    """The officecli reference: help('pptx') lists elements; help('pptx', 'shape') its properties;
    help('xlsx', 'cell', verb='set') only what set takes."""
    return _call(["help", fmt, *([verb] if verb else []), *([element] if element else [])], raw=True)


def search(word: str, fmt: str | None = None, limit: int = 40) -> list[str]:
    """Find elements/properties whose name or description mentions word (e.g. search('shadow', 'pptx'))."""
    out = _call(["help", "all", "--jsonl"], raw=True)
    hits, w = [], word.lower()
    for line in out.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") == "meta" or (fmt and r.get("format") != fmt):
            continue
        if w in json.dumps(r, ensure_ascii=False).lower():
            name = f"{r.get('element')}.{r['name']}" if r.get("kind") == "PROP" else f"{r.get('element')} (element)"
            vals = f" [{', '.join(map(str, r['values'][:8]))}]" if r.get("values") else ""
            hits.append(f"{r.get('format')} {name}{vals}: {(r.get('description') or '')[:110]}")
            if len(hits) >= limit:
                break
    return hits


def cli(*args, json_out: bool = True):
    """Any officecli command, args as a list (no shell quoting): office.cli('view', 'a.pptx', 'stats')."""
    return _call(list(args), raw=not json_out)


def _finish() -> None:
    """At exit: send queued edits, close every file, tell office_run what changed and what to show."""
    changed = sorted(d.path for d in _docs.values() if d.changed) + sorted(_made)
    for d in list(_docs.values()):
        try:
            d.close()
        except Exception as e:  # report, keep closing the others
            print(f"office: {d.path}: {e}", file=sys.stderr)
    try:
        with builtins.open(os.path.join(RUN_DIR, "state.json"), "w") as f:
            json.dump({"changed": sorted(set(changed)), "images": _images, "warnings": _warnings[-20:]}, f)
    except OSError:
        pass


atexit.register(_finish)
