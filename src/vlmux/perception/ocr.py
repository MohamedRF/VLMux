"""OCR perception: screenshot plus recognized text and coordinates.

The provider boundary is pluggable; the default uses pytesseract when the
Tesseract binary is installed and degrades to an explicit error otherwise.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any, Protocol

from PIL import Image

from vlmux.core import ScreenObservation
from vlmux.exceptions import ScreenCaptureError


class OCRWord:
    """One recognized word with image-space coordinates."""

    def __init__(self, text: str, x: int, y: int, width: int, height: int) -> None:
        self.text = text
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable description."""
        return {
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


class OCRProvider(Protocol):
    """Recognize text in a screenshot."""

    def recognize(self, screen: ScreenObservation) -> list[OCRWord]:
        """Return recognized words in encoded-image pixels."""
        ...


class PytesseractOCRProvider:
    """OCR backend using pytesseract and the Tesseract binary."""

    def __init__(self, *, language: str = "eng") -> None:
        self._language = language

    def recognize(self, screen: ScreenObservation) -> list[OCRWord]:
        """Run Tesseract on the decoded screenshot."""
        try:
            import pytesseract  # type: ignore[import-not-found]
        except ImportError as error:
            raise ScreenCaptureError(
                "OCR requires the pytesseract package (pip install pytesseract)"
            ) from error
        image = Image.open(BytesIO(base64.b64decode(screen.image)))
        try:
            data = pytesseract.image_to_data(
                image, lang=self._language, output_type=pytesseract.Output.DICT
            )
        except Exception as error:
            raise ScreenCaptureError("OCR failed; is the Tesseract binary installed?") from error
        words: list[OCRWord] = []
        for index in range(len(data["text"])):
            text = str(data["text"][index]).strip()
            if not text:
                continue
            conf = float(data["conf"][index])
            if conf < 0:
                continue
            words.append(
                OCRWord(
                    text=text,
                    x=int(data["left"][index]),
                    y=int(data["top"][index]),
                    width=int(data["width"][index]),
                    height=int(data["height"][index]),
                )
            )
        return words


class StubOCRProvider:
    """Deterministic OCR backend for tests and offline development."""

    def __init__(self, words: list[OCRWord] | None = None) -> None:
        self._words = words or []

    def recognize(self, screen: ScreenObservation) -> list[OCRWord]:
        """Return the configured words regardless of the image."""
        return list(self._words)


def ocr_payload(words: list[OCRWord]) -> tuple[list[dict[str, Any]], str]:
    """Return (observation OCR list, joined text) for recognized words."""
    return [word.to_dict() for word in words], " ".join(word.text for word in words)
