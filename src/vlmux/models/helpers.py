"""Small protocol-neutral helpers shared by model adapters."""

import base64
import secrets
from io import BytesIO
from typing import Any

from PIL import Image


def build_vision_probe() -> tuple[str, str]:
    """Return an unpredictable, easy-to-recognize image challenge."""
    colors = {
        "red": (255, 0, 0),
        "green": (0, 160, 0),
        "blue": (0, 80, 255),
        "yellow": (255, 220, 0),
        "purple": (145, 40, 180),
        "orange": (255, 125, 0),
    }
    name = secrets.choice(tuple(colors))
    image = Image.new("RGB", (64, 64), colors[name])
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    payload = base64.b64encode(encoded.getvalue()).decode("ascii")
    return f"data:image/png;base64,{payload}", name


def usage_integer(usage: dict[str, Any], key: str) -> int | None:
    """Read one non-negative integer from a provider usage envelope."""
    value = usage.get(key)
    return value if isinstance(value, int) and value >= 0 else None


def model_ids(payload: object) -> set[str]:
    """Read OpenAI-style model IDs when a provider exposes them."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return set()
    return {
        item["id"]
        for item in payload["data"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
