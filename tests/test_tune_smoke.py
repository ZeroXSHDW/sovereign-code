from __future__ import annotations

from sovereign_code import tune


def test_desired_env() -> None:
    env = tune.desired_env()
    assert isinstance(env, dict)


def test_ollama_db_path() -> None:
    assert tune.ollama_db_path() is not None


def test_parse_server_env() -> None:
    parsed = tune.parse_server_env("")
    assert isinstance(parsed, dict)
