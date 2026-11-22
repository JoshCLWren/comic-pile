"""Same-origin ingress for local/e2e runs against the native Rust service.

Vercel routes every ``/api/*`` request to native Rust. Local Playwright/e2e
runs serve a single origin from one process, so this bounded ingress proxies
API requests to ``NATIVE_ROLL_URL`` (default ``http://127.0.0.1:8010``) and
serves the built frontend from ``static/react`` for non-API paths.

It is test/dev infrastructure only. It is not an application route, does not
implement any endpoint, and must never be deployed as a compatibility fallback.
"""

from __future__ import annotations

import http.client
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

NATIVE = urlsplit(os.environ.get("NATIVE_ROLL_URL", "http://127.0.0.1:8010"))
LISTEN_PORT = int(os.environ.get("INGRESS_PORT", "9000"))
STATIC_ROOT = Path(__file__).resolve().parent.parent / "static" / "react"
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


class Ingress(BaseHTTPRequestHandler):
    """Serve frontend assets locally and proxy API traffic to Rust."""

    protocol_version = "HTTP/1.1"

    def _is_api_path(self) -> bool:
        path = urlsplit(self.path).path
        return path == "/api" or path.startswith("/api/")

    def _forward(self) -> None:
        upstream = NATIVE
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP
        }
        connection = http.client.HTTPConnection(
            upstream.hostname, upstream.port, timeout=60
        )
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() in HOP_BY_HOP or key.lower() == "content-length":
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        finally:
            connection.close()

    def _static_file(self) -> Path | None:
        request_path = unquote(urlsplit(self.path).path)
        relative = request_path.lstrip("/")
        if not relative:
            relative = "index.html"
        candidate = (STATIC_ROOT / relative).resolve()
        try:
            candidate.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            return None
        if candidate.is_file():
            return candidate
        index = STATIC_ROOT / "index.html"
        return index if index.is_file() else None

    def _serve_static(self) -> None:
        if self.command not in {"GET", "HEAD"}:
            self.send_error(405, "Method Not Allowed")
            return
        file_path = self._static_file()
        if file_path is None:
            self.send_error(404, "Not Found")
            return
        payload = file_path.read_bytes()
        content_type, _ = mimetypes.guess_type(file_path.name)
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _handle(self) -> None:
        if self._is_api_path():
            self._forward()
            return
        self._serve_static()

    def log_message(self, format: str, *args: object) -> None:
        """Keep per-request noise out of e2e logs."""
        return


# BaseHTTPRequestHandler dispatches on ``do_<METHOD>``; set them without
# declaring mixedCase class attributes.
for _method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
    setattr(Ingress, f"do_{_method}", Ingress._handle)


def main() -> None:
    """Serve until the process is stopped."""
    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Ingress)
    print(
        f"e2e ingress on :{LISTEN_PORT} -> api {NATIVE.geturl()}, static {STATIC_ROOT}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
