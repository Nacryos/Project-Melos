"""Loopback-only design preview, with the existing local corpus API proxied.

Run: python tools/serve_timeline_preview.py [8792]
No production routes or backend processes are changed.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import mimetypes
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8791"


class PreviewHandler(BaseHTTPRequestHandler):
    def reply(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def serve(self):
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/"):
            size = int(self.headers.get("Content-Length", "0"))
            if size > 1_000_000:
                return self.reply(413, b"Request too large", "text/plain")
            body = self.rfile.read(size) if size else None
            request = Request(API + self.path, data=body, method=self.command,
                              headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
            try:
                with urlopen(request, timeout=180) as response:
                    return self.reply(response.status, response.read(), response.headers.get("Content-Type", "application/json"))
            except HTTPError as error:
                return self.reply(error.code, error.read(), error.headers.get("Content-Type", "application/json"))
            except URLError:
                return self.reply(502, b'{"detail":"Local corpus service is unavailable."}', "application/json")
        if self.command not in ("GET", "HEAD"):
            return self.reply(405, b"Method not allowed", "text/plain")
        if path == "/":
            path = "/reader.html"
        if path in ("/legacy", "/design-studio", "/design-studio.html"):
            path = "/index.html"
        if path in ("/lexicon", "/authors", "/themes"):
            path += ".html"
        pages = ("/reader.html", "/index.html", "/lexicon.html", "/authors.html", "/themes.html")
        if not (path in pages or path.startswith(("/local-preview/", "/js/", "/css/", "/assets/paintings/", "/assets/branding/", "/assets/authors/", "/assets/nature-presets/"))):
            return self.reply(404, b"Not found", "text/plain")
        file = (ROOT / path.lstrip("/")).resolve()
        allowed = [ROOT / name for name in ("local-preview", "js", "css", "assets/paintings", "assets/branding", "assets/authors", "assets/nature-presets")]
        safe = file in tuple(ROOT / page.lstrip("/") for page in pages) or any(file.is_relative_to(folder) for folder in allowed)
        # Raw download receipts and extraction metadata are not served by this preview.
        if not safe or "raw" in file.relative_to(ROOT).parts or not file.is_file():
            return self.reply(404, b"Not found", "text/plain")
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if file.suffix == ".js":
            content_type = "text/javascript"
        return self.reply(200, file.read_bytes(), content_type)

    do_GET = serve
    do_HEAD = serve
    do_POST = serve


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8792
    print(f"Melos timeline preview: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), PreviewHandler).serve_forever()
