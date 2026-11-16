"""Deterministic policy evaluation independent of model claims."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from vlmux.protocol import (
    Action,
    BrowserNavigateAction,
    CloseWindowAction,
    HotkeyAction,
    OpenAppAction,
    PasteAction,
)


class RiskLevel(StrEnum):
    """Runtime-owned action risk classification."""

    SAFE = "safe"
    SENSITIVE = "sensitive"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    DESTRUCTIVE = "destructive"


class PolicyOutcome(StrEnum):
    """Possible policy decisions before action execution."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


class PolicyDecision(BaseModel):
    """Structured decision returned by the policy engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: PolicyOutcome
    risk: RiskLevel
    reason: str


#: Shortcut combinations that close windows, quit apps, lock the session, or
#: open the run dialog. These are DESTRUCTIVE regardless of the surrounding
#: key order, matching how the same semantics are treated for built-in actions.
_DANGEROUS_HOTKEYS: tuple[frozenset[str], ...] = (
    frozenset({"alt", "f4"}),
    frozenset({"ctrl", "w"}),
    frozenset({"ctrl", "shift", "w"}),
    frozenset({"win", "r"}),
    frozenset({"win", "l"}),
    frozenset({"meta", "r"}),
    frozenset({"meta", "l"}),
    frozenset({"cmd", "r"}),
    frozenset({"cmd", "q"}),
    frozenset({"ctrl", "alt", "del"}),
)


def _normalized_hotkey(keys: list[str]) -> set[str]:
    return {key.strip().casefold() for key in keys if key.strip()}


class PolicyEngine:
    """Classify actions locally and apply configured risk rules."""

    def __init__(
        self,
        *,
        confirm: set[RiskLevel] | None = None,
        deny: set[RiskLevel] | None = None,
    ) -> None:
        self._confirm = (
            {RiskLevel.SENSITIVE, RiskLevel.DESTRUCTIVE, RiskLevel.EXTERNAL_SIDE_EFFECT}
            if confirm is None
            else set(confirm)
        )
        self._deny = set() if deny is None else set(deny)

    async def evaluate(self, action: Action) -> PolicyDecision:
        risk = self.classify(action)
        if risk in self._deny:
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                risk=risk,
                reason=f"policy denies {risk.value} actions",
            )
        if risk in self._confirm:
            return PolicyDecision(
                outcome=PolicyOutcome.REQUIRE_CONFIRMATION,
                risk=risk,
                reason=f"policy requires confirmation for {risk.value} actions",
            )
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            risk=risk,
            reason="action is allowed by policy",
        )

    @staticmethod
    def classify(action: Action) -> RiskLevel:
        if isinstance(action, PasteAction):
            return RiskLevel.SENSITIVE
        if isinstance(action, CloseWindowAction):
            return RiskLevel.DESTRUCTIVE
        if isinstance(action, HotkeyAction):
            keys = _normalized_hotkey(action.keys)
            if any(combo <= keys for combo in _DANGEROUS_HOTKEYS):
                return RiskLevel.DESTRUCTIVE
            return RiskLevel.SAFE
        # Launching applications and navigating the signed-in browser have
        # effects beyond the desktop session; treat them as external.
        if isinstance(action, (OpenAppAction, BrowserNavigateAction)):
            return RiskLevel.EXTERNAL_SIDE_EFFECT
        return RiskLevel.SAFE
