"""The proxy's landing page is documentation that ships inside the code.

Documentation in a docstring rots quietly. This page is worse: it tells
someone who is *already unsure whether the proxy works* what to type, so
a wrong URL or an unsubstituted placeholder reads as "the proxy is
broken" rather than "the docs are stale".

Everything here runs offline against a stub credential source -- no
Earth Engine, no listening socket.
"""
import json
import re

import pytest


def _client(tenants=("prod-tenant", "adc-default"), project="my-ee-project"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from geeViz.eeAuth.server import build_proxy_router

    class StubCreds:
        def list(self):
            return list(tenants)

        def project_for(self, tenant):
            return project

        def get_token(self, *a, **k):
            return "not-a-real-token"

    app = FastAPI()
    app.include_router(build_proxy_router(creds=StubCreds()), prefix="/ee-api")
    return TestClient(app)


def _blocks(html):
    """The <pre> code samples, unescaped, as a reader would copy them."""
    import html as _h
    return [_h.unescape(b).strip()
            for b in re.findall(r"<pre>(.*?)</pre>", html, re.S)]


@pytest.mark.parametrize("path", ["/ee-api", "/ee-api/"])
def test_the_page_renders_with_and_without_the_trailing_slash(path):
    """``/ee-api`` used to be a 307 with an EMPTY BODY.

    A browser follows the redirect, so nobody noticed; curl, Insomnia and
    Postman do not follow by default. The first thing anyone tries by
    hand therefore came back blank, from what looked like a dead server.
    """
    r = _client().get(path, follow_redirects=False)
    assert r.status_code == 200, (
        f"{path} returned {r.status_code}, not a rendered page — a client "
        f"that does not follow redirects sees an empty response")
    assert "text/html" in r.headers["content-type"]
    assert "geeViz eeAuth proxy" in r.text


def test_the_health_link_on_the_page_actually_resolves():
    """The page advertises a health URL. Following it must give JSON, not
    a 404 and not the HTML page again -- which is exactly the failure
    that would look like "the health endpoint is blank"."""
    c = _client()
    html = c.get("/ee-api/").text
    links = re.findall(r'href="([^"]*health[^"]*)"', html)
    assert links, "the page no longer advertises a health URL"
    for url in links:
        path = re.sub(r"^https?://[^/]+", "", url)
        r = c.get(path)
        assert r.status_code == 200, f"advertised health URL {url} -> {r.status_code}"
        assert r.headers["content-type"].startswith("application/json"), (
            f"{url} returned {r.headers['content-type']}, not JSON")
        assert r.json()["ok"] is True


def test_the_examples_use_a_real_tenant_and_project_when_one_is_known():
    """``<tenant-name>`` in a copied curl line is the difference between
    a command that runs and a 404 for someone already unsure whether the
    proxy works. Substitute when the answer is knowable."""
    html = _client().get("/ee-api/").text
    samples = "\n".join(_blocks(html))
    assert "adc-default" in samples, "no registered tenant reached the examples"
    assert "my-ee-project" in samples, "no project reached the examples"
    leftover = set(re.findall(r"<(tenant-name|your-ee-project)>", samples))
    assert not leftover, f"unsubstituted placeholder in a code sample: {leftover}"


def test_placeholders_survive_when_nothing_is_registered():
    """The other half of the previous test: with no tenants there is
    nothing true to substitute, and inventing one would be worse."""
    html = _client(tenants=(), project=None).get("/ee-api/").text
    assert "<tenant-name>" in "\n".join(_blocks(html))


def test_every_json_payload_in_the_examples_is_valid_json():
    """These are pasted into curl and Insomnia verbatim. A stray comma
    turns a working example into a 400 that reads as a proxy fault.

    The payloads are hand-written inside an f-string with doubled braces,
    which is precisely the kind of thing that breaks silently.
    """
    html = _client().get("/ee-api/").text
    found = 0
    for blk in _blocks(html):
        for m in re.finditer(r'\{"expression".*?\}\}\}\}+', blk, re.S):
            json.loads(m.group(0))          # raises if malformed
            found += 1
    assert found >= 2, (
        f"only found {found} EE expression payloads to check; the examples "
        f"changed shape and this test is no longer looking at them")


def test_the_examples_never_show_a_hand_supplied_bearer_token():
    """Minting the token is the proxy's entire job. An example that adds
    an Authorization header teaches the one thing guaranteed to fail --
    it is forwarded, and upstream rejects it."""
    html = _client().get("/ee-api/").text
    body = "\n".join(_blocks(html)).lower()
    assert "authorization" not in body
    assert "bearer " not in body


def test_the_page_names_every_way_to_select_a_tenant():
    """Three mechanisms exist; a reader who knows only the header form
    cannot make a browser tab work, because an <img> tag fetching a map
    tile cannot carry one."""
    from geeViz.eeAuth.server import build_proxy_router  # noqa: F401
    html = _client().get("/ee-api/").text
    assert "X-geeViz-Creds" in html, "header form missing"
    assert "/t/" in html, "URL-path form missing"
    assert re.search(r"\?\w*[Tt]enant\w*=", html), "query-param form missing"


def test_the_page_needs_no_network_to_render():
    """No external CSS, JS, fonts or images. It is served on air-gapped
    networks and, more to the point, is read when something is already
    wrong -- a spinner waiting on a CDN is the last thing wanted."""
    html = _client().get("/ee-api/").text
    # Only things the BROWSER fetches on its own. An <a href> to the
    # proxy's own health endpoint is a hyperlink the reader may click,
    # not an asset, and flagging it would make this test noise.
    assets = re.findall(r'<(?:script|img|iframe)\b[^>]*\bsrc="([^"]+)"', html)
    assets += re.findall(r'<link\b[^>]*\bhref="([^"]+)"', html)
    assets += re.findall(r'(?:@import|url\()\s*["\']?(https?://[^"\')]+)', html)
    assert not assets, f"page pulls external assets: {assets}"
    # Fonts too: the stylesheet must name only system families.
    assert "fonts.googleapis" not in html and "cdn" not in html.lower()
