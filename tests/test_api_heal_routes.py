"""Routing for the mock Vercel entrypoint: static shell vs /api/heal."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from api.heal import _is_heal_path, _request_path, _static_file, handler


def test_heal_path_is_only_the_api() -> None:
    assert _is_heal_path(_request_path("/api/heal"))
    assert _is_heal_path(_request_path("/api/heal/"))
    assert _is_heal_path(_request_path("/api/heal.py?x=1"))
    assert not _is_heal_path(_request_path("/"))
    assert not _is_heal_path(_request_path("/styles.css"))


def test_static_files_resolve_under_web() -> None:
    index = _static_file("/")
    assert index is not None and index.name == "index.html"
    css = _static_file("/styles.css")
    assert css is not None and css.name == "styles.css"
    nested = _static_file("/web/app.js")
    assert nested is not None and nested.name == "app.js"
    assert _static_file("/../pyproject.toml") is None
    assert _static_file("/web/../pyproject.toml") is None


def test_http_serves_shell_and_reserves_post_for_heal() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        conn = HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/")
        home = conn.getresponse()
        body = home.read()
        assert home.status == 200
        assert b"Run mock heal" in body
        assert "text/html" in home.getheader("Content-Type", "")

        conn = HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/styles.css")
        css = conn.getresponse()
        css_body = css.read()
        assert css.status == 200
        assert "text/css" in css.getheader("Content-Type", "")
        assert b"{" in css_body

        conn = HTTPConnection(host, port, timeout=10)
        conn.request("POST", "/", body=b"")
        missing = conn.getresponse()
        payload = json.loads(missing.read().decode())
        assert missing.status == 404
        assert payload["error"] == "not found"
    finally:
        server.shutdown()
        server.server_close()
