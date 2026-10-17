"""Rule-based reader for label *text* (typed, pasted, or produced by OCR).

Turns free text into the same raw structure the AI providers return, so it goes
through the same validation (label.normalise_extraction). It understands the
usual Indian label layout: "Ingredients: ...", a "Nutritional Information"
table with per-100 g / per-serve columns, "Contains ..." / "May contain ..."
allergen lines, serving size and net quantity.
"""
from __future__ import annotations

import re
from typing import Any

KCAL_PER_KJ = 1 / 4.184
READABLE_NAMES = {"energy": "energy", "saturated_fat_g": "saturated fat", "trans_fat_g": "trans fat",
                  "added_sugars_g": "added sugars", "sugars_g": "sugars", "fiber_g": "fibre",
                  "carbohydrates_g": "carbohydrate", "protein_g": "protein", "sodium": "sodium",
                  "salt_g": "salt", "fat_g": "fat"}

# Nutrient row labels -> field. Order matters: more specific labels first.
_ROWS: list[tuple[str, re.Pattern[str]]] = [
    ("energy", re.compile(r"\b(?:energy|calories|calorific value)\b", re.I)),
    ("saturated_fat_g", re.compile(r"(?<!un)(?<!un-)saturated\s*(?:fat|fatty)", re.I)),
    ("trans_fat_g", re.compile(r"\btrans\s*(?:fat|fatty)", re.I)),
    ("unsaturated", re.compile(r"(?:mono|poly)?\s*-?\s*unsaturated|\bmufa\b|\bpufa\b|cholesterol|omega", re.I)),
    ("added_sugars_g", re.compile(r"\badded\s+sugars?\b", re.I)),
    ("sugars_g", re.compile(r"\b(?:total\s+)?sugars?\b|of which sugars", re.I)),
    ("fiber_g", re.compile(r"\b(?:dietary\s+|total\s+dietary\s+)?fib(?:re|er)\b", re.I)),
    ("carbohydrates_g", re.compile(r"\b(?:total\s+)?carbohydrates?\b|\bcarbs?\b", re.I)),
    ("protein_g", re.compile(r"\bproteins?\b", re.I)),
    ("sodium", re.compile(r"\bsodium\b", re.I)),
    ("salt_g", re.compile(r"\bsalt\b", re.I)),
    ("fat_g", re.compile(r"\b(?:total\s+)?fats?\b", re.I)),
]
_IGNORE_ROW = re.compile(r"vitamin|calcium|iron|potassium|magnesium|zinc|iodine|folic|niacin|riboflavin|thiamine|"
                         r"phosphorus|selenium|%\s*rda|rda\s*%", re.I)
_NUMBER = re.compile(r"(?<![a-z\d.])(\d+(?:\.\d+)?)\s*(kcal|kj|mg|mcg|µg|g|ml|%)?", re.I)
_PER100 = re.compile(r"(?:per|/)\s*100\s*(g|gm|grams?|ml|mls?)\b|\b100\s*(g|gm|ml)\b", re.I)
_PERSERVE = re.compile(r"per\s*(?:serv(?:e|ing)|portion|pack|piece|bottle|can|sachet)", re.I)
_SERVING = [
    re.compile(r"serv(?:ing|e)\s*size\s*[:\-]?\s*(?:approx\.?\s*)?(\d+(?:\.\d+)?)\s*(g|gm|ml)\b", re.I),
    re.compile(r"per\s*serv(?:e|ing)\s*\(?\s*(\d+(?:\.\d+)?)\s*(g|gm|ml)\b", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*(g|gm|ml)\s*(?:per|/|=)\s*(?:1\s*)?serv(?:e|ing)", re.I),
    re.compile(r"one\s*serv(?:e|ing)\s*(?:is|=)?\s*(\d+(?:\.\d+)?)\s*(g|gm|ml)\b", re.I),
]
_NET = re.compile(r"net\s*(?:wt\.?|weight|quantity|qty\.?|vol(?:ume)?|contents?)\s*[:\-.]?\s*"
                  r"(\d+(?:\.\d+)?\s*(?:g|gm|kg|ml|l|litre|liter)s?)\b", re.I)
_INGREDIENTS = re.compile(r"\bingred[il1]ents?\s*(?:list)?\s*[:;\-–]?\s*", re.I)
_INGREDIENTS_STOP = re.compile(
    r"\n\s*\n|\n\s*(?=(?:nutrition|nutritional|allergen|allergy|best before|use by|mfd|mfg|manufactured|marketed|"
    r"packed|storage|store in|keep in|net\s*(?:wt|weight|quantity|qty)|fssai|lic\.?\s*no|customer care|mrp|batch|"
    r"b\.?\s*no|directions|how to|serving suggestion|for best|approx|typical values)\b)", re.I)
_CONTAINS = re.compile(r"(?<!may )(?<!may also )\bcontains?\s*[:\-]?\s*([a-z ,&/()\-]{3,120}?)(?:[.;\n]|$)", re.I)
_TRACES = re.compile(r"\bmay\s+(?:also\s+)?contains?\s*(?:traces\s+of)?\s*[:\-]?\s*([a-z ,&/()\-]{3,120}?)(?:[.;\n]|$)", re.I)
_LIQUID_WORDS = re.compile(r"\b(?:drink|beverage|juice|soda|cola|milkshake|lassi|water)\b", re.I)


def clean_text(text: str) -> str:
    text = text.replace("\r", "\n").replace(" ", " ").replace("\t", " ")
    text = re.sub(r"[|¦]", " ", text)                      # table rules from OCR
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)           # hyphenated line breaks
    # Common OCR confusions inside numbers: '1O.5' -> '10.5', '2.l' -> '2.1'.
    text = re.sub(r"(?<=\d)[oO](?=[\d.,\s]|$)", "0", text)
    text = re.sub(r"(?<=\d\.)[lI](?=\b)", "1", text)
    # Thousands separators ("1,167") then decimal commas ("15,7").
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    text = re.sub(r"(?<=\d),(?=\d{1,2}(?!\d))", ".", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text


def _column_index(lines: list[str]) -> tuple[str, int]:
    """Which basis the nutrition table uses and which numeric column is per 100."""
    for line in lines:
        m100 = _PER100.search(line)
        if m100:
            unit = (m100.group(1) or m100.group(2) or "g").lower()
            basis = "per_100ml" if unit.startswith("ml") else "per_100g"
            ms = _PERSERVE.search(line)
            return basis, 1 if ms and ms.start() < m100.start() else 0
    if any(_PERSERVE.search(line) for line in lines):
        return "per_serving", 0
    return "not_visible", 0


def _row_numbers(rest: str) -> list[tuple[float, str]]:
    out = []
    for m in _NUMBER.finditer(rest):
        unit = (m.group(2) or "").lower()
        if unit == "%":
            continue  # %RDA column
        out.append((float(m.group(1)), unit))
    return out


def parse_nutrition(text: str) -> tuple[dict[str, float | None], str, list[str]]:
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    basis, col = _column_index(raw_lines)
    # Rows written inline ("Energy 44 kcal, Fat 0 g, Sodium 10 mg") become one row each.
    lines: list[str] = []
    for ln in raw_lines:
        if ln.count(",") + ln.count(";") >= 2:
            lines.extend(p.strip() for p in re.split(r"[,;]", ln) if p.strip())
        else:
            lines.append(ln)
    # Pass 1: find nutrient rows and their numbers.
    rows: list[tuple[str, str, list[tuple[float, str]]]] = []
    for line in lines:
        if _IGNORE_ROW.search(line) and not re.search(r"\bsodium\b", line, re.I):
            continue
        for field, pattern in _ROWS:
            m = pattern.search(line)
            if not m:
                continue
            if field == "unsaturated":
                break
            label_unit = ""
            unit_in_label = re.search(r"\(\s*(kcal|kj|mg|g)\s*\)", line[m.end():m.end() + 12], re.I)
            if unit_in_label:
                label_unit = unit_in_label.group(1).lower()
            nums = _row_numbers(line[m.end():])
            if nums:
                rows.append((field, label_unit, nums))
            break

    # In a multi-column table, a row with a missing (misread) number is ambiguous:
    # we can't tell which column survived, so leave it empty rather than guess.
    counts = [len(n) for f, _, n in rows if f != "energy"]
    columns = max(set(counts), key=counts.count) if counts else 1

    found: dict[str, float | None] = {}
    energy_kcal: float | None = None
    energy_kj: float | None = None
    notes: list[str] = []
    unreadable: list[str] = []
    for field, label_unit, nums in rows:
        if field == "energy":
            kcal = [v for v, u in nums if u == "kcal"]
            kj = [v for v, u in nums if u == "kj"]
            if kcal:
                energy_kcal = energy_kcal if energy_kcal is not None else kcal[min(col, len(kcal) - 1)]
            elif kj:
                energy_kj = energy_kj if energy_kj is not None else kj[min(col, len(kj) - 1)]
            elif columns >= 2 and len(nums) < columns:
                unreadable.append("energy")
            elif label_unit == "kj":
                energy_kj = energy_kj if energy_kj is not None else nums[min(col, len(nums) - 1)][0]
            else:
                energy_kcal = energy_kcal if energy_kcal is not None else nums[min(col, len(nums) - 1)][0]
            continue
        if columns >= 2 and len(nums) < columns:
            unreadable.append(field)
            continue
        value, unit = nums[min(col, len(nums) - 1)]
        unit = unit or label_unit
        if field == "sodium":
            if found.get("sodium_mg") is None:
                if unit == "g" or (not unit and value < 5 and value != int(value)):
                    value *= 1000  # sodium given in grams
                found["sodium_mg"] = value
            continue
        if unit == "mg":
            value = value / 1000
        if found.get(field) is None:
            found[field] = value
    if energy_kcal is None and energy_kj is not None:
        energy_kcal = round(energy_kj * KCAL_PER_KJ, 1)
        notes.append("Energy was given in kJ and converted to kcal.")
    if energy_kcal is not None:
        found["energy_kcal"] = energy_kcal
    missing = [READABLE_NAMES.get(f, f) for f in unreadable
               if found.get("sodium_mg" if f == "sodium" else f) is None and not (f == "energy" and energy_kcal)]
    if missing:
        notes.append("Couldn't read " + ", ".join(dict.fromkeys(missing)) + " clearly; please type it in.")
    return found, basis, notes


def parse_ingredients(text: str) -> tuple[str | None, tuple[int, int] | None]:
    """Returns the ingredient list and its (start, end) span in the text."""
    m = _INGREDIENTS.search(text)
    if not m:
        return None, None
    rest = text[m.end():]
    stop = _INGREDIENTS_STOP.search(rest)
    end = m.end() + (stop.start() if stop else min(len(rest), 3000))
    chunk = re.sub(r"\s*\n\s*", " ", text[m.end():end]).strip(" .;:-")
    return (chunk[:6000] or None), (m.start(), end)


_NUTRITION_HEADER = re.compile(r"nutrition(?:al)?\s*(?:information|info|facts|values?|declaration)", re.I)


def parse_label_text(text: str, name: str | None = None, brand: str | None = None) -> dict[str, Any]:
    text = clean_text(text)
    ingredients, span = parse_ingredients(text)
    # Read the nutrition table only from text outside the ingredient list (which
    # also mentions salt, sugar and fat, often next to INS numbers), starting
    # at the table heading when there is one.
    rest = text[: span[0]] + "\n" + text[span[1]:] if span else text
    header = _NUTRITION_HEADER.search(rest)
    nutrition, basis, notes = parse_nutrition(rest[header.start():] if header else rest)
    serving = None
    for pattern in _SERVING:
        m = pattern.search(text)
        if m:
            serving = float(m.group(1))
            break
    net = _NET.search(text)
    def split_list(s: str) -> list[str]:
        return [p.strip(" ()").lower() for p in re.split(r",|&|/|\band\b", s, flags=re.I) if p.strip(" ()")]

    contains = []
    for m in _CONTAINS.finditer(text):
        contains += split_list(m.group(1))
    traces = []
    for m in _TRACES.finditer(text):
        traces += split_list(m.group(1))
    contains = [c for c in contains if c.lower() not in {t.lower() for t in traces}]

    is_liquid = basis == "per_100ml" or bool(net and re.search(r"(ml|l|litre|liter)s?$", net.group(1).lower()))
    if not is_liquid and name and _LIQUID_WORDS.search(name):
        is_liquid = True
    nutrient_count = sum(1 for v in nutrition.values() if v is not None)
    if basis == "not_visible" and nutrient_count >= 3:
        basis = "per_100ml" if is_liquid else "per_100g"
        notes.append("The table did not say 'per 100 g'; values were assumed to be per 100.")
    if not ingredients:
        notes.append("No 'Ingredients:' list was found in the text.")
    if nutrient_count == 0:
        notes.append("No nutrition table values were found in the text.")
    confidence = "medium" if ingredients and nutrient_count >= 5 else "low"
    return {
        "is_food_label": bool(ingredients or nutrient_count >= 2),
        "product_name": name,
        "brand": brand,
        "category": "other",
        "is_liquid": is_liquid,
        "net_quantity": net.group(1) if net else None,
        "serving_size_g": serving,
        "ingredients_text": ingredients,
        "additive_codes": [],
        "allergens_declared": contains[:20],
        "traces": traces[:20],
        "veg_mark": "not_visible",
        "nutrition_basis": basis,
        "nutrition": nutrition,
        "fruit_veg_nuts_percent": None,
        "confidence": confidence,
        "notes": notes,
    }
