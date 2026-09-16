"""Deterministic policy evaluation independent of model claims."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from vlmux.protocol import Action, CloseWindowAction, PasteAction


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


class PolicyEngine:
    """Classify actions locally and apply configured risk rules."""

    def __init__(
        self,
        *,
        confirm: set[RiskLevel] | None = None,
        deny: set[RiskLevel] | None = None,
    ) -> None:
        self._confirm = {RiskLevel.SENSITIVE, RiskLevel.DESTRUCTIVE} if confirm is None else confirm
        self._deny = set() if deny is None else deny

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
        return RiskLevel.SAFE
