from __future__ import annotations

import html
import json
import mimetypes
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .maps import build_map_image
from .parser import parse_story
from .photos import get_photos, search_photos
from .project import state_dir
from .render import STYLE, render_photo_page, render_story


def _send(handler: BaseHTTPRequestHandler, content: bytes, content_type: str, status: int = 200) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(content)


def serve_preview(root: Path, path: Path, host: str, port: int, open_browser: bool = True) -> None:
    path = path.resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urllib.parse.urlparse(self.path)
            try:
                if request.path == "/style.css":
                    return _send(self, STYLE.encode(), "text/css; charset=utf-8")
                if request.path == "/__version":
                    return _send(self, str(path.stat().st_mtime_ns).encode(), "text/plain")
                if request.path.startswith("/image/"):
                    photo_id = request.path.rsplit("/", 1)[-1]
                    image = state_dir(root) / "cache" / "previews" / f"{photo_id}.webp"
                    if image.exists():
                        return _send(self, image.read_bytes(), "image/webp")
                    return _send(self, b"not found", "text/plain", 404)
                if request.path.startswith("/map/"):
                    node_index = int(request.path.rsplit("/", 1)[-1])
                    story = parse_story(path)
                    map_nodes = [
                        (i, n) for i, n in enumerate(story.nodes) if n.kind == "map"
                    ]
                    match = next((n for i, n in map_nodes if i == node_index), None)
                    if match is None:
                        return _send(self, b"not found", "text/plain", 404)
                    cached = build_map_image(root, path, match)
                    return _send(self, cached.read_bytes(), "image/png")
                story = parse_story(path)
                photos = get_photos(root, story.photo_ids)
                if request.path.startswith("/photo/"):
                    photo_id = request.path.strip("/").split("/", 1)[1]
                    photo = next((row for row in photos.values() if row["id"] == photo_id), None)
                    if photo is None:
                        return _send(self, b"not found", "text/plain", 404)
                    page = render_photo_page(
                        photo,
                        f"/image/{photo_id}",
                        "/",
                        "/style.css",
                        story.metadata.get("title", "story"),
                    )
                    return _send(self, page.encode(), "text/html; charset=utf-8")
                map_urls = {
                    i: f"/map/{i}"
                    for i, n in enumerate(story.nodes)
                    if n.kind == "map"
                }
                page = render_story(
                    story,
                    photos,
                    lambda p: f"/image/{p['id']}",
                    lambda p: f"/photo/{p['id']}/",
                    live=True,
                    map_urls=map_urls,
                )
                return _send(self, page.encode(), "text/html; charset=utf-8")
            except Exception as error:
                page = f"<h1>Preview error</h1><pre>{html.escape(str(error))}</pre>"
                return _send(self, page.encode(), "text/html; charset=utf-8", 500)

        def log_message(self, format: str, *args: object) -> None:
            pass

    _run(Handler, host, port, open_browser)


def serve_photos(root: Path, host: str, port: int, open_browser: bool = True) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urllib.parse.urlparse(self.path)
            if request.path.startswith("/thumb/") or request.path.startswith("/preview/"):
                size, photo_id = request.path.strip("/").split("/", 1)
                folder = "thumbnails" if size == "thumb" else "previews"
                image = state_dir(root) / "cache" / folder / f"{photo_id}.webp"
                if image.exists():
                    return _send(self, image.read_bytes(), "image/webp")
                return _send(self, b"not found", "text/plain", 404)
            query = urllib.parse.parse_qs(request.query).get("q", [""])[0]
            rows = search_photos(root, query, 200)
            cards = "".join(
                f'<article><a href="/preview/{r["id"]}" target="_blank"><img src="/thumb/{r["id"]}" alt=""></a><button data-id="{r["id"]}">{r["id"]}</button><small>{html.escape(r["captured_at"] or r["filename"])}</small></article>'
                for r in rows
            )
            page = f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Photos</title><style>
body{{font:15px system-ui;margin:0;background:#f5f3ee;color:#27251f}}header{{position:sticky;top:0;padding:18px;background:#f5f3eef2;z-index:2}}form{{max-width:700px;margin:auto}}input{{width:100%;padding:12px;font:inherit}}main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:18px;padding:20px}}article img{{width:100%;aspect-ratio:4/3;object-fit:cover;background:#ddd}}button{{display:block;border:0;background:none;padding:8px 0 2px;font:bold 14px monospace;cursor:pointer}}small{{color:#6d695f}}
</style></head><body><header><form><input name=q value="{html.escape(query)}" placeholder="Search filename, path, keywords…" autofocus></form></header><main>{cards}</main><script>document.querySelectorAll('button').forEach(b=>b.onclick=async()=>{{await navigator.clipboard.writeText(b.dataset.id);let t=b.textContent;b.textContent='copied';setTimeout(()=>b.textContent=t,900)}})</script></body></html>"""
            _send(self, page.encode(), "text/html; charset=utf-8")

        def log_message(self, format: str, *args: object) -> None:
            pass

    _run(Handler, host, port, open_browser)


def _run(handler, host: str, port: int, open_browser: bool) -> None:
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_port}/"
    print(f"Serving {url} (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
