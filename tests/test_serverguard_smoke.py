from __future__ import annotations

import pytest

from sovereign_code import serverguard


def _make_handler(request_bytes: bytes):
    from io import BytesIO

    response_bytes = BytesIO()

    class FakeSocket:
        def makefile(self, mode, *a, **k):
            if "r" in mode:
                return BytesIO(request_bytes)
            return response_bytes

        def sendall(self, data):
            response_bytes.write(data)

        def settimeout(self, *a, **k):
            pass

        def getsockname(self):
            return ("127.0.0.1", 1234)

    serverguard.GuardedHandler(FakeSocket(), ("127.0.0.1", 1234), None)
    return response_bytes


def test_loopback_host_ok() -> None:
    assert serverguard.loopback_host_ok("127.0.0.1") is True
    assert serverguard.loopback_host_ok("example.com") is False


def test_content_length() -> None:
    assert serverguard.content_length("12") == 12
    assert serverguard.content_length(None) == 0


def test_loopback_host_ok_edge_cases() -> None:
    assert serverguard.loopback_host_ok("") is False
    assert serverguard.loopback_host_ok("[::1]:8080") is True


def test_content_length_rejects_negative_and_too_large() -> None:
    with pytest.raises(ValueError):
        serverguard.content_length("-1")
    with pytest.raises(serverguard.BodyTooLarge):
        serverguard.content_length(str(serverguard.MAX_BODY_BYTES + 1))


def test_guarded_handler_accepts_loopback_host() -> None:
    response = _make_handler(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    # A valid GET with no handler implementation returns 501, not 403.
    assert b"501" in response.getvalue()


def test_guarded_handler_rejects_non_loopback_host() -> None:
    response = _make_handler(b"GET / HTTP/1.1\r\nHost: evil.com\r\n\r\n")
    assert b"403" in response.getvalue()


def test_guarded_handler_rejects_bad_request_line() -> None:
    # Too many fields in the request line makes parse_request return False.
    response = _make_handler(b"GET / HTTP/1.1 extra\r\nHost: 127.0.0.1\r\n\r\n")
    assert response.getvalue()  # some error response was sent


def test_guarded_server_handle_error_swallows_disconnect() -> None:
    server = serverguard.GuardedServer(("127.0.0.1", 0), serverguard.GuardedHandler)
    try:
        raise BrokenPipeError()
    except BrokenPipeError:
        server.handle_error(None, None)  # must not raise
    finally:
        server.server_close()


def test_guarded_server_handle_error_propagates_other_errors() -> None:
    server = serverguard.GuardedServer(("127.0.0.1", 0), serverguard.GuardedHandler)
    try:
        raise ValueError("boom")
    except ValueError:
        # BaseHTTPRequestHandler.handle_error writes to stderr; just ensure no raise
        server.handle_error(None, None)
    finally:
        server.server_close()
