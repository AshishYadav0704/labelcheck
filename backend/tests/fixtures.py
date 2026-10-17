"""Shared sample products and fakes for the tests."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models import ProductData

NOODLES: dict[str, Any] = {
    "name": "Masala instant noodles",
    "brand": "Test Foods",
    "category": "instant_noodles",
    "serving_size_g": 70,
    "ingredients_text": (
        "Refined wheat flour (maida), refined palmolein, salt, wheat gluten, thickeners (508, 412), "
        "acidity regulators (501(i), 500(ii)), humectant (451(i)), Masala tastemaker: spices, sugar, "
        "hydrolysed groundnut protein, flavour enhancer (INS 627, INS 631), colour (150d), TBHQ. "
        "Contains wheat. May contain milk, mustard and soy."
    ),
    "nutrition": {"energy_kcal": 427, "fat_g": 15.7, "saturated_fat_g": 7.5, "trans_fat_g": 0.1,
                  "carbohydrates_g": 62, "sugars_g": 2.1, "fiber_g": 2.3, "protein_g": 8.9, "sodium_mg": 1167},
}

COLA: dict[str, Any] = {
    "name": "Cola soft drink",
    "category": "sugary_drink",
    "is_liquid": True,
    "serving_size_g": 300,
    "ingredients_text": "Carbonated water, sugar, acidity regulator (338), caffeine, colour (150d), natural flavouring substances",
    "nutrition": {"energy_kcal": 44, "sugars_g": 10.9, "fat_g": 0, "saturated_fat_g": 0, "sodium_mg": 10,
                  "protein_g": 0, "carbohydrates_g": 10.9},
}

DAHI: dict[str, Any] = {
    "name": "Plain dahi",
    "category": "yogurt_dessert",
    "ingredients_text": "Pasteurised toned milk, active cultures",
    "nutrition": {"energy_kcal": 62, "fat_g": 3.1, "saturated_fat_g": 2.0, "sugars_g": 4.6, "sodium_mg": 45,
                  "protein_g": 3.6, "carbohydrates_g": 4.6},
}

BROMATE_BREAD: dict[str, Any] = {
    "name": "Test bread",
    "category": "bread_bakery",
    "ingredients_text": "Wheat flour, water, yeast, salt, potassium bromate",
    "nutrition": {"energy_kcal": 250, "fat_g": 2, "saturated_fat_g": 0.5, "sugars_g": 3, "sodium_mg": 400,
                  "protein_g": 9, "fiber_g": 6, "carbohydrates_g": 48},
}


def product(data: dict[str, Any], **overrides: Any) -> ProductData:
    d = copy.deepcopy(data)
    d.update(overrides)
    return ProductData.model_validate(d)


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "data_dir": Path(tempfile.mkdtemp(prefix="labelcheck-test-")),
        "gemini_api_key": "test-key",
        "web_dir": Path(__file__).resolve().parents[2] / "web",
        "rate_ai_per_min": 100,
        "rate_ai_per_day": 1000,
        "rate_default_per_min": 1000,
        "rate_video_per_min": 100,
        "trust_proxy_headers": True,
    }
    base.update(overrides)
    return Settings(**base)


GOOD_EXTRACTION: dict[str, Any] = {
    "is_food_label": True,
    "product_name": "Masala instant noodles",
    "brand": "Test Foods",
    "category": "instant_noodles",
    "is_liquid": False,
    "net_quantity": "70 g",
    "serving_size_g": 70,
    "ingredients_text": NOODLES["ingredients_text"],
    "additive_codes": ["INS 627", "INS 631"],
    "allergens_declared": ["wheat"],
    "traces": ["milk", "mustard", "soy"],
    "nutrition_basis": "per_100g",
    "nutrition": NOODLES["nutrition"],
    "fruit_veg_nuts_percent": None,
    "confidence": "high",
    "notes": [],
}


class FakeAI:
    """Stands in for an AI provider client (Claude or Gemini) without network calls."""

    def __init__(self, extraction: dict[str, Any] | None = None, enabled: bool = True, provider: str = "gemini",
                 error: Exception | None = None):
        self.extraction = extraction or GOOD_EXTRACTION
        self.enabled = enabled
        self.provider = provider
        self.model = "fake-model"
        self.error = error
        self.extract_calls = 0
        self.explain_calls = 0

    def extract_label(self, images: list[tuple[bytes, str]]) -> dict[str, Any]:
        self.extract_calls += 1
        assert all(mime == "image/jpeg" for _, mime in images)
        if self.error:
            raise self.error
        return copy.deepcopy(self.extraction)

    def explain(self, facts: dict[str, Any], language: str) -> dict[str, Any]:
        self.explain_calls += 1
        return {"headline": f"Explained {facts['product']['name']}", "summary": "A test summary.",
                "key_points": ["one", "two", "three"], "who_should_be_careful": None, "tip": "Eat fruit."}


FakeGemini = FakeAI  # backwards-compatible name


class FakeOCR:
    """Stands in for the Tesseract reader."""

    provider = "ocr"

    def __init__(self, enabled: bool = True, text: str | None = None):
        self.enabled = enabled
        self.text = text or SAMPLE_LABEL_TEXT
        self.calls = 0

    def extract_label(self, images: list[tuple[bytes, str]]) -> dict[str, Any]:
        from app.services.label_text import parse_label_text
        self.calls += 1
        return parse_label_text(self.text)


SAMPLE_LABEL_TEXT = """INGREDIENTS: Refined Wheat Flour (Maida), Refined Palm Oil, Salt, Wheat Gluten,
Thickeners (508 & 412), Acidity Regulators [501(i) & 500(ii)], Humectant [451(i)].
Masala Tastemaker: Spices & Condiments (Onion Powder, Garlic Powder, Coriander, Chilli),
Sugar, Flavour Enhancer (635), Colour (150d).
CONTAINS WHEAT. MAY CONTAIN MILK, MUSTARD AND SOY.
NUTRITIONAL INFORMATION (Approx. values) Per 100 g Per serve (70 g) %RDA*
Energy (kcal) 427 299 15%
Protein (g) 8.9 6.2
Carbohydrate (g) 62.0 43.4
Total Sugars (g) 2.1 1.5
Added Sugars (g) 1.0 0.7 1%
Total Fat (g) 15.7 11.0 16%
Saturated Fat (g) 7.5 5.3 24%
Trans Fat (g) 0.1 0.07
Sodium (mg) 1,167 817 41%
Net Wt. 70 g
"""


class FakeOFF:
    def __init__(self, products: dict[str, dict[str, Any]] | None = None):
        self.products = products or {}
        self.lookups: list[str] = []

    def lookup(self, barcode: str) -> dict[str, Any] | None:
        self.lookups.append(barcode)
        return copy.deepcopy(self.products.get(barcode))

    def better_alternatives(self, off_tag: str, exclude_barcode: str | None, limit: int = 5) -> list[dict[str, Any]]:
        return [{"barcode": "8900000000001", "name": "Millet noodles", "brand": "Good Co", "nutri_score": "B",
                 "quantity": "200 g", "image_url": None}]


OFF_PRODUCT: dict[str, Any] = {
    "code": "8901234567890",
    "product_name": "Salted potato chips",
    "brands": "Crunch Co, Other",
    "quantity": "52 g",
    "serving_quantity": "26",
    "categories_tags": ["en:snacks", "en:salty-snacks", "en:crisps"],
    "ingredients_text": "Potato, edible vegetable oil (palmolein), salt",
    "additives_tags": [],
    "allergens_tags": [],
    "traces_tags": ["en:milk"],
    "nutriments": {"energy-kcal_100g": 545, "fat_g": None, "fat_100g": 34, "saturated-fat_100g": 15,
                   "carbohydrates_100g": 52, "sugars_100g": 0.5, "fiber_100g": 4, "proteins_100g": 7,
                   "salt_100g": 1.4, "sodium_100g": 0.56},
    "image_front_url": "https://images.openfoodfacts.org/x.jpg",
}
