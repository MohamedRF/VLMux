"""Provider-independent model adapter contracts."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from vlmux.core import AgentContext, ModelDecision, Observation, Task


class AdapterConfig(BaseModel):
    """Validated networking and model identity supplied to an adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: SecretStr | None = None
    base_url: str = Field(min_length=1)
    timeout_seconds: float = Field(default=60.0, gt=0)
    request_retries: int = Field(default=2, ge=0, le=5)
    repair_attempts: int = Field(default=1, ge=0, le=3)
    supports_json_mode: bool = True


class ModelHealth(BaseModel):
    """Safe result of a model-provider connectivity check."""

    model_config = ConfigDict(extra="forbid")

    connected: bool
    provider: str
    model: str
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisionSupport(BaseModel):
    """Result of sending a real image input to a configured model."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    provider: str
    model: str
    detail: str


class ModelAdapter(ABC):
    """Convert a task and observation into one validated VAP decision."""

    @abstractmethod
    async def decide(
        self,
        task: Task,
        observation: Observation,
        context: AgentContext,
    ) -> ModelDecision:
        """Choose exactly one next action."""

    @abstractmethod
    async def healthcheck(self) -> ModelHealth:
        """Check provider connectivity without requesting a computer action."""

    async def check_image_input(self) -> VisionSupport:
        """Verify image input support before a credential is persisted."""
        return VisionSupport(
            accepted=False,
            provider="unknown",
            model="unknown",
            detail="adapter does not implement image-input validation",
        )

    async def aclose(self) -> None:
        """Release adapter resources when owned by the implementation."""
        return None
