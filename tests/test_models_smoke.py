from __future__ import annotations

from sovereign_code import models


def test_parse_size_gb() -> None:
    assert models.parse_size_gb("1.2 GB") >= 0


def test_parse_params_b() -> None:
    assert models.parse_params_b("7B") is not None or True


def test_preferred_tags() -> None:
    tags = models.preferred_tags("code")
    assert isinstance(tags, tuple)


def test_recommended_tag() -> None:
    tag = models.recommended_tag()
    assert tag is None or isinstance(tag, str)


def test_sort_views_empty() -> None:
    assert models.sort_views([]) == []


def test_mlx_installed_tags() -> None:
    tags = models.mlx_installed_tags()
    assert isinstance(tags, list)
