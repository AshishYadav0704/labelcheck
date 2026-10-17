"""Builds the full report a client shows: rule-based analysis, personal advice,
alternatives and a plain-language explanation."""
from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..db import Database, product_id
from ..models import Profile, ProductData
from . import scoring
from .ai import AIClient, AIError
from .openfoodfacts import ATTRIBUTION, OpenFoodFactsClient
from .personalize import personalise
from .standards import Standards

log = logging.getLogger("labelcheck.report")

DISCLAIMER = (
    "General information based on the label and public standards (WHO, FSSAI, JECFA, IARC, EFSA). "
    "Not medical advice. Labels read from photos can contain mistakes — check important numbers on the pack. "
    "If you have a health condition, talk to your doctor or a dietitian."
)
SOURCES = [
    {"name": "WHO — Healthy diet, salt, sugars, trans fat guidance", "url": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"},
    {"name": "FSSAI — Food Safety and Standards Authority of India", "url": "https://www.fssai.gov.in"},
    {"name": "JECFA — FAO/WHO evaluations of food additives", "url": "https://apps.who.int/food-additives-contaminants-jecfa-database/"},
    {"name": "IARC Monographs — classifications", "url": "https://monographs.iarc.who.int/agents-classified-by-the-iarc/"},
    {"name": "EFSA — food additive re-evaluations", "url": "https://www.efsa.europa.eu/en/topics/topic/food-additives"},
    {"name": "Open Food Facts (product data, ODbL)", "url": "https://world.openfoodfacts.org"},
]
EXPLANATION_TTL = 30 * 24 * 3600

HI_VERDICT = {"A": "अच्छा विकल्प", "B": "नियमित रूप से ठीक", "C": "कभी-कभी ठीक",
              "D": "कभी-कभार ही खाएँ", "E": "नियमित सेवन से बचें"}
HI_WARN = {"HIGH FAT": "वसा (फैट) अधिक", "HIGH SATURATED FAT": "संतृप्त वसा अधिक", "HIGH SUGAR": "चीनी अधिक",
           "HIGH SALT": "नमक अधिक", "SWEETENED BEVERAGE": "मीठा पेय"}


class ReportService:
    def __init__(self, settings: Settings, db: Database, ai: AIClient, off: OpenFoodFactsClient, std: Standards):
        self.settings = settings
        self.db = db
        self.ai = ai
        self.off = off
        self.std = std
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="report")

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---- alternatives ----------------------------------------------------
    def alternatives(self, product: ProductData, analysis: dict[str, Any], pid: str) -> dict[str, Any]:
        entry = self.std.swaps.get(product.category) or self.std.swaps["other"]
        from_scans = self.db.better_in_category(product.category, analysis["score"] + 5, pid) \
            if product.category != "other" else []
        from_off: list[dict[str, Any]] = []
        if entry.get("off_tags") and analysis["grade"] in ("B", "C", "D", "E"):
            from_off = self.off.better_alternatives(entry["off_tags"][0], product.barcode)
        return {
            "category": product.category,
            "category_label": entry["label"],
            "from_scans": from_scans,
            "from_open_food_facts": from_off,
            "home_swaps": entry["swaps"],
            "attribution": ATTRIBUTION if from_off else None,
        }

    # ---- explanation -----------------------------------------------------
    @staticmethod
    def _facts(product: ProductData, analysis: dict[str, Any], personal: dict[str, Any], swaps: list[dict]) -> dict:
        return {
            "product": {"name": product.name, "brand": product.brand, "category": product.category,
                        "is_drink": product.is_liquid},
            "score_out_of_100": analysis["score"],
            "grade": analysis["grade"],
            "verdict": analysis["verdict"],
            "front_of_pack_warnings": analysis["front_of_pack_warnings"],
            "nutri_score": analysis["nutri_score"]["grade"],
            "processing_nova_group": analysis["nova"]["group"],
            "positives": analysis["positives"],
            "nutrients_per_100": {k: v["value"] for k, v in analysis["nutrient_levels"].items()},
            "additives_of_concern": [
                {"name": a["name"], "code": a["ins"], "concern": a["concern"], "note": a["note"]}
                for a in analysis["additives"] if a["concern"] in ("moderate", "high")
            ],
            "linked_health_effects": [
                {"title": r["title"], "effect": r["effect"], "evidence": r["evidence"], "why": r["reason"]}
                for r in analysis["health_risks"]
            ],
            "allergens": analysis["allergens"],
            "personal_alerts": [{"level": a["level"], "title": a["title"], "detail": a["detail"]} for a in personal["alerts"]],
            "home_swaps": [s["name"] for s in swaps],
        }

    @staticmethod
    def template_explanation(product: ProductData, analysis: dict[str, Any], personal: dict[str, Any],
                             swaps: list[dict], language: str) -> dict[str, Any]:
        warns = analysis["front_of_pack_warnings"]
        concern = [a["name"] for a in analysis["additives"] if a["concern"] in ("moderate", "high")]
        tip = swaps[0]["name"] if swaps else ""
        if language == "hi":
            points = [HI_WARN.get(w, w) for w in warns]
            if analysis["nova"]["group"] == 4:
                points.append("अति-प्रसंस्कृत भोजन (NOVA 4)")
            if concern:
                points.append("ध्यान देने योग्य एडिटिव: " + ", ".join(concern))
            points += [a["title"] for a in personal["alerts"][:2]]
            return {
                "headline": f"{product.name}: स्कोर {analysis['score']}/100 ({analysis['grade']}) — {HI_VERDICT[analysis['grade']]}",
                "summary": "यह रिपोर्ट लेबल पर दी गई जानकारी और WHO/FSSAI मानकों पर आधारित है।"
                           + (" मुख्य चिंताएँ: " + ", ".join(points[:3]) + "।" if points else " कोई बड़ी चिंता नहीं मिली।"),
                "key_points": points[:5] or ["कोई बड़ी चेतावनी नहीं मिली।"],
                "who_should_be_careful": None,
                "tip": f"बेहतर विकल्प: {tip}" if tip else "",
                "generated_by": "template",
            }
        points = [w.capitalize().replace("Saturated", "saturated") for w in warns]
        if analysis["nova"]["group"] == 4:
            points.append("Ultra-processed (estimated NOVA 4)")
        if concern:
            points.append("Additives worth knowing about: " + ", ".join(concern))
        points += analysis["positives"][:2]
        points += [a["title"] for a in personal["alerts"][:2]]
        issues = ", ".join(w.lower() for w in warns) if warns else ""
        summary = (f"Scores {analysis['score']}/100 (grade {analysis['grade']}). "
                   + (f"It is {issues.replace('high', 'high in').replace('sweetened beverage', 'a sweetened drink')}. " if issues else "")
                   + {"A": "A good everyday choice.", "B": "Fine as part of a balanced diet.",
                      "C": "Fine sometimes; don't make it a daily habit.",
                      "D": "Best kept as an occasional treat.", "E": "Avoid making this a regular part of your diet."}[analysis["grade"]])
        return {
            "headline": f"{analysis['verdict']}: {product.name}",
            "summary": summary,
            "key_points": points[:5] or ["No major warnings found."],
            "who_should_be_careful": None,
            "tip": f"Try instead: {tip}" if tip else "",
            "generated_by": "template",
        }

    def explanation(self, product: ProductData, analysis: dict[str, Any], personal: dict[str, Any],
                    swaps: list[dict], language: str) -> dict[str, Any]:
        facts = self._facts(product, analysis, personal, swaps)
        if not self.ai.enabled:
            return self.template_explanation(product, analysis, personal, swaps, language)
        digest = hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]
        key = f"expl:{self.ai.provider}:{self.ai.model}:{language}:{digest}"
        cached = self.db.cache_get(key)
        if cached:
            return cached
        try:
            out = self.ai.explain(facts, language)
            result = {
                "headline": str(out.get("headline", ""))[:160],
                "summary": str(out.get("summary", ""))[:900],
                "key_points": [str(p)[:240] for p in (out.get("key_points") or [])][:5],
                "who_should_be_careful": (str(out["who_should_be_careful"])[:300] if out.get("who_should_be_careful") else None),
                "tip": str(out.get("tip", ""))[:300],
                "generated_by": self.ai.provider,
            }
            if not result["headline"] or not result["summary"]:
                raise AIError("incomplete explanation")
            self.db.cache_set(key, result, EXPLANATION_TTL)
            return result
        except AIError as exc:
            log.warning("Falling back to template explanation: %s", exc)
            return self.template_explanation(product, analysis, personal, swaps, language)

    # ---- full report -----------------------------------------------------
    def build(self, product: ProductData, profile: Profile, report_id: str, created_at: str,
              explain: bool = True) -> dict[str, Any]:
        pid = product_id(product.barcode, product.name, product.brand)
        analysis = scoring.analyse(product, self.std)
        personal = personalise(product, analysis, profile, self.std)
        swaps = (self.std.swaps.get(product.category) or self.std.swaps["other"])["swaps"]

        alt_future = self._pool.submit(self.alternatives, product, analysis, pid)
        if explain:
            explanation = self.explanation(product, analysis, personal, swaps, profile.language)
        else:
            explanation = self.template_explanation(product, analysis, personal, swaps, profile.language)
        try:
            alternatives = alt_future.result(timeout=self.settings.off_timeout_s + 5)
        except Exception as exc:  # alternatives are optional; never fail the report for them
            log.warning("Alternatives unavailable: %s", exc)
            alternatives = {"category": product.category, "category_label": "", "from_scans": [],
                            "from_open_food_facts": [], "home_swaps": swaps, "attribution": None}

        return {
            "report_id": report_id,
            "created_at": created_at,
            "product": product.model_dump(),
            "analysis": analysis,
            "personal": personal,
            "alternatives": alternatives,
            "explanation": explanation,
            "links": {
                "self": f"/api/v1/reports/{report_id}",
                "simulation": f"/api/v1/reports/{report_id}/simulation",
                "video": f"/api/v1/reports/{report_id}/video.mp4",
                "share": f"/r/{report_id}",
            },
            "disclaimer": DISCLAIMER,
            "sources": SOURCES,
        }

    def create(self, product: ProductData, profile: Profile, explain: bool = True) -> dict[str, Any]:
        pid = product_id(product.barcode, product.name, product.brand)
        analysis = scoring.analyse(product, self.std)
        product_dict = product.model_dump()
        # Only real labels (photo, label text, barcode data) with complete data feed the alternatives database.
        dq = analysis["data_quality"]
        if (product.source in ("label_photo", "label_text", "barcode") and dq["nutrition_complete"]
                and dq["ingredients_available"] and product.extraction_confidence != "low"):
            self.db.upsert_product(pid, product_dict, analysis["score"], analysis["grade"])
        rid = self.db.save_report(pid, product_dict)
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return self.build(product, profile, rid, created, explain)

    def load(self, report_id: str, profile: Profile, explain: bool = True) -> dict[str, Any] | None:
        row = self.db.get_report(report_id)
        if not row:
            return None
        product = ProductData.model_validate(row["product"])
        return self.build(product, profile, row["id"], row["created_at"], explain)
