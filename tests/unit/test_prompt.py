"""Prompt construction: task, refs, and untrusted-content framing."""

from __future__ import annotations

import json

from vlmux.core import AgentContext, Observation, ScreenObservation, Task
from vlmux.models.prompt import build_system_prompt, build_user_prompt


def _observation(metadata: dict | None = None) -> Observation:
    return Observation(
        screen=ScreenObservation(width=10, height=10, image="aQ=="),
        metadata=metadata or {},
    )


def test_user_prompt_includes_ui_tree_when_present() -> None:
    tree = '- button "Save" [@abc12345:e1] (actions: Click)'
    prompt = build_user_prompt(
        Task(instruction="open"), _observation({"ui_tree": tree}), AgentContext(task_id="t")
    )

    payload = json.loads(prompt)
    assert payload["ui_tree"] == tree
    assert payload["task"] == "open"


def test_user_prompt_omits_ui_tree_when_absent() -> None:
    prompt = build_user_prompt(Task(instruction="open"), _observation(), AgentContext(task_id="t"))

    payload = json.loads(prompt)
    assert "ui_tree" not in payload


def test_system_prompt_documents_ref_contract() -> None:
    prompt = build_system_prompt()

    assert "click_ref" in prompt
    assert "stale_ref" in prompt
    assert "refs belong to the snapshot" in prompt.lower()
