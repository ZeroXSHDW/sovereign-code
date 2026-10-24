from __future__ import annotations

from sovereign_code import webchat


def test_pid_path() -> None:
    assert webchat.pid_path().name.endswith(".pid") or webchat.pid_path().suffix == ".pid"


def test_page_contains_html() -> None:
    html = webchat.page()
    assert "<html" in html.lower() or "<!doctype" in html.lower()


def test_model_options() -> None:
    opts = webchat.model_options()
    assert isinstance(opts, str)


def test_log_path() -> None:
    assert webchat.log_path() is not None
