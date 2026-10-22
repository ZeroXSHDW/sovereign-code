"""Tests for the machine-readable status output."""

from __future__ import annotations

import json

from sovereign_code import cli
from sovereign_code.config import Settings
from sovereign_code.status import Snapshot

LOCAL_CODEX = """\
model = "auto"
model_provider = "sovereign-tier"
openai_base_url = "http://127.0.0.1:4010/v1"

[model_providers.sovereign-tier]
base_url = "http://127.0.0.1:4010/v1"

[model_providers.sovereign-tier.auth]
command = "/bin/echo"
args = ["local"]
"""


def test_status_json_reports_the_app_modes(capsys, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(LOCAL_CODEX, encoding="utf-8")
    assert cli._status_json(Snapshot(settings=Settings())) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apps"]["chatgpt"]["local"] is True
    assert payload["apps"]["chatgpt"]["signin_required"] is False
    assert payload["apps"]["claude"]["local"] is False
    assert payload["memory"]["known"] is True
    assert "installed" in payload


def test_status_json_reports_a_cloud_app(capsys, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "gpt-5-codex"\nmodel_provider = "openai"\n', encoding="utf-8")
    assert cli._status_json(Snapshot(settings=Settings())) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apps"]["chatgpt"]["local"] is False
    assert payload["apps"]["chatgpt"]["signin_required"] is True
