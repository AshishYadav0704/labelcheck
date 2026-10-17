"""Loads the curated reference data in app/data once and indexes it for lookups."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str) -> dict[str, Any]:
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def normalise_ins(code: str) -> str | None:
    """'E 330', 'INS330', '(330)', 'ins 150d', 'e471' -> '330', '150d', '471'."""
    m = re.search(r"(\d{3,4})\s*([a-z])?(?![a-z])", code.strip().lower())
    if not m:
        return None
    return m.group(1) + (m.group(2) or "")


@dataclass(frozen=True)
class Standards:
    additives: dict[str, dict[str, Any]]           # ins code -> entry
    additive_aliases: list[tuple[re.Pattern[str], str]]  # name pattern -> ins code
    standards: dict[str, Any]
    health_links: dict[str, dict[str, Any]]         # trigger -> link
    swaps: dict[str, dict[str, Any]]                # category -> swaps entry
    meta: dict[str, Any]

    def additive(self, code: str) -> dict[str, Any] | None:
        ins = normalise_ins(code)
        if ins is None:
            return None
        if ins in self.additives:
            return self.additives[ins]
        # 'E450i' / '150d' fall back to the parent family when only that is listed.
        base = re.sub(r"[a-z]$", "", ins)
        return self.additives.get(base)


@lru_cache
def get_standards() -> Standards:
    add_doc = _load("additives.json")
    additives = {a["ins"]: a for a in add_doc["additives"]}

    aliases: list[tuple[re.Pattern[str], str]] = []
    for entry in add_doc["additives"]:
        for alias in {entry["name"].lower(), *[a.lower() for a in entry.get("aliases", [])]}:
            # Short aliases like 'msg', 'bha', 'ssl' must match as whole words.
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])")
            aliases.append((pattern, entry["ins"]))
    # Longest alias first so 'sodium metabisulphite' wins over 'sulphite'.
    aliases.sort(key=lambda item: len(item[0].pattern), reverse=True)

    std = _load("standards.json")
    links_doc = _load("health_links.json")
    swaps_doc = _load("swaps.json")
    return Standards(
        additives=additives,
        additive_aliases=aliases,
        standards=std,
        health_links={link["trigger"]: link for link in links_doc["links"]},
        swaps=swaps_doc["categories"],
        meta={
            "additives": add_doc["meta"],
            "standards": std["meta"],
            "health_links": links_doc["meta"],
        },
    )
