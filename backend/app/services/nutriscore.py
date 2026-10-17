"""Nutri-Score, original algorithm as published by Sante publique France (2017).

Points are computed per 100 g (foods) or per 100 ml (drinks). The 2017 version is
used because it is fully documented and widely implemented; cheese and added-fat
special cases are not handled (they are rare in this app's categories).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Nutrition

# Thresholds: a point is scored for every threshold the value is strictly above.
_ENERGY_KJ = [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350]
_SUGARS_G = [4.5, 9, 13.5, 18, 22.5, 27, 31, 36, 40, 45]
_SAT_FAT_G = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
_SODIUM_MG = [90, 180, 270, 360, 450, 540, 630, 720, 810, 900]
_FIBER_G = [0.9, 1.9, 2.8, 3.7, 4.7]
_PROTEIN_G = [1.6, 3.2, 4.8, 6.4, 8.0]

_BEV_ENERGY_KJ = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270]
_BEV_SUGARS_G = [0, 1.5, 3, 4.5, 6, 7.5, 9, 10.5, 12, 13.5]

KCAL_TO_KJ = 4.184


def _pts(value: float | None, thresholds: list[float]) -> int:
    if value is None:
        return 0
    return sum(1 for t in thresholds if value > t)


def _fruit_points(percent: float | None, beverage: bool) -> int:
    p = percent or 0
    if beverage:
        return 10 if p > 80 else 4 if p > 60 else 2 if p > 40 else 0
    return 5 if p > 80 else 2 if p > 60 else 1 if p > 40 else 0


@dataclass
class NutriScore:
    grade: str | None
    points: int | None
    negative: dict[str, int]
    positive: dict[str, int]
    beverage: bool
    missing: list[str]
    complete: bool

    def as_dict(self) -> dict:
        return {
            "grade": self.grade,
            "points": self.points,
            "negative_points": self.negative,
            "positive_points": self.positive,
            "beverage": self.beverage,
            "missing_nutrients": self.missing,
            "complete": self.complete,
            "algorithm": "Nutri-Score (2017 algorithm)",
        }


def compute(n: Nutrition, beverage: bool, fruit_veg_nuts_percent: float | None,
            is_water: bool = False) -> NutriScore:
    key_fields = {"energy": n.energy_kcal, "sugars": n.sugars_g, "saturated_fat": n.saturated_fat_g, "sodium": n.sodium_mg}
    missing = [k for k, v in key_fields.items() if v is None]
    if len(missing) >= 2:
        return NutriScore(None, None, {}, {}, beverage, missing, False)

    energy_kj = n.energy_kcal * KCAL_TO_KJ if n.energy_kcal is not None else None
    if beverage:
        neg = {
            "energy": _pts(energy_kj, _BEV_ENERGY_KJ),
            "sugars": _pts(n.sugars_g, _BEV_SUGARS_G),
            "saturated_fat": _pts(n.saturated_fat_g, _SAT_FAT_G),
            "sodium": _pts(n.sodium_mg, _SODIUM_MG),
        }
    else:
        neg = {
            "energy": _pts(energy_kj, _ENERGY_KJ),
            "sugars": _pts(n.sugars_g, _SUGARS_G),
            "saturated_fat": _pts(n.saturated_fat_g, _SAT_FAT_G),
            "sodium": _pts(n.sodium_mg, _SODIUM_MG),
        }
    fruit = _fruit_points(fruit_veg_nuts_percent, beverage)
    pos = {
        "fruit_veg_nuts": fruit,
        "fiber": _pts(n.fiber_g, _FIBER_G),
        "protein": _pts(n.protein_g, _PROTEIN_G),
    }
    negative_total = sum(neg.values())
    fruit_cap = 10 if beverage else 5
    if negative_total >= 11 and fruit < fruit_cap:
        # Protein does not offset an unhealthy profile unless fruit/veg content is high.
        points = negative_total - fruit - pos["fiber"]
        pos["protein_counted"] = 0
    else:
        points = negative_total - fruit - pos["fiber"] - pos["protein"]
        pos["protein_counted"] = 1

    if beverage:
        if is_water:
            grade = "A"
        else:
            grade = "B" if points <= 1 else "C" if points <= 5 else "D" if points <= 9 else "E"
    else:
        grade = "A" if points <= -1 else "B" if points <= 2 else "C" if points <= 10 else "D" if points <= 18 else "E"
    return NutriScore(grade, points, neg, pos, beverage, missing, not missing)
