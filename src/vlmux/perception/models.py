"""Internal values used by screen capture providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaptureOptions(BaseModel):
    """Validated controls for one screenshot capture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    monitor: int | None = Field(default=None, ge=0)
    active_window: bool = False
    max_width: int | None = Field(default=1440, ge=1)
    max_height: int | None = Field(default=1440, ge=1)
    image_format: Literal["png", "jpeg"] = "png"
    quality: int = Field(default=85, ge=1, le=100)

    @model_validator(mode="after")
    def capture_target_must_be_unambiguous(self) -> Self:
        if self.active_window and self.monitor is not None:
            raise ValueError("monitor and active_window cannot be used together")
        return self


@dataclass(frozen=True, slots=True)
class CaptureRegion:
    """Absolute native-pixel rectangle to capture."""

    left: int
    top: int
    width: int
    height: int
    monitor: int | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("capture region dimensions must be positive")


@dataclass(frozen=True, slots=True)
class RawScreenshot:
    """An RGB screenshot before resize and transport encoding."""

    region: CaptureRegion
    rgb: bytes

    def __post_init__(self) -> None:
        expected_length = self.region.width * self.region.height * 3
        if len(self.rgb) != expected_length:
            raise ValueError(
                f"RGB data length {len(self.rgb)} does not match expected {expected_length}"
            )
