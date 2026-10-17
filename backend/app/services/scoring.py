"""The scoring engine: fixed, documented rules over verified reference data.

No AI is used here. Given the same product data it always returns the same
result, so every number in a report can be traced back to a rule and a source.
"""
from __future__ import annotations

from typing import Any

from ..models import ProductData
from . import nutriscore
from .ingredients import IngredientAnalysis, analyse_ingredients
from .standards import Standards

SCORING_VERSION = "1.0"

AZO_COLOURS = {"102", "110", "122", "124", "129"}
NITRITES = {"249", "250", "251", "252"}
PHOSPHATES = {"338", "339", "340", "341", "343", "450", "451", "452"}
SWEETENER_WORD = "sweetener (non-sugar"

NUTRIENT_LABELS = {
    "energy_kcal": ("Energy", "kcal"),
    "fat_g": ("Fat", "g"),
    "saturated_fat_g": ("Saturated fat", "g"),
    "trans_fat_g": ("Trans fat", "g"),
    "carbohydrates_g": ("Carbohydrates", "g"),
    "sugars_g": ("Sugars", "g"),
    "added_sugars_g": ("Added sugars", "g"),
    "fiber_g": ("Fibre", "g"),
    "protein_g": ("Protein", "g"),
    "salt_g": ("Salt", "g"),
    "sodium_mg": ("Sodium", "mg"),
}
HFSS_LABELS = {"fat_g": "HIGH FAT", "saturated_fat_g": "HIGH SATURATED FAT", "sugars_g": "HIGH SUGAR", "salt_g": "HIGH SALT"}

GRADES = [(80, "A", "Good choice"), (60, "B", "Fine for regular use"), (40, "C", "OK sometimes"),
          (20, "D", "Limit to an occasional treat"), (0, "E", "Avoid regular use")]
CONCERN_PENALTY = {"high": 10, "moderate": 4, "low": 0, "none": 0}


def daily_limits(std: Standards, age_group: str = "adult") -> dict[str, dict[str, Any]]:
    cfg = std.standards["daily_limits"]
    scale = cfg["child_energy_kcal"] / cfg["reference_energy_kcal"] if age_group == "child" else 1.0
    out = {}
    for key, item in cfg["nutrients"].items():
        limit = item["limit"] * scale if item["kind"] == "max" else item["limit"] * scale
        out[key] = {**item, "limit": round(limit, 2)}
    return out


def nutrient_levels(product: ProductData, std: Standards) -> dict[str, dict[str, Any]]:
    kind = "liquid" if product.is_liquid else "solid"
    high = std.standards["high_thresholds"][kind]
    low = std.standards["low_thresholds"][kind]
    n = product.nutrition
    levels = {}
    for key in ("fat_g", "saturated_fat_g", "sugars_g", "salt_g"):
        value = getattr(n, key)
        if value is None:
            level = "unknown"
        elif value > high[key]:
            level = "high"
        elif value <= low[key]:
            level = "low"
        else:
            level = "medium"
        levels[key] = {"label": NUTRIENT_LABELS[key][0], "value": value, "unit": "g", "level": level,
                       "high_above": high[key], "low_at_or_below": low[key]}
    return levels


def per_serving(product: ProductData, std: Standards, age_group: str = "adult") -> dict[str, Any] | None:
    if not product.serving_size_g:
        return None
    factor = product.serving_size_g / 100
    limits = daily_limits(std, age_group)
    values, share = {}, {}
    for key, (label, unit) in NUTRIENT_LABELS.items():
        v = getattr(product.nutrition, key)
        if v is None:
            continue
        values[key] = round(v * factor, 2)
        if key in limits:
            share[key] = round(100 * v * factor / limits[key]["limit"], 1)
    return {"serving_size": product.serving_size_g, "unit": "ml" if product.is_liquid else "g",
            "values": values, "percent_of_daily_limit": share}


def _nutrition_component(ns: nutriscore.NutriScore) -> tuple[float, str]:
    if ns.points is None:
        return 30.0, "Nutrition table incomplete, so a neutral score was used."
    if ns.beverage:
        p = min(max(ns.points, 0), 15)
        return 60 * (15 - p) / 15, f"Nutri-Score {ns.grade} ({ns.points} points, drink scale)."
    p = min(max(ns.points, -1), 25)
    return 60 * (25 - p) / 26, f"Nutri-Score {ns.grade} ({ns.points} points)."


def _processing_component(nova: int | None) -> tuple[float, str]:
    if nova is None:
        return 10.0, "Processing level unknown, so a neutral score was used."
    return {1: 20.0, 2: 16.0, 3: 12.0, 4: 4.0}[nova], f"Estimated NOVA group {nova}."


def _additive_component(ing: IngredientAnalysis) -> tuple[float, str]:
    penalty = sum(CONCERN_PENALTY.get(a.get("concern", "none"), 0) for a in ing.additives)
    concerning = [a["name"] for a in ing.additives if a.get("concern") in ("moderate", "high")]
    note = "No additives of concern." if not concerning else "Additives of concern: " + ", ".join(concerning) + "."
    return max(0.0, 20.0 - penalty), note


def _grade(score: int) -> tuple[str, str]:
    for floor, grade, verdict in GRADES:
        if score >= floor:
            return grade, verdict
    return "E", GRADES[-1][2]


def _n(x: float | None) -> str:
    return f"{round(x or 0, 1):g}"


def health_risks(product: ProductData, ing: IngredientAnalysis, levels: dict[str, Any],
                 std: Standards) -> list[dict[str, Any]]:
    n = product.nutrition
    triggers: list[tuple[str, str]] = []
    if levels["salt_g"]["level"] == "high":
        triggers.append(("salt", f"High in salt: {_n(n.salt_g)} g per 100 {'ml' if product.is_liquid else 'g'}."))
    if product.is_liquid and (n.sugars_g or 0) >= 5:
        triggers.append(("sugary_drink", f"Sweetened drink: {_n(n.sugars_g)} g sugar per 100 ml."))
    elif levels["sugars_g"]["level"] == "high":
        triggers.append(("sugars", f"High in sugar: {_n(n.sugars_g)} g per 100 g."))
    if levels["saturated_fat_g"]["level"] == "high":
        triggers.append(("saturated_fat", f"High in saturated fat: {_n(n.saturated_fat_g)} g per 100 g."))
    if (n.trans_fat_g or 0) >= 0.2 or ing.has_flag("trans_fat_source"):
        why = f"Trans fat {_n(n.trans_fat_g)} g per 100 g." if (n.trans_fat_g or 0) >= 0.2 else "Contains hydrogenated fat."
        triggers.append(("trans_fat", why))
    if ing.nova_group == 4:
        triggers.append(("nova4", "Estimated to be ultra-processed (NOVA 4)."))
    if any(a["ins"] in NITRITES for a in ing.additives):
        triggers.append(("nitrite", "Contains nitrite/nitrate preservatives used in processed meat."))
    if ing.has_flag("refined_flour") and (n.fiber_g is None or n.fiber_g < 3):
        triggers.append(("low_fibre_refined", "Made with refined flour and low in fibre."))
    if any(SWEETENER_WORD in a.get("function", "") for a in ing.additives):
        triggers.append(("sweetener", "Contains non-sugar sweeteners."))
    if any(a["ins"] in AZO_COLOURS for a in ing.additives):
        triggers.append(("azo_colour", "Contains synthetic azo colours."))
    if any(a["ins"] in PHOSPHATES for a in ing.additives):
        triggers.append(("phosphate", "Contains phosphate additives."))
    if ing.has_flag("caffeine"):
        triggers.append(("caffeine", "Contains caffeine."))

    risks = []
    for trigger, reason in triggers:
        link = std.health_links.get(trigger)
        if link:
            risks.append({**{k: link[k] for k in ("id", "title", "effect", "evidence", "source", "url", "body_systems")},
                          "reason": reason})
    return risks


def positives(product: ProductData, ing: IngredientAnalysis, levels: dict[str, Any]) -> list[str]:
    n = product.nutrition
    unit = "100 ml" if product.is_liquid else "100 g"
    out = []
    if n.fiber_g is not None and n.fiber_g >= 6:
        out.append(f"High in fibre ({n.fiber_g:g} g per {unit}).")
    elif n.fiber_g is not None and n.fiber_g >= 3:
        out.append(f"Source of fibre ({n.fiber_g:g} g per {unit}).")
    if n.protein_g is not None and n.protein_g >= 10 and not product.is_liquid:
        out.append(f"Good source of protein ({n.protein_g:g} g per {unit}).")
    for key, label in (("sugars_g", "sugar"), ("salt_g", "salt"), ("saturated_fat_g", "saturated fat")):
        if levels[key]["level"] == "low":
            out.append(f"Low in {label}.")
    if ing.nova_group in (1, 2):
        out.append("Minimally processed.")
    if (product.ingredients_text or product.ingredients) and not ing.additives:
        out.append("No additives found in the ingredient list.")
    return out


def analyse(product: ProductData, std: Standards) -> dict[str, Any]:
    ing = analyse_ingredients(product, std)
    is_water = product.is_liquid and product.ingredients_text is not None and \
        product.ingredients_text.strip().lower() in {"water", "mineral water", "drinking water", "packaged drinking water"}
    ns = nutriscore.compute(product.nutrition, product.is_liquid, product.fruit_veg_nuts_percent, is_water)
    levels = nutrient_levels(product, std)

    nutrition_pts, nutrition_note = _nutrition_component(ns)
    processing_pts, processing_note = _processing_component(ing.nova_group)
    additive_pts, additive_note = _additive_component(ing)

    penalties: list[dict[str, Any]] = []
    high = [key for key, lv in levels.items() if lv["level"] == "high"]
    if high:
        penalties.append({"points": -min(9, 3 * len(high)),
                          "reason": "Front-of-pack 'high' warning for: " + ", ".join(HFSS_LABELS[k] for k in high)})
    if product.is_liquid and (product.nutrition.sugars_g or 0) >= 8:
        penalties.append({"points": -10, "reason": "Sugar-sweetened drink (8 g or more sugar per 100 ml)."})
    if ing.has_flag("trans_fat_source") or (product.nutrition.trans_fat_g or 0) >= 0.2:
        penalties.append({"points": -10, "reason": "Contains trans fat or hydrogenated fat."})

    raw = nutrition_pts + processing_pts + additive_pts + sum(p["points"] for p in penalties)
    banned = [a for a in ing.additives if "BANNED in India" in a.get("fssai", "")]
    if banned:
        raw = min(raw, 10)
        penalties.append({"points": 0, "reason": "Score capped: contains an additive banned in India ("
                          + ", ".join(a["name"] for a in banned) + ")."})
    score = int(round(min(100, max(0, raw))))
    grade, verdict = _grade(score)

    fop_warnings = [HFSS_LABELS[k] for k in high]
    if product.is_liquid and (product.nutrition.sugars_g or 0) >= 5:
        fop_warnings.append("SWEETENED BEVERAGE")

    data_quality = {
        "nutrition_complete": ns.complete,
        "missing_nutrients": ns.missing,
        "ingredients_available": bool(product.ingredients_text or product.ingredients),
        "extraction_confidence": product.extraction_confidence,
        "extraction_notes": product.extraction_notes,
        "read_by": product.read_by,
        "reviewed_by_user": product.reviewed,
        "veg_mark": product.veg_mark,
        "unrecognised_additive_codes": ing.unknown_additive_codes,
    }

    return {
        "scoring_version": SCORING_VERSION,
        "positives": positives(product, ing, levels),
        "score": score,
        "grade": grade,
        "verdict": verdict,
        "breakdown": {
            "nutrition": {"points": round(nutrition_pts, 1), "max": 60, "note": nutrition_note},
            "processing": {"points": processing_pts, "max": 20, "note": processing_note},
            "additives": {"points": additive_pts, "max": 20, "note": additive_note},
            "penalties": penalties,
        },
        "nutri_score": ns.as_dict(),
        "nova": {"group": ing.nova_group, "reasons": ing.nova_reasons, "estimated": True},
        "nutrient_levels": levels,
        "front_of_pack_warnings": fop_warnings,
        "per_serving": per_serving(product, std),
        "additives": [
            {k: a.get(k) for k in ("ins", "name", "function", "concern", "adi", "adi_note", "adi_source",
                                    "iarc", "fssai", "note", "regulatory", "at_risk", "animal_origin", "animal_note")}
            for a in sorted(ing.additives, key=lambda a: ["high", "moderate", "low", "none"].index(a.get("concern", "none")))
        ],
        "ingredient_flags": ing.flags,
        "allergens": ing.allergens,
        "traces": ing.traces,
        "health_risks": health_risks(product, ing, levels, std),
        "data_quality": data_quality,
    }
