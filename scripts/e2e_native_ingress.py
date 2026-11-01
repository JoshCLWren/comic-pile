"""Same-origin ingress for local/e2e runs that need native v2 plus Python.

Vercel routes ``/api/v2/*`` to the native Rust functions before the Python
catch-all. Local Playwright/e2e runs serve a single origin from one ASGI
process, so this bounded proxy reproduces that method/path split:

* ``/api/v2/*`` -> ``NATIVE_ROLL_URL`` (default ``http://127.0.0.1:8010``)
* everything else -> ``PYTHON_API_URL`` (default ``http://127.0.0.1:9001``)

It is test/dev infrastructure only. It is not an application route, does not
implement any endpoint, and must never be deployed as a compatibility fallback.
"""

from __future__ import annotations

import http.client
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

NATIVE_PREFIX = "/api/v2"
NATIVE = urlsplit(os.environ.get("NATIVE_ROLL_URL", "http://127.0.0.1:8010"))
PYTHON = urlsplit(os.environ.get("PYTHON_API_URL", "http://127.0.0.1:9001"))
LISTEN_PORT = int(os.environ.get("INGRESS_PORT", "9000"))
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
    """Forward one request to the same-origin owner of its path."""

    protocol_version = "HTTP/1.1"

    def _forward(self) -> None:
        upstream = NATIVE if self.path.startswith(NATIVE_PREFIX) else PYTHON
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

    def log_message(self, format: str, *args: object) -> None:
        """Keep per-request noise out of e2e logs."""
        return


# BaseHTTPRequestHandler dispatches on ``do_<METHOD>``; set them without
# declaring mixedCase class attributes.
for _method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
    setattr(Ingress, f"do_{_method}", Ingress._forward)


def main() -> None:
    """Serve until the process is stopped."""
    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Ingress)
    print(
        f"e2e ingress on :{LISTEN_PORT} "
        f"(native {NATIVE.geturl()} for {NATIVE_PREFIX}, "
        f"python {PYTHON.geturl()})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
