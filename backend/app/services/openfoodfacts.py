"""Open Food Facts client: barcode lookup and 'better in the same category'
search. Data is ODbL-licensed; the app shows attribution wherever it is used."""
from __future__ import annotations

import logging
import re
from typing import Any

import requests

from ..config import Settings
from ..db import Database
from ..models import CATEGORIES, Nutrition, ProductData
from .standards import Standards

log = logging.getLogger("labelcheck.off")

PRODUCT_FIELDS = ",".join([
    "code", "product_name", "product_name_en", "brands", "quantity", "serving_quantity", "categories_tags",
    "ingredients_text", "ingredients_text_en", "additives_tags", "allergens_tags", "traces_tags", "nutriments",
    "image_front_url", "nutrition_data_per", "countries_tags",
])
SEARCH_FIELDS = "code,product_name,brands,nutrition_grades,quantity,image_front_small_url"
ATTRIBUTION = "Data from Open Food Facts (openfoodfacts.org), available under the Open Database License."

PRODUCT_TTL = 7 * 24 * 3600
NOT_FOUND_TTL = 24 * 3600
SEARCH_TTL = 24 * 3600


class OpenFoodFactsError(Exception):
    pass


def _f(nutriments: dict[str, Any], key: str) -> float | None:
    v = nutriments.get(key)
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def guess_category(tags: list[str], name: str, std: Standards) -> str:
    tagset = set(tags)
    lowered = name.lower()
    for cat, entry in std.swaps.items():
        if tagset & set(entry.get("off_tags", [])):
            return cat
    for cat, entry in std.swaps.items():
        if any(k in lowered for k in entry.get("keywords", [])):
            return cat
    return "other"


def to_product(p: dict[str, Any], std: Standards) -> ProductData:
    nm = p.get("nutriments") or {}
    energy = _f(nm, "energy-kcal_100g")
    if energy is None and _f(nm, "energy_100g") is not None:
        energy = round(_f(nm, "energy_100g") / 4.184, 1)  # type: ignore[operator]
    sodium_g = _f(nm, "sodium_100g")
    nutrition = Nutrition(
        energy_kcal=energy,
        fat_g=_f(nm, "fat_100g"),
        saturated_fat_g=_f(nm, "saturated-fat_100g"),
        trans_fat_g=_f(nm, "trans-fat_100g"),
        carbohydrates_g=_f(nm, "carbohydrates_100g"),
        sugars_g=_f(nm, "sugars_100g"),
        added_sugars_g=_f(nm, "added-sugars_100g"),
        fiber_g=_f(nm, "fiber_100g"),
        protein_g=_f(nm, "proteins_100g"),
        salt_g=_f(nm, "salt_100g"),
        sodium_mg=sodium_g * 1000 if sodium_g is not None else None,
    )
    name = p.get("product_name_en") or p.get("product_name") or "Unnamed product"
    quantity = p.get("quantity") or ""
    tags = p.get("categories_tags") or []
    is_liquid = bool(re.search(r"\d\s*(ml|cl|l|litre|liter)\b", quantity.lower())) or \
        p.get("nutrition_data_per") == "100ml" or "en:beverages" in tags
    serving = p.get("serving_quantity")
    try:
        serving = float(serving) if serving not in (None, "") else None
    except (TypeError, ValueError):
        serving = None
    fvn = _f(nm, "fruits-vegetables-nuts-estimate-from-ingredients_100g")
    category = guess_category(tags, name, std)
    return ProductData(
        name=name[:200],
        brand=((p.get("brands") or "").split(",")[0].strip() or None),
        barcode=p.get("code"),
        category=category if category in CATEGORIES else "other",
        is_liquid=is_liquid,
        net_quantity=quantity[:60] or None,
        serving_size_g=serving if serving and 0 < serving <= 2000 else None,
        ingredients_text=(p.get("ingredients_text_en") or p.get("ingredients_text") or None),
        additive_codes=[t.split(":")[-1] for t in (p.get("additives_tags") or [])],
        allergens_declared=[t.split(":")[-1] for t in (p.get("allergens_tags") or [])],
        traces=[t.split(":")[-1] for t in (p.get("traces_tags") or [])],
        nutrition=nutrition,
        fruit_veg_nuts_percent=fvn if fvn is not None and 0 <= fvn <= 100 else None,
        image_url=p.get("image_front_url"),
        source="barcode",
    )


class OpenFoodFactsClient:
    def __init__(self, settings: Settings, db: Database, session: requests.Session | None = None):
        self.settings = settings
        self.db = db
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": settings.off_user_agent})

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.settings.off_base_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.settings.off_timeout_s)
        except requests.RequestException as exc:
            raise OpenFoodFactsError(f"Open Food Facts unreachable: {exc.__class__.__name__}") from exc
        if resp.status_code == 404:
            return {"status": 0}
        if resp.status_code != 200:
            raise OpenFoodFactsError(f"Open Food Facts returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise OpenFoodFactsError("Open Food Facts returned invalid JSON") from exc

    def lookup(self, barcode: str) -> dict[str, Any] | None:
        key = f"off:product:{barcode}"
        cached = self.db.cache_get(key)
        if cached is not None:
            return cached or None
        data = self._get(f"/api/v2/product/{barcode}", {"fields": PRODUCT_FIELDS})
        product = data.get("product") if data.get("status") == 1 else None
        self.db.cache_set(key, product or {}, PRODUCT_TTL if product else NOT_FOUND_TTL)
        return product

    def better_alternatives(self, off_tag: str, exclude_barcode: str | None, limit: int = 5) -> list[dict[str, Any]]:
        tag = off_tag.split(":", 1)[-1]
        key = f"off:search:{tag}"
        cached = self.db.cache_get(key)
        if cached is None:
            try:
                data = self._get("/api/v2/search", {
                    "categories_tags_en": tag,
                    "countries_tags_en": "india",
                    "nutrition_grades_tags": "a|b",
                    "fields": SEARCH_FIELDS,
                    "sort_by": "unique_scans_n",
                    "page_size": 12,
                })
            except OpenFoodFactsError as exc:
                log.warning("OFF search failed: %s", exc)
                return []
            cached = data.get("products") or []
            self.db.cache_set(key, cached, SEARCH_TTL)
        out = []
        for p in cached:
            if not p.get("product_name") or p.get("code") == exclude_barcode:
                continue
            out.append({
                "barcode": p.get("code"),
                "name": p.get("product_name"),
                "brand": (p.get("brands") or "").split(",")[0].strip() or None,
                "nutri_score": (p.get("nutrition_grades") or "").upper() or None,
                "quantity": p.get("quantity"),
                "image_url": p.get("image_front_small_url"),
            })
            if len(out) >= limit:
                break
        return out
