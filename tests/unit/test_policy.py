"""Tests for runtime-owned action risk classification and decisions."""

import asyncio

from vlmux.policy import PolicyEngine, PolicyOutcome, RiskLevel
from vlmux.protocol import ClickAction, CloseWindowAction, PasteAction


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
