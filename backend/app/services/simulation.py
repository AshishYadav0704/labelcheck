"""Long-term 'what if I eat this regularly' illustration.

This is an ILLUSTRATIVE model, not a medical prediction. It converts how much of
each daily limit the product uses, times how often it is eaten, into a 0-1
'extra strain' value per body system that grows with years of regular intake.
The shape (saturating growth) and the weights are design choices that make the
general evidence easy to see; they are not fitted to clinical outcomes.
"""
from __future__ import annotations

import math
from typing import Any

from ..models import ProductData
from .scoring import daily_limits
from .standards import Standards

MODEL_NOTE = ("Illustration of general evidence about regular excess intake — not a prediction "
              "for any individual. Your overall diet, activity, genes and health care matter far more "
              "than any single product.")

K = 0.24  # growth constant: half a daily limit every day for 10 years -> ~0.7 strain

SYSTEMS = {
    "heart": "Heart & blood vessels",
    "metabolism": "Blood sugar & weight",
    "liver": "Liver",
    "kidneys": "Kidneys",
    "teeth": "Teeth",
    "gut": "Gut",
}

STAGES = [(0.2, "minimal"), (0.45, "mild"), (0.7, "moderate"), (1.01, "high")]

CAPTIONS = {
    "heart": {"mild": "Salt and fat add up: blood pressure and cholesterol start creeping up.",
              "moderate": "Arteries stiffen and narrow over time, raising heart-attack and stroke risk.",
              "high": "Sustained high blood pressure and cholesterol: a major heart-disease risk."},
    "metabolism": {"mild": "Frequent sugar spikes and extra calories.",
                   "moderate": "Weight gain and insulin resistance become more likely.",
                   "high": "Strong link with obesity and type 2 diabetes when eaten this often."},
    "liver": {"mild": "Excess sugar and calories are stored as fat.",
              "moderate": "Fat can build up in the liver (fatty liver).",
              "high": "Fatty liver risk is high with this level of intake."},
    "kidneys": {"mild": "Extra salt and phosphate additives give the kidneys more work.",
                "moderate": "High blood pressure from salt slowly strains the kidneys.",
                "high": "Long-term high salt intake is linked with kidney damage."},
    "teeth": {"mild": "Sugar feeds tooth-decay bacteria.",
              "moderate": "Frequent sugar and acid wear enamel and cause cavities.",
              "high": "High risk of tooth decay with this much sugar."},
    "gut": {"mild": "Low fibre and heavy processing: less food for healthy gut bacteria.",
            "moderate": "Low-fibre, ultra-processed diets are linked with bowel problems.",
            "high": "Regular processed meat is linked with bowel cancer (IARC Group 1)."},
}


def _share(product: ProductData, key: str, limits: dict[str, Any], serving_g: float) -> float:
    value = getattr(product.nutrition, key)
    if value is None:
        return 0.0
    return value * serving_g / 100 / limits[key]["limit"]


def _stage(v: float) -> str:
    for ceiling, name in STAGES:
        if v < ceiling:
            return name
    return "high"


def daily_loads(product: ProductData, analysis: dict[str, Any], std: Standards,
                servings_per_week: float, age_group: str = "adult") -> dict[str, float]:
    """Average share of the daily limit taken up by this product, per body system."""
    limits = daily_limits(std, age_group)
    serving = product.serving_size_g or (250.0 if product.is_liquid else 50.0)
    per_day = servings_per_week / 7
    salt = _share(product, "salt_g", limits, serving) * per_day
    sugar = _share(product, "sugars_g", limits, serving) * per_day
    sat = _share(product, "saturated_fat_g", limits, serving) * per_day
    trans = _share(product, "trans_fat_g", limits, serving) * per_day
    energy = _share(product, "energy_kcal", limits, serving) * per_day
    flags = {f["id"] for f in analysis["ingredient_flags"]}
    risks = {r["id"] for r in analysis["health_risks"]}
    if "trans_fat_source" in flags and trans == 0:
        trans = 0.1 * per_day  # hydrogenated fat without a declared amount: assume a small share
    nova4 = 0.15 * min(per_day, 2) if analysis["nova"]["group"] == 4 else 0.0
    acid_drink = 0.1 * per_day if product.is_liquid and {"338", "330"} & {a["ins"] for a in analysis["additives"]} else 0.0
    low_fibre = 0.15 * min(per_day, 2) if "low_fibre" in risks else 0.0
    processed_meat = 0.6 * min(per_day, 2) if "processed_meat" in risks else 0.0
    phosphate = 0.04 * min(per_day, 2) if "phosphates" in risks else 0.0

    return {
        "heart": 0.5 * salt + 0.4 * sat + 1.0 * trans + 0.1 * sugar,
        "metabolism": 0.6 * sugar + 0.3 * energy + nova4 + 0.5 * low_fibre,
        "liver": 0.5 * sugar + 0.3 * sat + 0.2 * energy,
        "kidneys": 0.7 * salt + phosphate,
        "teeth": 0.9 * sugar + acid_drink,
        "gut": low_fibre + 0.5 * nova4 + processed_meat,
    }


def simulate(product: ProductData, analysis: dict[str, Any], std: Standards,
             servings_per_week: float = 7, years: int = 10, age_group: str = "adult") -> dict[str, Any]:
    servings_per_week = max(0.0, min(float(servings_per_week), 35.0))
    years = max(1, min(int(years), 30))
    loads = daily_loads(product, analysis, std, servings_per_week, age_group)
    timeline = []
    for year in range(0, years + 1):
        systems = {}
        for key, load in loads.items():
            strain = 1 - math.exp(-K * load * year)
            systems[key] = {"strain": round(strain, 3), "stage": _stage(strain)}
        timeline.append({"year": year, "systems": systems})

    final = timeline[-1]["systems"]
    findings = []
    for key in sorted(final, key=lambda k: final[k]["strain"], reverse=True):
        stage = final[key]["stage"]
        if stage != "minimal":
            findings.append({"system": key, "label": SYSTEMS[key], "stage": stage,
                             "strain": final[key]["strain"], "caption": CAPTIONS[key][stage]})
    return {
        "servings_per_week": servings_per_week,
        "serving_size": product.serving_size_g,
        "serving_size_assumed": product.serving_size_g is None,
        "years": years,
        "systems": SYSTEMS,
        "daily_load": {k: round(v, 3) for k, v in loads.items()},
        "timeline": timeline,
        "findings": findings,
        "model_note": MODEL_NOTE,
    }
