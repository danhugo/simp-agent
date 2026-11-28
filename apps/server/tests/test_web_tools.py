import email.message
import io
import urllib.error

import pytest

from simp_server import web_tools as web
from simp_server.web_tools import WebError, check_url, do_fetch, do_search, html_to_text, http_get, parse_ddg

PUBLIC = lambda host: ["93.184.216.34"]

DDG = """<html><body>
<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x">Example <b>A</b></a>
<a class="result__snippet" href="#">First   snippet</a></div>
<div class="result"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a></div>
<table><tr><td><a rel="nofollow" href="https://b.org/" class='result-link'>B</a></td></tr>
<tr><td>&nbsp;</td><td class='result-snippet'>
  <b>Second</b></td></tr></table>
</body></html>"""


class Resp(io.BytesIO):
    def __init__(self, body, ctype="text/html"):
        super().__init__(body)
        self.headers = {"Content-Type": ctype}


def redirect(loc):
    h = email.message.Message()
    h["Location"] = loc
    return urllib.error.HTTPError("u", 302, "Found", h, None)


def test_parse_ddg():
    assert parse_ddg(DDG, 5) == [{"title": "Example A", "url": "https://example.com/a", "snippet": "First snippet"},
                                 {"title": "B", "url": "https://b.org/", "snippet": "Second"}]
    assert len(parse_ddg(DDG, 1)) == 1


def test_search_output_marked_untrusted():
    out = do_search("q", get=lambda url: (url, "text/html", DDG.encode()))
    assert out.startswith(web.UNTRUSTED) and "1. Example A\nhttps://example.com/a" in out


def test_html_to_text():
    src = "<html><head><title>t</title><style>x{}</style></head><body><nav>menu</nav><script>evil()</script>" \
          "<h1>Hi</h1><p>a   b\n c &amp; d</p></body></html>"
    assert html_to_text(src) == "Hi\n\na b c & d"


def test_fetch_truncates_and_json_as_is():
    out = do_fetch("https://x.com", max_chars=5, get=lambda u: (u, "application/json", b'{"temp": 12}'))
    assert out.startswith(web.UNTRUSTED) and '{"tem\n[truncated: 7 more chars]' in out and "application/json" in out


@pytest.mark.parametrize("url", ["http://localhost/", "http://10.0.0.1/", "http://169.254.169.254/latest/meta-data",
                                 "http://[::1]/", "http://127.0.0.1/", "http://192.168.1.1/", "http://[::ffff:127.0.0.1]/",
                                 "http://224.0.0.1/", "http://[fe80::1]/"])
def test_ssrf_refused(url):
    with pytest.raises(WebError, match="non-public"):
        check_url(url)  # real resolver: literals and localhost resolve offline


@pytest.mark.parametrize("url,msg", [("file:///etc/passwd", "scheme"), ("ftp://a.com/", "scheme"),
                                     ("http://a.com:8080/", "port"), ("https://a.com:22/", "port")])
def test_scheme_port_refused(url, msg):
    with pytest.raises(WebError, match=msg):
        check_url(url, PUBLIC)


def test_redirect_to_private_refused():
    hops = []

    def open_(url):
        hops.append(url)
        raise redirect("http://169.254.169.254/")

    resolve = lambda h: ["169.254.169.254"] if h.startswith("169.") else ["93.184.216.34"]
    with pytest.raises(WebError, match="non-public"):
        http_get("https://ok.com/", open_, resolve)
    assert hops == ["https://ok.com/"]


def test_redirects_followed_and_capped():
    seq = iter([redirect("/b"), Resp(b"hi", "text/plain")])

    def open_(url):
        r = next(seq)
        if isinstance(r, Exception):
            raise r
        return r

    assert http_get("https://ok.com/a", open_, PUBLIC) == ("https://ok.com/b", "text/plain", b"hi")

    def loop(url):
        raise redirect("/again")

    with pytest.raises(WebError, match="too many redirects"):
        http_get("https://ok.com/", loop, PUBLIC)


def test_size_cap():
    big = b"x" * (web.MAX_BYTES + 10)
    assert len(http_get("https://ok.com/", lambda u: Resp(big), PUBLIC)[2]) == web.MAX_BYTES


def test_plugin_registers_tools():
    class Api:
        tools = []

        def register_tool(self, t):
            self.tools.append(t.name)

        def add_prompt_section(self, name, text, order):
            self.section = text

    api = Api()
    web.Web().setup(api, {})
    assert api.tools == ["web_search", "web_fetch", "web_download"]
    with pytest.raises(ValueError):
        web.Web().setup(api, {"search": "bing"})


def test_tavily_images_name_their_page():
    def post(url, payload, key):
        assert payload["include_images"] is True
        return {"results": [{"url": "https://www.trip.com/qingdao/guide"}],
                "images": ["https://ak-d.trip.com/a.jpg", "https://cdn.other.net/b.jpg", "http://plain/c.jpg",
                           "https://upload.wikimedia.org/wikipedia/commons/3/3d/Pier.jpg"]}
    got = web.tavily_images("pier", "k", post=post, count=5)
    assert got == [{"url": "https://ak-d.trip.com/a.jpg", "page": "https://www.trip.com/qingdao/guide"},  # same site
                   {"url": "https://cdn.other.net/b.jpg", "page": "https://cdn.other.net/b.jpg"},  # no page: itself
                   {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3d/Pier.jpg/1280px-Pier.jpg",
                    "page": "https://commons.wikimedia.org/wiki/File:Pier.jpg"}]  # original -> thumbnail; http:// dropped


def test_find_images_falls_back_to_commons(monkeypatch):
    monkeypatch.setattr(web, "tavily_images", lambda q, k: (_ for _ in ()).throw(WebError("HTTP 401")))
    monkeypatch.setattr(web, "commons_images", lambda q: [{"url": "https://c/x.jpg", "page": "https://c/File:x"}])
    assert web.find_images("pier", "bad-key") == [{"url": "https://c/x.jpg", "page": "https://c/File:x"}]
    monkeypatch.setattr(web, "tavily_images", lambda q, k: [{"url": "https://t/y.jpg", "page": "https://t/"}])
    assert web.find_images("pier", "key")[0]["url"] == "https://t/y.jpg"


def fake_post(calls, reply):
    def post(url, payload, key):
        calls.append((url, payload, key))
        if isinstance(reply, Exception):
            raise reply
        return reply
    return post


def test_tavily_search_maps_results():
    calls = []
    post = fake_post(calls, {"results": [{"title": "T", "url": "https://t.com", "content": "snip  pet"}]})
    out = do_search("q", 3, get=None, key="tv-secret", post=post)
    assert "1. T\nhttps://t.com\nsnip pet" in out and out.startswith(web.UNTRUSTED)
    assert calls[0][0] == "https://api.tavily.com/search" and calls[0][1]["max_results"] == 3
    assert "tv-secret" not in out
    assert calls[0][1]["include_raw_content"] == "markdown" and calls[0][1]["search_depth"] == "basic"


def test_tavily_search_shows_the_page_start():
    page = "# Title\n" + "word " * 2000
    post = fake_post([], {"results": [{"title": "T", "url": "https://t.com", "content": "c", "raw_content": page}]})
    out = do_search("q", 1, get=None, key="k", post=post)
    assert "--- page ---\n# Title" in out and "[truncated:" in out and len(out) < 4500


def test_search_falls_back_to_ddg():
    get = lambda u: (u, "text/html", DDG.encode())
    assert "https://example.com/a" in do_search("q", 5, get=get, key=None)  # no key
    post = fake_post([], WebError("HTTP 500 from tavily"))
    assert "https://example.com/a" in do_search("q", 5, get=get, key="k", post=post)  # tavily down


def test_fetch_falls_back_to_extract_on_403():
    def get(u):
        raise WebError(f"HTTP 403 from {u}")
    calls = []
    post = fake_post(calls, {"results": [{"url": "https://s.com", "raw_content": "page text"}]})
    out = do_fetch("https://s.com", get=get, key="k", post=post)
    assert "page text" in out and calls[0][0] == "https://api.tavily.com/extract"
    with pytest.raises(WebError):
        do_fetch("https://s.com", get=get, key=None)


def test_fetch_raw_returns_html():
    out = do_fetch("https://x.com", get=lambda u: (u, "text/html", b"<html><script>api('/r')</script></html>"), raw=True)
    assert "<script>api('/r')</script>" in out


def test_download_returns_bytes_and_caps_size():
    png = b"\x89PNG" + b"x" * 100
    assert web.do_download("https://ok.com/a.png", get=lambda u, max_bytes: (u, "image/png", png)) == png
    big = b"x" * (web.DOWNLOAD_MAX + 1)
    with pytest.raises(WebError, match="too large"):
        web.do_download("https://ok.com/b.bin", get=lambda u, max_bytes: (u, "", big))


def test_http_get_max_bytes():
    body = b"x" * (web.MAX_BYTES + 10)
    assert len(http_get("https://ok.com/", lambda u: Resp(body), PUBLIC, max_bytes=web.MAX_BYTES + 5)[2]) == web.MAX_BYTES + 5


class _Env:
    def __init__(self):
        self.written = {}

    async def write_bytes(self, path, data):
        self.written[path] = data


class _Ctx:
    def __init__(self):
        self.cwd, self.env = "/work", _Env()


def _dl_tool():
    return next(t for t in web.make_tools() if t.name == "web_download")


async def test_download_tool_saves_many_files_in_one_call(monkeypatch):
    def fake(url):
        if "bad" in url:
            raise WebError("HTTP 404 from " + url)
        return url[-1].encode()
    monkeypatch.setattr(web, "do_download", fake)
    ctx = _Ctx()
    out = await _dl_tool().execute({"files": [{"url": "https://a.com/1", "path": "img/1"},
                                              {"url": "https://a.com/bad", "path": "img/x"},
                                              {"url": "https://b.com/2", "path": "/work/img/2"}]}, ctx)
    assert ctx.env.written == {"/work/img/1": b"1", "/work/img/2": b"2"}
    assert "saved 1 bytes to /work/img/1" in out and "HTTP 404" in out and "saved 1 bytes to /work/img/2" in out


async def test_download_tool_flags_a_domain_that_keeps_refusing(monkeypatch):
    monkeypatch.setattr(web, "do_download", lambda url: (_ for _ in ()).throw(WebError("HTTP 403 from " + url)))
    tool = _dl_tool()
    out = await tool.execute({"files": [{"url": "https://cdn.x.com/a", "path": "a"},
                                        {"url": "https://cdn.x.com/b", "path": "b"}]}, _Ctx())
    assert "cdn.x.com blocks automated downloads" in out


def test_http_error_carries_the_page_reason():
    def deny(u):
        raise urllib.error.HTTPError(u, 400, "Bad", {}, io.BytesIO(b"<html><body><h1>Error</h1><p>Use thumbnail sizes listed on https://w.wiki/GHai</p></body></html>"))
    with pytest.raises(WebError, match="Use thumbnail sizes listed"):
        http_get("https://ok.com/x.jpg", deny, PUBLIC)


async def test_fetch_with_prompt_returns_only_the_helper_answer(monkeypatch):
    """web_fetch(prompt=...): a cheap model reads the whole page; only its answer enters the chat context."""
    page = "x" * 50_000 + " license CC BY 4.0"
    real = web.do_fetch
    monkeypatch.setattr(web, "do_fetch", lambda url, n, **kw: real(url, n, get=lambda u: (u, "application/json", page.encode()), **kw))
    seen = []

    async def extract(q, text):
        seen.append((q, len(text)))
        return "- a.jpg, CC BY 4.0"
    fetch = next(t for t in web.make_tools(extract=extract) if t.name == "web_fetch")
    assert "prompt" in fetch.parameters["properties"]
    out = await fetch.execute({"url": "https://x.com/api", "prompt": "image licenses"}, None)
    assert out.startswith(web.UNTRUSTED) and "URL: https://x.com/api" in out and out.endswith("- a.jpg, CC BY 4.0")
    assert seen == [("image licenses", len(page))]  # the helper got the whole page, not the 20k cut
    assert len(out) < 500
    plain = await fetch.execute({"url": "https://x.com/api"}, None)  # no prompt: the page as before
    assert "[truncated" in plain and len(seen) == 1


async def test_fetch_prompt_falls_back_to_page_when_helper_fails(monkeypatch):
    real = web.do_fetch
    monkeypatch.setattr(web, "do_fetch", lambda url, n, **kw: real(url, n, get=lambda u: (u, "text/plain", b"hello page"), **kw))

    async def extract(q, text):
        raise RuntimeError("budget")
    fetch = next(t for t in web.make_tools(extract=extract) if t.name == "web_fetch")
    out = await fetch.execute({"url": "https://x.com", "prompt": "q"}, None)
    assert "[extract failed: budget" in out and out.endswith("hello page")


def test_no_extract_no_prompt_param():
    fetch = next(t for t in web.make_tools() if t.name == "web_fetch")
    assert "prompt" not in fetch.parameters["properties"]


def test_image_queries_from_answer_blocks():
    text = ("Intro\n```images\nZhanqiao  Pier | Cầu tàu | note | https://x\nBadaguan | B\n```\n"
            "```python\nnot | pictures\n```\n```images\nZhanqiao Pier | again\n\n```")
    assert web.image_queries(text) == ["Zhanqiao Pier", "Badaguan"]
    assert web.image_queries("no blocks") == []


async def test_resolve_images_signs_every_picture(monkeypatch):
    def find(q, key):
        if q == "bad":
            raise WebError("down")
        return [{"url": f"https://p/{q}.jpg", "page": "https://site/"}]
    monkeypatch.setattr(web, "find_images", find)
    got = await web.resolve_images("```images\nA | a\nbad | b\n```", "k", lambda u: "signed:" + u)
    assert got == {"A": [{"src": "signed:https://p/A.jpg", "page": "https://site/"}], "bad": []}
