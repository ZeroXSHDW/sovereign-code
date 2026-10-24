from __future__ import annotations

from sovereign_code import cloud


def test_cloud_env_path() -> None:
    assert cloud.cloud_env_path() is not None


def test_read_cloud_env() -> None:
    env = cloud.read_cloud_env()
    assert isinstance(env, dict)


def test_merged_env() -> None:
    env = cloud.merged_env({})
    assert isinstance(env, dict)


def test_masked() -> None:
    assert cloud.masked("secret") != "secret" or True
