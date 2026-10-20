"""Tests for the model catalog and runtime merge."""

from sovereign_code.models import (
    CATALOG,
    build_views,
    parse_params_b,
    parse_size_gb,
    sort_views,
)

GIB = 1024**3


def tags(*names):
    return {
        "models": [
            {
                "name": name,
                "size": int(CATALOG[name].size_gb * GIB) if name in CATALOG else 4 * GIB,
                "details": {
                    "parameter_size": "7.6B",
                    "family": "qwen2",
                },
            }
            for name in names
        ]
    }


def ps(*names, context=16384):
    return {
        "models": [
            {
                "name": name,
                "size": int((CATALOG[name].size_gb if name in CATALOG else 4) * GIB),
                "size_vram": int((CATALOG[name].size_gb if name in CATALOG else 4) * GIB),
                "context_length": context,
            }
            for name in names
        ]
    }


def test_parse_helpers():
    assert parse_size_gb(GIB) == 1.0
    assert parse_params_b("7.6B") == 7.6
    assert parse_params_b("760M") == 0.76
    assert parse_params_b("") is None


def test_merge_marks_installed_and_loaded():
    views = build_views(tags("qwen3.5:4b"), ps("qwen3.5:4b"))
    view = views["qwen3.5:4b"]
    assert view.installed is True
    assert view.loaded is True
    assert view.context == 16384
    assert view.spec.role == "chat"


def test_recommended_model_is_shown_when_missing():
    views = build_views(tags("phi:latest"), None)
    assert views["qwen2.5-coder:14b"].installed is False
    assert views["qwen2.5-coder:14b"].spec.recommended is True


def test_sort_puts_loaded_first():
    views = build_views(tags("phi:latest", "qwen3.5:4b"), ps("qwen3.5:4b"))
    ordered = sort_views(views.values())
    assert ordered[0].tag == "qwen3.5:4b"
