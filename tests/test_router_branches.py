"""Supplementary branch coverage for the router."""

from __future__ import annotations

from dataclasses import replace

from sovereign_code.models import ModelView, build_views
from sovereign_code.router import Task, choose, context_for, system_prompt, task_from_name


def _view(tag: str, **kw) -> ModelView:
    views = build_views({"models": [{"name": tag, "size": 4 * 1024**3, "details": {}}]}, None)
    view = views[tag]
    for key, value in kw.items():
        view = replace(view, **{key: value})
    return view


def test_context_for_loaded_model_keeps_resident_context() -> None:
    view = _view("qwen3-coder:30b", loaded=True, context=8192)
    assert context_for(view, 4.0, max_context=32768) == 8192


def test_context_for_tight_budget_falls_back_to_minimum() -> None:
    # weights < budget but even the smallest context cannot fit -> choices[-1]
    view = _view("qwen3-coder:30b")
    small = replace(view, spec=replace(view.spec, max_context=2048))
    context = context_for(small, 2.0, max_context=2048)
    assert context in (2048, 4096)


def test_system_prompt_every_task() -> None:
    for task in Task:
        prompt = system_prompt(task)
        assert "Sovereign Code" in prompt
        assert len(prompt) > 50


def test_system_prompt_chat_fallback() -> None:
    assert "Markdown" in system_prompt(Task.CHAT)


def test_task_from_name() -> None:
    assert task_from_name("code") is Task.CODE
    assert task_from_name(None) is Task.CHAT
    assert task_from_name("bogus") is Task.CHAT  # unknown -> chat


def test_task_from_name_synonyms() -> None:
    assert task_from_name("coder") is Task.CODE
    assert task_from_name("CODER") is Task.CODE
    assert task_from_name("legal") is Task.REASON
    assert task_from_name("finance") is Task.REASON
    assert task_from_name("forensics") is Task.REASON
    assert task_from_name("image") is Task.VISION
    assert task_from_name("agentic") is Task.AGENT
    assert task_from_name("speed") is Task.FAST


def test_choose_selection_tag_none_when_no_model() -> None:
    selection = choose(Task.CODE, {}, free_gb=8.0)
    assert selection.model is None
    assert selection.tag is None
    assert selection.needs_pull is not None


def test_context_for_very_tight_budget_returns_minimum() -> None:
    view = _view("qwen3-coder:30b")
    # weights far exceed budget -> choices[-1]
    assert context_for(view, 1.0, max_context=32768) == 2048


def test_mlx_loop_skips_uninstalled_tags(monkeypatch) -> None:
    import sovereign_code.router as router

    monkeypatch.setattr(router, "mlx_online", lambda: True)
    views = build_views(
        {"models": [{"name": "qwen3-coder:30b", "size": 4 * 1024**3, "details": {}}]}, None
    )
    selection = choose(Task.CODE, views, free_gb=8.0)
    assert selection.model is not None
    assert selection.model.tag == "qwen3-coder:30b"


def test_context_for_fallback_when_weights_just_under_budget() -> None:
    # weights < budget but even the smallest context does not fit -> line 81
    view = _view("tiny")
    view = replace(
        view,
        size_gb=1.68,
        spec=replace(view.spec, size_gb=1.68, max_context=32768),
    )
    assert context_for(view, 2.0, max_context=32768) == 2048


def test_mode_label_for_every_task() -> None:
    from sovereign_code.router import mode_label

    for task in Task:
        assert mode_label(task) == task.value
