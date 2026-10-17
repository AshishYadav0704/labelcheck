"""Pluggable AI provider for the two jobs AI is allowed to do in this app:

1. Read label photos into structured data (vision).
2. Re-word an already-computed report in plain language (no new facts).

Providers: Anthropic Claude, Google Gemini, or none. With no provider, label
photos are read with on-device OCR (Tesseract) and explanations use templates,
so the app still works end to end without any API key.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Protocol

from ..config import Settings

log = logging.getLogger("labelcheck.ai")


class AIError(Exception):
    """Raised when the AI provider cannot produce a usable answer."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class AIClient(Protocol):
    provider: str

    @property
    def enabled(self) -> bool: ...

    @property
    def model(self) -> str | None: ...

    def extract_label(self, images: list[tuple[bytes, str]]) -> dict[str, Any]: ...

    def explain(self, facts: dict[str, Any], language: str) -> dict[str, Any]: ...


class NullAI:
    """Used when no AI provider is configured."""

    provider = "none"
    enabled = False
    model = None

    def extract_label(self, images: list[tuple[bytes, str]]) -> dict[str, Any]:
        raise AIError("AI label reading is not configured on this server.", 503)

    def explain(self, facts: dict[str, Any], language: str) -> dict[str, Any]:
        raise AIError("AI explanations are not configured on this server.", 503)


def build_ai_client(settings: Settings) -> AIClient:
    from .claude import ClaudeClient
    from .gemini import GeminiClient

    provider = settings.resolved_ai_provider
    if provider == "anthropic":
        return ClaudeClient(settings)
    if provider == "gemini":
        return GeminiClient(settings)
    return NullAI()


# ---- shared prompt material ------------------------------------------------
def _num() -> dict[str, Any]:
    return {"type": "NUMBER", "nullable": True}


def extraction_schema(categories: tuple[str, ...]) -> dict[str, Any]:
    """Schema in Gemini's OpenAPI subset; `to_json_schema` converts it for Claude."""
    return {
        "type": "OBJECT",
        "properties": {
            "is_food_label": {"type": "BOOLEAN"},
            "product_name": {"type": "STRING", "nullable": True},
            "brand": {"type": "STRING", "nullable": True},
            "category": {"type": "STRING", "enum": list(categories)},
            "is_liquid": {"type": "BOOLEAN"},
            "net_quantity": {"type": "STRING", "nullable": True},
            "serving_size_g": _num(),
            "ingredients_text": {"type": "STRING", "nullable": True},
            "additive_codes": {"type": "ARRAY", "items": {"type": "STRING"}},
            "allergens_declared": {"type": "ARRAY", "items": {"type": "STRING"}},
            "traces": {"type": "ARRAY", "items": {"type": "STRING"}},
            "veg_mark": {"type": "STRING", "enum": ["veg", "non_veg", "not_visible"]},
            "nutrition_basis": {"type": "STRING", "enum": ["per_100g", "per_100ml", "per_serving", "not_visible"]},
            "nutrition": {
                "type": "OBJECT",
                "properties": {
                    "energy_kcal": _num(), "fat_g": _num(), "saturated_fat_g": _num(), "trans_fat_g": _num(),
                    "carbohydrates_g": _num(), "sugars_g": _num(), "added_sugars_g": _num(), "fiber_g": _num(),
                    "protein_g": _num(), "sodium_mg": _num(), "salt_g": _num(),
                },
            },
            "fruit_veg_nuts_percent": _num(),
            "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
            "notes": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["is_food_label", "category", "is_liquid", "nutrition_basis", "nutrition", "confidence"],
    }


EXTRACTION_PROMPT = """You are reading photos of a packaged food or drink label (front of pack, ingredient list and/or nutrition table). Return JSON only.

Rules:
- Copy the ingredient list exactly as printed into ingredients_text, in English if an English list is printed. Keep percentages and INS/E codes as written.
- additive_codes: every additive code printed, e.g. "INS 621", "E330", "(500(ii))" -> "500".
- Nutrition: copy numbers exactly as printed and say which basis they use (per 100 g, per 100 ml, or per serving). If the table has both per-100 and per-serving columns, use the per-100 column. Convert kJ to kcal only if kcal is not printed (kcal = kJ / 4.184). If sodium is printed in mg, put it in sodium_mg. If a value is not visible or not readable, use null. NEVER guess or estimate a number that is not printed.
- serving_size_g: the serving size in grams or millilitres, if printed.
- allergens_declared: allergens listed in a 'Contains' statement. traces: allergens in a 'May contain' statement.
- veg_mark: "veg" if the green square-with-dot vegetarian mark is visible, "non_veg" if the brown mark is visible, otherwise "not_visible".
- fruit_veg_nuts_percent: only if the ingredient list prints percentages for fruit, vegetables, pulses or nuts; otherwise null.
- category: pick the closest category; use "other" if unsure.
- is_food_label: false if the photos do not show a food or drink label.
- confidence: "low" if the photo is blurry, cut off or partly unreadable. Put what you could not read in notes.
"""

EXPLANATION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "key_points": {"type": "ARRAY", "items": {"type": "STRING"}},
        "who_should_be_careful": {"type": "STRING", "nullable": True},
        "tip": {"type": "STRING"},
    },
    "required": ["headline", "summary", "key_points", "tip"],
}

EXPLANATION_PROMPT = """You explain a food product's health report to an ordinary shopper in India.
Write in {language}. Use simple words. Be calm and factual, never alarmist.

STRICT RULES:
- Use ONLY the facts in the JSON below. Do not add any health claim, number, disease, study or ingredient that is not in the facts.
- Never say the product "causes" a disease. Use "linked with" and keep the evidence level given.
- Never tell the person to stop medication or replace medical advice.
- Do not criticise the brand; describe the product.
- headline: max 12 words. summary: max 70 words. key_points: 3 to 5 short bullets. tip: one practical swap or portion tip (use the home_swaps if relevant).

FACTS:
{facts}
"""


def language_name(language: str) -> str:
    return "Hindi (Devanagari script)" if language == "hi" else "English"


def to_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert the OpenAPI-subset schema (UPPERCASE types, `nullable`) to JSON Schema."""
    s = copy.deepcopy(schema)
    out: dict[str, Any] = {}
    t = s.get("type")
    if t:
        jt = t.lower()
        out["type"] = [jt, "null"] if s.get("nullable") else jt
    if "enum" in s:
        out["enum"] = list(s["enum"]) + ([None] if s.get("nullable") else [])
    if "properties" in s:
        out["properties"] = {k: to_json_schema(v) for k, v in s["properties"].items()}
    if "items" in s:
        out["items"] = to_json_schema(s["items"])
    if "required" in s:
        out["required"] = list(s["required"])
    return out
