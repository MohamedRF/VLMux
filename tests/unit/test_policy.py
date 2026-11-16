"""Tests for runtime-owned action risk classification and decisions."""

import asyncio

from vlmux.policy import PolicyEngine, PolicyOutcome, RiskLevel
from vlmux.protocol import (
    BrowserNavigateAction,
    ClickAction,
    CloseWindowAction,
    HotkeyAction,
    OpenAppAction,
    PasteAction,
)


def test_default_policy_requires_confirmation_for_sensitive_and_destructive_actions() -> None:
    policy = PolicyEngine()

    paste = asyncio.run(policy.evaluate(PasteAction(text="secret")))
    close = asyncio.run(policy.evaluate(CloseWindowAction(title="Editor")))
    click = asyncio.run(policy.evaluate(ClickAction(x=1, y=1)))

    assert paste.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert paste.risk is RiskLevel.SENSITIVE
    assert close.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert click.outcome is PolicyOutcome.ALLOW


def test_explicit_empty_confirmation_set_disables_prompts() -> None:
    decision = asyncio.run(PolicyEngine(confirm=set()).evaluate(PasteAction(text="text")))

    assert decision.outcome is PolicyOutcome.ALLOW


def test_deny_takes_precedence_over_confirmation() -> None:
    policy = PolicyEngine(confirm={RiskLevel.SAFE}, deny={RiskLevel.SAFE})

    decision = asyncio.run(policy.evaluate(ClickAction(x=1, y=1)))

    assert decision.outcome is PolicyOutcome.DENY


def test_dangerous_hotkeys_are_destructive() -> None:
    policy = PolicyEngine()

    for keys in (["alt", "f4"], ["ctrl", "w"], ["ctrl", "shift", "w"], ["win", "r"], ["cmd", "q"]):
        decision = asyncio.run(policy.evaluate(HotkeyAction(keys=keys)))
        assert decision.risk is RiskLevel.DESTRUCTIVE, keys
        assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION


def test_harmless_hotkey_is_safe() -> None:
    decision = asyncio.run(PolicyEngine().evaluate(HotkeyAction(keys=["ctrl", "c"])))

    assert decision.risk is RiskLevel.SAFE
    assert decision.outcome is PolicyOutcome.ALLOW


def test_open_app_requires_confirmation_by_default() -> None:
    decision = asyncio.run(PolicyEngine().evaluate(OpenAppAction(application="calc.exe")))

    assert decision.risk is RiskLevel.EXTERNAL_SIDE_EFFECT
    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION


def test_browser_navigate_requires_confirmation_by_default() -> None:
    decision = asyncio.run(
        PolicyEngine().evaluate(BrowserNavigateAction(url="https://example.com"))
    )

    assert decision.risk is RiskLevel.EXTERNAL_SIDE_EFFECT
    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION


def test_hotkey_order_is_insignificant() -> None:
    decision = asyncio.run(PolicyEngine().evaluate(HotkeyAction(keys=["w", "ctrl", "shift"])))

    assert decision.risk is RiskLevel.DESTRUCTIVE


def test_policy_copies_caller_sets() -> None:
    confirm = {RiskLevel.SAFE}
    policy = PolicyEngine(confirm=confirm)
    confirm.clear()

    decision = asyncio.run(policy.evaluate(ClickAction(x=1, y=1)))

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
