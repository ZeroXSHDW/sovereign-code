"""Request guards shared by the loopback HTTP servers.

Every server in this project binds to 127.0.0.1, but binding is not enough:
a web page can point its own domain at 127.0.0.1 (DNS rebinding) and then talk
to the server as if it were same-origin. The fix is to refuse any request whose
``Host`` header does not name the loopback address. Request bodies are capped
for the same reason as any local service: one oversized POST must not be able
to exhaust the process's memory.
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_BODY_BYTES = 32 * 1024 * 1024
LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})


class BodyTooLarge(ValueError):
    """The request declared a body bigger than :data:`MAX_BODY_BYTES`."""


def loopback_host_ok(host_header: str | None) -> bool:
    """True when the Host header names this machine's loopback address."""
    host = (host_header or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        name = host[1:].split("]", 1)[0]
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in LOOPBACK_NAMES


def content_length(header: str | None) -> int:
    """The declared body length, or raise ValueError for a malformed header."""
    if header is None or not header.strip():
        return 0
    length = int(header)
    if length < 0:
        raise ValueError("negative Content-Length")
    if length > MAX_BODY_BYTES:
        raise BodyTooLarge(f"body is {length} bytes; the limit is {MAX_BODY_BYTES}")
    return length


class GuardedHandler(BaseHTTPRequestHandler):
    """Base handler that rejects requests not addressed to the loopback name."""

    # A client that sends headers and then stalls used to pin its worker
    # thread (and its buffer) forever. Bound every read.
    timeout = 30

    def parse_request(self) -> bool:
        if not super().parse_request():
            return False
        if not loopback_host_ok(self.headers.get("Host")):
            self.send_error(403, "Host header is not a loopback name")
            return False
        return True


class GuardedServer(ThreadingHTTPServer):
    """Threaded loopback server that ignores clients hanging up.

    A browser or coding client closes the connection as soon as it has what it
    needs, which is a normal event, not a server bug. The stock
    ``socketserver`` prints a traceback for every such disconnect; that noise
    filled the gateway logs and made real failures hard to spot. Only genuine
    errors are reported.
    """

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)
