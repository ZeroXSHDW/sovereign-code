"""Regression tests for the upgrade pass.

Each test pins a defect found during the review so it cannot come back.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sovereign_code import direct, pdf, repomap, sessions
from sovereign_code.backup import create_backup
from sovereign_code.browser import actions
from sovereign_code.cache import DiskCache
from sovereign_code.mcp import handle
from sovereign_code.promptdb import PromptDB
from sovereign_code.repoedit import apply_patch, edit_text
from sovereign_code.skills import search_skills
from sovereign_code.tier_gateway import TIER_MODELS, catalog_models


def _pdf(path: Path, *, pages: int = 1) -> Path:
    font_id = 3 + pages * 2
    children = " ".join(f"{3 + index * 2} 0 R" for index in range(pages))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{children}] /Count {pages} >>",
    ]
    for index in range(pages):
        page_id = 3 + index * 2
        content_id = page_id + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )
        stream = f"BT /F1 12 Tf 100 700 Td (Page {index + 1}) Tj ET"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    body = "%PDF-1.4\n"
    for number, obj in enumerate(objects, start=1):
        body += f"{number} 0 obj\n{obj}\nendobj\n"
    body += "trailer\n<< /Size 1 /Root 1 0 R >>\n%%EOF\n"
    path.write_text(body, encoding="utf-8")
    return path


def test_disk_cache_is_usable_from_a_worker_thread(tmp_path: Path) -> None:
    """The tier gateway answers on ThreadingHTTPServer worker threads."""
    cache = DiskCache(tmp_path / "cache.db")
    try:

        def work() -> tuple[str, object]:
            cache.put("k", {"answer": 42}, model="m", tier="fast")
            return "ok", cache.get("k")

        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(work).result(timeout=10)
        assert result == ("ok", {"answer": 42})
    finally:
        cache.close()


def test_tier_aliases_report_their_real_model() -> None:
    entries = {entry["id"]: entry for entry in catalog_models(set())}
    model, context, _ = TIER_MODELS["fast"]
    assert entries["sovereign-fast"]["tier"] == "fast"
    assert entries["sovereign-fast"]["model"] == model
    assert entries["sovereign-fast"]["context"] == context
    assert entries["sovereign"]["tier"] == "auto"


def test_sessions_created_in_the_same_second_do_not_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    first = sessions.SessionWriter.create("qwen")
    second = sessions.SessionWriter.create("qwen")
    assert first.path != second.path
    assert len({first.path, second.path}) == 2


def test_read_session_skips_a_corrupt_line_without_losing_the_rest(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(
        json.dumps({"type": "session", "model": "m"})
        + "\n{not json}\n"
        + json.dumps({"type": "message", "content": "kept"})
        + "\n",
        encoding="utf-8",
    )
    records = sessions.read_session(path)
    assert [record.get("content") for record in records] == [None, "kept"]


def test_backups_are_unique_and_leave_no_partial_files(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    (source / "note.txt").write_text("hello", encoding="utf-8")
    first = create_backup([source], tmp_path / "backups")
    second = create_backup([source], tmp_path / "backups")
    assert first != second
    assert first.is_file() and second.is_file()
    assert list((tmp_path / "backups").glob("*.partial")) == []


def test_undo_restores_a_binary_file_instead_of_deleting_it(tmp_path: Path) -> None:
    target = tmp_path / "image.bin"
    target.write_bytes(b"\x89PNG\r\n\x1a\n\x00payload")
    direct.apply_writes(tmp_path, [direct.FileWrite("image.bin", "replaced")])
    direct.undo_writes(tmp_path)
    assert target.read_bytes() == b"\x89PNG\r\n\x1a\n\x00payload"


def test_undo_preserves_crlf_line_endings(tmp_path: Path) -> None:
    target = tmp_path / "crlf.txt"
    target.write_bytes(b"a\r\nb\r\n")
    direct.apply_writes(tmp_path, [direct.FileWrite("crlf.txt", "replaced")])
    direct.undo_writes(tmp_path)
    assert target.read_bytes() == b"a\r\nb\r\n"


def test_editing_a_non_utf8_file_refuses_instead_of_corrupting_it(tmp_path: Path) -> None:
    target = tmp_path / "latin1.txt"
    original = b"caf\xe9\nfoo\n"
    target.write_bytes(original)
    with pytest.raises(ValueError, match="UTF-8"):
        edit_text(target, "foo", "bar")
    assert target.read_bytes() == original


def test_patch_preserves_crlf_line_endings(tmp_path: Path) -> None:
    target = tmp_path / "crlf.txt"
    target.write_bytes(b"line1\r\nline2\r\nline3\r\n")
    patch = "--- a/crlf.txt\n+++ b/crlf.txt\n@@ -1,3 +1,3 @@\n line1\n-line2\n+LINE2\n line3\n"
    apply_patch(tmp_path, patch)
    assert target.read_bytes() == b"line1\r\nLINE2\r\nline3\r\n"


def test_repomap_does_not_follow_symlinks_out_of_the_workspace(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("API_KEY = 'hunter2'\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")
    (root / "link").symlink_to(outside, target_is_directory=True)
    names = {item.rel for item in repomap.iter_files(root)}
    assert names == {"main.py"}


def test_read_slice_reports_empty_text_files_as_text(tmp_path: Path) -> None:
    target = tmp_path / "empty.py"
    target.write_text("", encoding="utf-8")
    result = repomap.read_slice(target)
    assert result["binary"] is False
    assert result["lines"] == 0


def test_pdf_download_filename_cannot_escape_its_directory() -> None:
    assert pdf._download_filename("../../evil", "http://x/a.pdf") == "evil.pdf"
    assert pdf._download_filename("/tmp/evil.pdf", "http://x/a.pdf") == "evil.pdf"
    assert pdf._download_filename("..", "http://x/a.pdf") == "a.pdf"


def test_pdf_render_pages_sort_numerically() -> None:
    names = [Path("page-10.png"), Path("page-2.png"), Path("page-1.png")]
    ordered = [path.name for path in sorted(names, key=pdf._render_sort_key)]
    assert ordered == ["page-1.png", "page-2.png", "page-10.png"]


def test_read_pdf_keeps_text_when_rendering_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _pdf(tmp_path / "doc.pdf", pages=1)

    def boom(*_args, **_kwargs):
        raise RuntimeError("pdftoppm missing")

    monkeypatch.setattr(pdf, "render_pages", boom)
    doc = pdf.read_pdf(source, render_images=True)
    assert "Page 1" in doc.text
    assert "pdftoppm missing" in doc.metadata["ocr_error"]


def test_read_pdf_gives_each_page_its_own_image(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "doc.pdf", pages=2)
    doc = pdf.read_pdf(source, render_images=True, ocr="false", dpi=72)
    assert doc.page_count == 2
    assert all(len(page.image_paths) == 1 for page in doc.pages)
    assert doc.pages[0].image_paths != doc.pages[1].image_paths


def test_legacy_numeric_hosts_are_treated_as_loopback() -> None:
    policy = actions.BrowserPolicy()
    for url in ("http://2130706433/", "http://127.1/", "http://0x7f.0.0.1/"):
        with pytest.raises(actions.PolicyError):
            actions.check_url(url, policy)
    assert actions.is_private_url("http://2130706433/") is True


def test_about_blank_is_allowed_by_policy() -> None:
    assert actions.check_url("about:blank", actions.BrowserPolicy()) == "about:blank"


def test_camel_case_destructive_labels_need_confirmation() -> None:
    assert actions.is_destructive("DeleteAccount") is True
    assert actions.is_destructive("SendMessage") is True
    assert actions.is_destructive("BuyNow") is True
    assert actions.is_destructive("Read more") is False


def test_punctuation_only_skill_query_does_not_raise() -> None:
    assert search_skills("++") == [] or isinstance(search_skills("++"), list)


def test_prompt_tags_match_first_and_last_positions(tmp_path: Path) -> None:
    db = PromptDB(tmp_path / "prompts.db")
    try:
        db.add("p", "body", tags="first,middle,last")
        assert [p.name for p in db.list_all(tag="first")] == ["p"]
        assert [p.name for p in db.list_all(tag="last")] == ["p"]
        assert [p.name for p in db.list_all(tag="middle")] == ["p"]
    finally:
        db.close()


def test_deleting_one_prompt_version_keeps_the_others_searchable(tmp_path: Path) -> None:
    db = PromptDB(tmp_path / "prompts.db")
    try:
        db.add("greet", "hello world")
        db.replace("greet", "second unique body")
        assert db.delete("greet", version=1) is True
        current = db.get("greet")
        assert current is not None and current.version == 2
        assert [p.name for p in db.list_all(search="unique")] == ["greet"]
    finally:
        db.close()


def test_failed_reindex_keeps_the_previous_index(tmp_path: Path, monkeypatch) -> None:
    from sovereign_code import search

    root = tmp_path / "root"
    root.mkdir()
    (root / "a.py").write_text("print(1)\n", encoding="utf-8")
    path = search.index_path_for(root)
    old = search.IndexStore(path)
    old.clear()
    old.add("old.py", 1, "previous", [1.0, 0.0])
    old.commit()
    old.close()

    def boom(*_args, **_kwargs):
        raise search.EmbedError("ollama is down")

    monkeypatch.setattr(search, "embed", boom)
    with pytest.raises(search.EmbedError):
        search.build_index(root, "http://127.0.0.1:1")
    check = search.IndexStore(path)
    try:
        assert check.count() == 1
    finally:
        check.close()
    assert not list(path.parent.glob(path.name + ".*.tmp"))


def test_mcp_tool_failures_are_tool_errors_not_protocol_errors() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "does-not-exist", "arguments": {}},
        }
    )
    assert response is not None
    assert "result" in response
    assert response["result"]["isError"] is True


def test_mcp_negotiates_the_requested_protocol_version() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    )
    assert response is not None
    assert response["result"]["protocolVersion"] == "2025-03-26"


def test_cli_accepts_the_http_mcp_service_flags() -> None:
    from sovereign_code.cli import build_parser

    args = build_parser().parse_args(
        ["mcp", "--http", "--host", "127.0.0.1", "--port", "8765", "--token", "secret"]
    )
    assert (args.http, args.host, args.port, args.token) == (True, "127.0.0.1", 8765, "secret")


def test_mcp_http_bearer_token_check() -> None:
    from sovereign_code.mcp import _bearer_ok

    assert _bearer_ok(None, "") is True
    assert _bearer_ok("Bearer secret", "secret") is True
    assert _bearer_ok("bearer secret", "secret") is False
    assert _bearer_ok("Bearer wrong", "secret") is False
    assert _bearer_ok(None, "secret") is False


def test_browser_profile_lock_is_exclusive_across_processes(tmp_path: Path) -> None:
    from sovereign_code.browser.executor import ProfileLock

    first = ProfileLock(tmp_path / "profile")
    first.acquire()
    try:
        code = (
            "import sys\n"
            "from sovereign_code.browser.executor import ProfileLock\n"
            "from sovereign_code.errors import BrowserError\n"
            "try:\n"
            "    ProfileLock(sys.argv[1]).acquire()\n"
            "except BrowserError:\n"
            "    sys.exit(0)\n"
            "sys.exit(3)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path / "profile")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
    finally:
        first.release()


def test_a_failed_browser_start_releases_the_profile_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pw = pytest.importorskip("playwright.sync_api")
    from sovereign_code.browser.actions import BrowserPolicy
    from sovereign_code.browser.executor import BrowserSession, ProfileLock

    def boom() -> None:
        raise RuntimeError("no browser")

    monkeypatch.setattr(pw, "sync_playwright", boom)
    session = BrowserSession(
        profile_dir=tmp_path / "profile", policy=BrowserPolicy(), headless=True
    )
    with pytest.raises(RuntimeError, match="no browser"):
        session.start()

    # The lock must be free again, or every later browse call would fail.
    lock = ProfileLock(tmp_path / "profile")
    lock.acquire()
    lock.release()


def test_webchat_rejects_other_loopback_origins() -> None:
    from sovereign_code.webchat import Handler

    class FakeHandler:
        def __init__(self, origin: str) -> None:
            self.headers = {"Origin": origin}
            self.port = 4020

    assert Handler._origin_is_local(FakeHandler("http://127.0.0.1:8888")) is False  # type: ignore[arg-type]
    assert Handler._origin_is_local(FakeHandler("http://127.0.0.1:4020")) is True  # type: ignore[arg-type]


def test_client_configs_derive_paths_from_the_real_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sovereign_code import client_setup

    monkeypatch.setenv("HOME", str(tmp_path))
    servers = client_setup.complementary_mcp_servers()
    filesystem_args = [str(arg) for arg in servers["filesystem"]["args"]]
    assert str(tmp_path / "Documents") in filesystem_args
    assert str(tmp_path / "Downloads") in filesystem_args
    assert not any("/Users/user/" in arg for arg in filesystem_args)


def test_codex_mcp_config_is_idempotent_and_preserves_other_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tomllib

    from sovereign_code import client_setup

    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.toml"
    target.write_text('[tui]\ntheme = "dark"\n', encoding="utf-8")
    client_setup.install_codex_mcp(target)
    client_setup.install_codex_mcp(target)
    parsed = tomllib.loads(target.read_text(encoding="utf-8"))
    assert parsed["tui"]["theme"] == "dark"
    assert set(parsed["mcp_servers"]) == {
        "sovereign",
        *client_setup.complementary_mcp_servers(),
    }


def test_prompt_import_is_idempotent(tmp_path: Path) -> None:
    db = PromptDB(tmp_path / "prompts.db")
    rows = [{"name": "p", "content": "body", "version": 1, "tags": "a"}]
    try:
        assert db.import_json(rows) == 1
        assert db.import_json(rows) == 0
        assert db.count() == 1
    finally:
        db.close()


def test_tools_tolerate_unexpected_client_config_shapes() -> None:
    from sovereign_code import tools

    assert tools.qwen_models('{"modelProviders": [1, 2]}') == []
    assert tools.qwen_models('{"modelProviders": {"openai": "nope"}}') == []
    assert tools.qwen_models('{"modelProviders": {"openai": [{"id": "local-a"}, "junk"]}}') == [
        "local-a"
    ]
    assert tools.opencode_models('{"provider": {"custom": {"models": {"cloud-x": {}}}}}') == [
        "cloud-x"
    ]
    assert tools.opencode_models('{"providers": {"custom": {"models": {"cloud-y": {}}}}}') == [
        "cloud-y"
    ]


def test_private_write_is_atomic_and_keeps_mode(tmp_path: Path) -> None:
    from sovereign_code.safefile import write_private

    target = tmp_path / "settings.json"
    write_private(target, "one")
    write_private(target, "two")
    assert target.read_text(encoding="utf-8") == "two"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_opencode_config_has_no_machine_specific_servers() -> None:
    from sovereign_code import client_setup

    servers = client_setup.opencode_config()["mcp"]["servers"]
    assert "browseros-neo" not in servers
    assert {"sovereign", "filesystem", "memory"} <= set(servers)


def test_pdf_figures_payload_is_bounded() -> None:
    from types import SimpleNamespace

    from sovereign_code.mcp import _pdf_figures_payload

    figures = [
        SimpleNamespace(page=number, path=f"page-{number}.png", image_base64="x" * 1_000_000)
        for number in range(1, 21)
    ]
    payload = _pdf_figures_payload(figures, max_pages=4)
    assert payload["total_pages"] == 20
    assert payload["returned_pages"] == 4
    assert payload["truncated"] is True
    # The budget is spent after the first image, so later pages keep only paths.
    assert payload["figures"][0]["image_base64"]
    assert payload["figures"][-1]["image_base64"] == ""
    assert payload["figures"][-1]["path"] == "page-4.png"


def test_a_failed_backup_leaves_no_partial_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sovereign_code import backup as backup_mod

    source = tmp_path / "data"
    source.mkdir()
    (source / "note.txt").write_text("hello", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(backup_mod.tarfile, "open", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        create_backup([source], tmp_path / "backups")
    assert list((tmp_path / "backups").glob("*.partial")) == []


def test_shared_client_does_not_share_across_transports() -> None:
    import httpx

    from sovereign_code import http

    first = http.shared_client(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    second = http.shared_client(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    try:
        assert first is not second
    finally:
        first.close()
        second.close()


def test_private_bytes_write_is_atomic_and_keeps_mode(tmp_path: Path) -> None:
    from sovereign_code.safefile import write_private_bytes

    target = tmp_path / "page.png"
    write_private_bytes(target, b"\x89PNG\r\n\x1a\none")
    write_private_bytes(target, b"\x89PNG\r\n\x1a\ntwo")
    assert target.read_bytes() == b"\x89PNG\r\n\x1a\ntwo"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_failed_session_export_keeps_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from sovereign_code import sessions

    dest = tmp_path / "export.jsonl"
    dest.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(
        sessions,
        "scan_sessions",
        lambda directory=None: [SimpleNamespace(path=tmp_path / "s.jsonl")],
    )

    def boom(_path: Path) -> list[dict]:
        raise OSError("disk full")

    monkeypatch.setattr(sessions, "read_session", boom)
    with pytest.raises(OSError, match="disk full"):
        sessions.export_sessions(dest)
    assert dest.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_concurrent_index_builds_do_not_share_a_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from sovereign_code import search

    root = tmp_path / "root"
    root.mkdir()
    (root / "a.py").write_text("print(1)\n", encoding="utf-8")
    barrier = threading.Barrier(2)

    def slow_embed(_url, _model, texts, timeout=300.0):
        barrier.wait(timeout=10)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(search, "embed", slow_embed)
    errors: list[BaseException] = []

    def build() -> None:
        try:
            search.build_index(root, "http://127.0.0.1:1")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=build) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    store = search.IndexStore(search.index_path_for(root))
    try:
        assert store.count() > 0
    finally:
        store.close()
    assert list(search.index_path_for(root).parent.glob("*.tmp")) == []


def test_tui_stylesheet_is_present_next_to_the_module() -> None:
    from sovereign_code.tui.monitor import MonitorApp

    assert MonitorApp.CSS_PATH.is_file()


def test_package_version_matches_pyproject() -> None:
    import tomllib

    from sovereign_code import __version__

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__
