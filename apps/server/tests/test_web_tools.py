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
    assert api.tools == ["show_cards", "web_search", "web_fetch"]
    with pytest.raises(ValueError):
        web.Web().setup(api, {"search": "bing"})


def test_og_image():
    html = '<head><meta property="og:image" content="/a.jpg"><meta name="twitter:image" content="https://x/b.jpg"></head>'
    assert web.og_image(html, "https://site.com/p") == "https://site.com/a.jpg"
    assert web.og_image('<meta name="twitter:image" content="https://x/b.jpg">', "https://s/") == "https://x/b.jpg"
    assert web.og_image("<p>none</p>", "https://s/") == ""
    assert web.og_image('<meta property="og:image" content="javascript:1">', "https://s/") == ""


def test_cards_fill_image_and_validate():
    import json
    calls = []

    def get(url):
        calls.append(url)
        if "dead" in url:
            raise WebError("HTTP 404")
        return url, "text/html", b'<meta property="og:image" content="https://cdn/x.png">'

    items = [{"url": "https://a.com", "title": "A"}, {"url": "https://b.com", "title": "B", "image": "https://i/b.jpg"},
             {"url": "https://dead.com", "title": "D"}, {"url": "ftp://bad", "title": "bad"}, "junk"]
    cards = json.loads(web.do_cards(items, get=get))["cards"]
    assert [c["image"] for c in cards] == ["https://cdn/x.png", "https://i/b.jpg", ""]
    assert sorted(calls) == ["https://a.com", "https://dead.com"]  # given image not refetched
    with pytest.raises(WebError):
        web.do_cards([{"url": "file:///etc/passwd"}], get=get)


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
