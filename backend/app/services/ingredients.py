"""Reads an ingredient list: additives (INS / E numbers and names), allergens,
ingredient-level flags (hydrogenated fat, palm oil, maida...) and an estimated
NOVA processing group."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models import ProductData
from .standards import Standards, normalise_ins

# 'INS 621', 'E330', 'E-150d', 'ins.471'
_PREFIXED_CODE = re.compile(r"(?<![a-z])(?:ins|e)\s*[-.]?\s*(\d{3,4}\s?[a-z]?)(?![a-z0-9])", re.I)
# Bare codes inside brackets, as Indian labels print them: 'Emulsifier (322, 471)'.
_BRACKETS = re.compile(r"[\(\[]([^\(\)\[\]]{1,120})[\)\]]")
_BARE_CODE = re.compile(
    r"(?<![\d.%])(\d{3,4}[a-f]?)(?![\d%a-z])(?!\s*(?:g|mg|mcg|ml|kg|kcal|kj|ppm|%)(?![a-z]))", re.I
)
# Roman-numeral sub-codes such as '500 (ii)' would otherwise nest brackets.
_ROMAN_SUFFIX = re.compile(r"\(\s*(?:i{1,3}|iv|vi{0,3}|ix|x)\s*\)", re.I)

_NEGATED_SUGAR = re.compile(r"\b(no added sugars?|sugar[- ]free|without added sugar|zero sugar)\b", re.I)
_ALLERGEN_EXCLUDE = {
    "milk": ["coconut milk", "cocoa butter", "shea butter", "peanut butter", "nut butter", "milk thistle",
             "almond milk", "soy milk", "soya milk", "oat milk", "cream of tartar"],
    "peanut": [],
    "tree_nuts": ["coconut"],
    "gluten": ["gluten free", "gluten-free", "buckwheat"],
}
_TRACES_SPLIT = re.compile(r"\b(may contain|may also contain|traces of|manufactured in a facility|processed in a facility|packed in a facility)\b", re.I)


@dataclass
class IngredientAnalysis:
    additives: list[dict[str, Any]] = field(default_factory=list)
    unknown_additive_codes: list[str] = field(default_factory=list)
    allergens: list[str] = field(default_factory=list)
    traces: list[str] = field(default_factory=list)
    flags: list[dict[str, Any]] = field(default_factory=list)
    nova_group: int | None = None
    nova_reasons: list[str] = field(default_factory=list)
    ingredient_count: int = 0

    def has_flag(self, flag_id: str) -> bool:
        return any(f["id"] == flag_id for f in self.flags)

    def has_additive(self, *codes: str) -> bool:
        wanted = set(codes)
        return any(a["ins"] in wanted for a in self.additives)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _word_pattern(word: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z])" + re.escape(word.lower()) + r"(?![a-z])")


def find_additives(text: str, explicit_codes: list[str], std: Standards) -> tuple[list[dict[str, Any]], list[str]]:
    found: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []

    def add_code(raw: str, strict: bool) -> None:
        code = normalise_ins(raw.replace(" ", ""))
        if not code:
            return
        entry = std.additive(code)
        if entry:
            found.setdefault(entry["ins"], entry)
        elif not strict and code not in unknown:
            unknown.append(code)

    for raw in explicit_codes:
        add_code(raw, strict=False)
    text = _ROMAN_SUFFIX.sub("", text)
    for m in _PREFIXED_CODE.finditer(text):
        add_code(m.group(1), strict=False)
    for group in _BRACKETS.finditer(text):
        for m in _BARE_CODE.finditer(group.group(1)):
            add_code(m.group(1), strict=True)  # bare numbers only count if they are real INS codes
    for pattern, ins in std.additive_aliases:
        if ins not in found and pattern.search(text):
            found[ins] = std.additives[ins]
    return list(found.values()), unknown


def find_allergens(text: str, declared: list[str], std: Standards) -> tuple[list[str], list[str]]:
    groups: dict[str, list[str]] = std.standards["allergens"]["groups"]
    parts = _TRACES_SPLIT.split(text, maxsplit=1)
    main = parts[0]
    trace_text = "".join(parts[1:]) if len(parts) > 1 else ""

    def match(segment: str) -> set[str]:
        hits: set[str] = set()
        for group, words in groups.items():
            seg = segment
            for phrase in _ALLERGEN_EXCLUDE.get(group, []):
                seg = seg.replace(phrase, " ")
            if any(_word_pattern(w).search(seg) for w in words):
                hits.add(group)
        return hits

    contains = match(main) | match(_clean(" ".join(declared)).replace("-", " "))
    traces = match(trace_text) - contains
    return sorted(contains), sorted(traces)


def find_flags(text: str, std: Standards) -> list[dict[str, Any]]:
    scrubbed = _NEGATED_SUGAR.sub(" ", text)
    flags = []
    for flag in std.standards["ingredient_flags"]:
        if any(_word_pattern(k).search(scrubbed) for k in flag["keywords"]):
            flags.append({k: flag[k] for k in ("id", "label", "severity", "note")})
    return flags


def estimate_nova(text: str, ingredients: list[str], additives: list[dict[str, Any]],
                  flags: list[dict[str, Any]], std: Standards) -> tuple[int | None, list[str]]:
    nova = std.standards["nova"]
    if not text and not ingredients:
        return None, ["No ingredient list available."]

    reasons: list[str] = []
    up_functions = nova["ultra_processed_additive_functions"]
    for a in additives:
        fn = a.get("function", "").lower()
        if any(f in fn for f in up_functions):
            reasons.append(f"Contains {a['name']} ({fn.split(' (')[0]}), a cosmetic additive typical of ultra-processed food.")
    for kw in nova["ultra_processed_ingredients"]:
        if _word_pattern(kw).search(text):
            reasons.append(f"Contains '{kw}', an industrial ingredient typical of ultra-processed food.")
            break
    if any(f["id"] in {"artificial_flavour", "trans_fat_source", "protein_isolate"} for f in flags):
        reasons.append("Contains added flavourings or industrial fats.")
    if reasons:
        return 4, reasons[:3]

    count = len(ingredients) or len([p for p in re.split(r"[,;]", text) if p.strip()])
    culinary = [w for w in nova["culinary_ingredients"] if _word_pattern(w).search(text)]
    if count <= 1:
        if culinary:
            return 2, ["A single culinary ingredient (like oil, sugar or salt)."]
        return 1, ["A single, minimally processed food."]
    if culinary or additives:
        return 3, ["Food processed with salt, sugar, oil or simple preservatives."]
    return 1, ["Only whole or minimally processed ingredients."]


def analyse_ingredients(product: ProductData, std: Standards) -> IngredientAnalysis:
    text = _clean(product.ingredients_text or ", ".join(product.ingredients))
    additives, unknown = find_additives(text, product.additive_codes, std)
    allergens, traces = find_allergens(text, product.allergens_declared, std)
    declared_traces = find_allergens(_clean(" ".join(product.traces)).replace("-", " "), [], std)[0]
    traces = sorted((set(traces) | set(declared_traces)) - set(allergens))
    flags = find_flags(text, std)
    nova, reasons = estimate_nova(text, product.ingredients, additives, flags, std)
    count = len(product.ingredients) or (len([p for p in re.split(r"[,;]", text) if p.strip()]) if text else 0)
    return IngredientAnalysis(
        additives=additives,
        unknown_additive_codes=unknown,
        allergens=allergens,
        traces=traces,
        flags=flags,
        nova_group=nova,
        nova_reasons=reasons,
        ingredient_count=count,
    )
