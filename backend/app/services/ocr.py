"""Offline label reading with Tesseract OCR, used when no AI provider is set
up or the AI service is unavailable. Less accurate than a vision model on
curved or glossy packs, so results always go to the user for review."""
from __future__ import annotations

import io
import logging
import shutil
from typing import Any

from PIL import Image, ImageFilter, ImageOps

from .label_text import parse_label_text

log = logging.getLogger("labelcheck.ocr")

try:  # optional dependency
    import pytesseract
except ImportError:  # pragma: no cover - depends on the environment
    pytesseract = None  # type: ignore[assignment]

OCR_TIMEOUT_S = 40
TARGET_SIDE = 2400


class OCRReader:
    provider = "ocr"

    def __init__(self, enabled: bool = True, languages: str = "eng"):
        self.languages = languages
        self._enabled = bool(enabled and pytesseract is not None and shutil.which("tesseract"))
        if enabled and not self._enabled:
            log.warning("OCR fallback disabled: Tesseract is not installed.")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _prepare(jpeg: bytes) -> Image.Image:
        with Image.open(io.BytesIO(jpeg)) as img:
            img = img.convert("L")
            longest = max(img.size)
            if longest < TARGET_SIDE:  # small text reads much better upscaled
                scale = TARGET_SIDE / longest
                img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
            img = ImageOps.autocontrast(img, cutoff=1)
            return img.filter(ImageFilter.SHARPEN)

    def image_text(self, jpeg: bytes) -> str:
        img = self._prepare(jpeg)
        try:
            return pytesseract.image_to_string(img, lang=self.languages, config="--oem 1 --psm 6",
                                               timeout=OCR_TIMEOUT_S)
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            log.warning("OCR timed out: %s", exc)
            return ""

    def extract_label(self, images: list[tuple[bytes, str]]) -> dict[str, Any]:
        texts = [self.image_text(data) for data, _ in images]
        # The client shows a "read with basic text recognition" notice based on read_by="ocr".
        raw = parse_label_text("\n\n".join(t for t in texts if t.strip()))
        raw["confidence"] = "low" if raw["confidence"] == "low" else "medium"
        return raw
