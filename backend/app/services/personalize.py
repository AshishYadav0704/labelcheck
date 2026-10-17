"""Turns the general analysis into advice for one person (age group, conditions,
allergies). The profile is used only for this calculation and is never stored."""
from __future__ import annotations

import re
from typing import Any

from ..models import Profile, ProductData
from .scoring import AZO_COLOURS, NITRITES, PHOSPHATES, SWEETENER_WORD, daily_limits, per_serving
from .standards import Standards

ALLERGEN_NAMES = {
    "gluten": "gluten (wheat)", "milk": "milk", "egg": "egg", "peanut": "peanut", "tree_nuts": "tree nuts",
    "soy": "soy", "fish": "fish", "crustacean": "shellfish", "sesame": "sesame", "mustard": "mustard",
    "sulphites": "sulphites",
}
CONDITION_NAMES = {
    "diabetes": "diabetes", "hypertension": "high blood pressure", "heart_disease": "heart disease",
    "kidney_disease": "kidney disease", "pregnancy": "pregnancy", "pku": "phenylketonuria (PKU)",
    "gout": "gout", "asthma": "asthma", "thyroid_condition": "a thyroid condition", "weight_loss": "weight loss",
}


DIET_NAMES = {"vegetarian": "vegetarian", "eggetarian": "vegetarian + egg", "vegan": "vegan", "jain": "Jain"}
# Animal-derived additives most Indian vegetarians accept (bee and lac products).
VEG_ACCEPTED_ANIMAL = {"901", "904"}


def _alert(level: str, title: str, detail: str) -> dict[str, str]:
    return {"level": level, "title": title, "detail": detail}


def _find(text: str, words: list[str], exclude: list[str] | None = None) -> list[str]:
    for phrase in exclude or []:
        text = text.replace(phrase, " ")
    hits = []
    for w in words:
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text) and w not in hits:
            hits.append(w)
    return hits


def diet_alerts(product: ProductData, analysis: dict[str, Any], diet: str, std: Standards) -> list[dict[str, str]]:
    """Checks the ingredient list and FSSAI veg mark against a diet. Never says 'suitable'
    with certainty: ingredient lists don't always reveal the source of an ingredient."""
    if diet == "any":
        return []
    rules = std.standards["diets"]
    name = DIET_NAMES[diet]
    text = re.sub(r"\s+", " ", (product.ingredients_text or ", ".join(product.ingredients)).lower())
    alerts: list[dict[str, str]] = []
    if not text.strip():
        alerts.append(_alert("info", f"Couldn't check if it's {name}",
                             "There is no ingredient list. Look for the green veg mark on the pack."))
    meat = _find(text, rules["meat_fish"])
    egg = _find(text, rules["egg"])
    dairy = _find(text, rules["dairy"], rules["dairy_exclude"])
    bee = _find(text, rules["bee"])
    animal_yes = [a for a in analysis["additives"] if a.get("animal_origin") == "yes"]
    animal_maybe = [a for a in analysis["additives"] if a.get("animal_origin") == "maybe"]
    if diet in ("vegetarian", "jain", "vegan"):
        animal_yes_for_diet = animal_yes if diet == "vegan" else [a for a in animal_yes if a["ins"] not in VEG_ACCEPTED_ANIMAL]
    else:  # eggetarian
        animal_yes_for_diet = [a for a in animal_yes if a["ins"] not in VEG_ACCEPTED_ANIMAL]

    def avoid(what: str, detail: str) -> None:
        alerts.append(_alert("avoid", f"Not {name}: {what}", detail))

    if meat:
        avoid(", ".join(meat[:3]), "The ingredient list includes meat, fish or other animal ingredients.")
    if egg and diet != "eggetarian":
        avoid(", ".join(egg[:2]), "Contains egg.")
    if product.veg_mark == "non_veg" and not meat and not (egg and diet != "eggetarian"):
        if diet == "eggetarian":
            alerts.append(_alert("caution", "Brown non-veg mark on the pack",
                                 "FSSAI's brown mark is used for egg as well as meat. Check the ingredients."))
        else:
            avoid("non-veg mark", "The pack carries FSSAI's brown non-vegetarian mark.")
    for a in animal_yes_for_diet:
        avoid(a["name"], a.get("animal_note") or "This additive is made from animals.")
    if diet == "vegan":
        if dairy:
            avoid(", ".join(dairy[:3]), "Contains milk or dairy ingredients.")
        if bee:
            avoid(", ".join(bee[:2]), "Contains a bee product.")
    if diet == "jain":
        jain = _find(text, rules["jain_avoid"])
        if jain:
            avoid(", ".join(jain[:4]), rules["jain_note"])
        if "honey" in bee:
            avoid("honey", "Honey is traditionally avoided in Jain diets.")
    for a in animal_maybe:
        alerts.append(_alert("caution", f"{a['name']} ({a['ins']}): source not stated",
                             (a.get("animal_note") or "Can be made from animal or plant sources.")
                             + (" The pack's green veg mark suggests a plant source." if product.veg_mark == "veg" else "")))
    return alerts


def personalise(product: ProductData, analysis: dict[str, Any], profile: Profile, std: Standards) -> dict[str, Any]:
    alerts: list[dict[str, str]] = []
    adjust = 0
    conds = set(profile.conditions)
    levels = analysis["nutrient_levels"]
    codes = {a["ins"] for a in analysis["additives"]}
    functions = " ".join(a.get("function", "") for a in analysis["additives"])
    flags = {f["id"] for f in analysis["ingredient_flags"]}
    n = product.nutrition
    sugary = levels["sugars_g"]["level"] == "high" or (product.is_liquid and (n.sugars_g or 0) >= 5)

    # Allergies: hard stop.
    wanted = {a.strip().lower() for a in profile.allergies}
    for group in sorted(wanted & set(analysis["allergens"])):
        alerts.append(_alert("avoid", f"Contains {ALLERGEN_NAMES.get(group, group)}",
                             "Listed in the ingredients. Not suitable for your allergy."))
    for group in sorted(wanted & set(analysis["traces"])):
        alerts.append(_alert("caution", f"May contain {ALLERGEN_NAMES.get(group, group)}",
                             "The label warns of possible traces (shared equipment). Avoid if your allergy is severe."))

    if "pku" in conds and "951" in codes:
        alerts.append(_alert("avoid", "Contains aspartame (phenylalanine)",
                             "People with phenylketonuria must avoid phenylalanine."))
    if "diabetes" in conds:
        if sugary:
            adjust -= 15
            alerts.append(_alert("avoid", "High in sugar", "Likely to raise blood sugar quickly. Choose an unsweetened option."))
        if "refined_flour" in flags:
            alerts.append(_alert("caution", "Refined flour (maida)", "Digests quickly and can spike blood sugar; whole grains are better."))
        if "965" in codes:
            alerts.append(_alert("caution", "Contains maltitol", "'Sugar-free' maltitol still raises blood sugar somewhat."))
    if conds & {"hypertension", "heart_disease"}:
        if levels["salt_g"]["level"] == "high":
            adjust -= 15
            alerts.append(_alert("avoid", "High in salt", "Salt raises blood pressure. Keep total salt under 5 g a day."))
        elif levels["salt_g"]["level"] == "medium":
            alerts.append(_alert("caution", "Moderate salt", "Count this towards your 5 g daily salt limit."))
        if levels["saturated_fat_g"]["level"] == "high" or "trans_fat_source" in flags:
            adjust -= 10
            alerts.append(_alert("avoid", "Saturated or trans fat", "Raises LDL cholesterol, which matters for heart health."))
        if "621" in codes:
            alerts.append(_alert("caution", "Contains MSG", "Adds extra sodium on top of salt."))
    if "kidney_disease" in conds:
        if codes & PHOSPHATES:
            adjust -= 10
            alerts.append(_alert("avoid", "Phosphate additives", "Phosphorus from additives is almost fully absorbed. Ask your doctor or dietitian about phosphate limits."))
        if "508" in codes:
            alerts.append(_alert("caution", "Potassium chloride", "Adds potassium, which may need limiting in kidney disease."))
        if levels["salt_g"]["level"] == "high":
            adjust -= 5
            alerts.append(_alert("avoid", "High in salt", "Extra salt strains the kidneys."))
    if "pregnancy" in conds:
        if "caffeine" in flags:
            alerts.append(_alert("caution", "Contains caffeine", "Keep total caffeine under about 200 mg a day in pregnancy."))
        if codes & NITRITES:
            alerts.append(_alert("caution", "Processed meat preservatives", "Limit processed meats; also make sure meat is fully cooked."))
        if "320" in codes:
            alerts.append(_alert("caution", "Contains BHA", "Possibly carcinogenic (IARC 2B); easy to avoid by choosing another brand."))
    if "gout" in conds and codes & {"627", "631", "635"}:
        alerts.append(_alert("caution", "Purine flavour enhancers", "Guanylates and inosinates contain purines, which can raise uric acid."))
    if "asthma" in conds and codes & {"220", "221", "222", "223", "224", "225", "226", "227", "228", "210", "211"}:
        alerts.append(_alert("caution", "Sulphites or benzoates", "These preservatives can trigger symptoms in some people with asthma."))
    if "thyroid_condition" in conds and "127" in codes:
        alerts.append(_alert("caution", "Contains erythrosine", "Contains iodine and affected the thyroid in animal studies."))
    if "weight_loss" in conds:
        if (n.energy_kcal or 0) >= 400 and not product.is_liquid:
            adjust -= 5
            alerts.append(_alert("caution", "Energy-dense", f"{n.energy_kcal:g} kcal per 100 g — easy to overeat. Watch the portion."))
        if sugary and product.is_liquid:
            adjust -= 10
            alerts.append(_alert("avoid", "Liquid sugar", "Calories from drinks don't fill you up."))
        if SWEETENER_WORD in functions:
            alerts.append(_alert("info", "Non-sugar sweeteners", "WHO advises against relying on sweeteners for weight control."))

    if profile.age_group == "child":
        if "caffeine" in flags:
            adjust -= 10
            alerts.append(_alert("avoid", "Contains caffeine", "Not recommended for children."))
        if codes & AZO_COLOURS:
            alerts.append(_alert("caution", "Synthetic azo colours", "Linked with hyperactivity in some children; the EU requires a warning label."))
        if SWEETENER_WORD in functions:
            alerts.append(_alert("caution", "Non-sugar sweeteners", "Not recommended for young children."))
        if sugary:
            adjust -= 5
            alerts.append(_alert("caution", "Sugary", "Children's daily sugar limit is lower than adults'."))

    alerts.extend(diet_alerts(product, analysis, profile.diet, std))

    # General at-risk tags on additives (for anyone with a matching condition).
    for a in analysis["additives"]:
        hit = set(a.get("at_risk") or []) & conds
        if hit and not any(a["name"] in al["title"] for al in alerts):
            alerts.append(_alert("caution", f"{a['name']} ({a['ins']})",
                                 f"Flagged for people with {', '.join(CONDITION_NAMES.get(h, h) for h in sorted(hit))}. {a.get('note', '')}".strip()))

    levels_rank = {"avoid": 0, "caution": 1, "info": 2}
    alerts.sort(key=lambda al: levels_rank[al["level"]])
    personal_score = max(0, min(100, analysis["score"] + adjust))
    if any(al["level"] == "avoid" for al in alerts):
        suitability = "not_suitable"
    elif any(al["level"] == "caution" for al in alerts):
        suitability = "caution"
    else:
        suitability = "suitable"

    return {
        "profile_applied": bool(profile.conditions or profile.allergies or profile.age_group != "adult"
                                or profile.diet != "any"),
        "age_group": profile.age_group,
        "diet": profile.diet,
        "personal_score": personal_score,
        "suitability": suitability,
        "alerts": alerts,
        "daily_limits": {k: v["limit"] for k, v in daily_limits(std, profile.age_group).items()},
        "per_serving": per_serving(product, std, profile.age_group),
    }
