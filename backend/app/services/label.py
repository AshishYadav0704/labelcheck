"""Label photo pipeline: clean the uploaded images, read them (AI vision provider,
falling back to offline OCR), then validate and normalise the result into
ProductData. Typed/pasted label text goes through the same validation."""
from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from ..models import CATEGORIES, Nutrition, ProductData
from .ai import AIClient, AIError
from .label_text import parse_label_text
from .ocr import OCRReader

log = logging.getLogger("labelcheck.label")

MAX_SIDE = 2000          # px; enough to read small label text
JPEG_QUALITY = 88
NUTRIENT_KEYS = list(Nutrition.model_fields.keys())


class LabelError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def prepare_image(data: bytes) -> bytes:
    """Decode, auto-rotate, downscale and re-encode as JPEG.

    Re-encoding also strips EXIF metadata (such as GPS location) before the
    image leaves the server."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise LabelError("One of the files is not a readable image. Please send a JPEG or PNG photo.", 400) from exc


def _clean_number(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def normalise_extraction(raw: dict[str, Any], source: str = "label_photo", read_by: str | None = None) -> ProductData:
    if not raw.get("is_food_label", False):
        if source == "label_text":
            raise LabelError("Couldn't find an ingredient list or nutrition table in that text. "
                             "Include the line starting 'Ingredients:' and the nutrition table.")
        raise LabelError("This doesn't look like a food label. Take a clear photo of the ingredients and nutrition table.")

    notes = [str(n)[:200] for n in (raw.get("notes") or [])][:10]
    serving = _clean_number(raw.get("serving_size_g"))
    if serving is not None and not (0 < serving <= 2000):
        serving = None

    raw_nut = raw.get("nutrition") or {}
    nut = {k: _clean_number(raw_nut.get(k)) for k in NUTRIENT_KEYS}
    basis = raw.get("nutrition_basis", "not_visible")
    if basis == "per_serving":
        if serving:
            factor = 100 / serving
            nut = {k: (round(v * factor, 3) if v is not None else None) for k, v in nut.items()}
            notes.append("Nutrition was printed per serving and converted to per 100.")
        else:
            nut = {k: None for k in nut}
            notes.append("Nutrition was printed per serving without a serving size, so it could not be used.")
    elif basis == "not_visible":
        nut = {k: None for k in nut}

    # Plausibility checks: drop values that cannot be right for 100 g / 100 ml.
    for k in ("fat_g", "saturated_fat_g", "trans_fat_g", "carbohydrates_g", "sugars_g", "added_sugars_g",
              "fiber_g", "protein_g", "salt_g"):
        if nut.get(k) is not None and nut[k] > 100:
            notes.append(f"Ignored an impossible value for {k.replace('_g', '')}.")
            nut[k] = None
    if nut.get("energy_kcal") is not None and nut["energy_kcal"] > 950:
        notes.append("Energy value looked like kJ and was converted to kcal.")
        nut["energy_kcal"] = round(nut["energy_kcal"] / 4.184, 1)
    if nut.get("sodium_mg") is not None and nut["sodium_mg"] > 40000:
        nut["sodium_mg"] = None
    if (nut.get("saturated_fat_g") or 0) > (nut.get("fat_g") or 1e9):
        notes.append("Saturated fat was larger than total fat; please check the label.")
    if (nut.get("sugars_g") or 0) > (nut.get("carbohydrates_g") or 1e9):
        notes.append("Sugar was larger than total carbohydrate; please check the label.")

    confidence = raw.get("confidence") if raw.get("confidence") in ("high", "medium", "low") else "medium"
    macros = [nut.get("fat_g"), nut.get("carbohydrates_g"), nut.get("protein_g"), nut.get("energy_kcal")]
    if all(v is not None for v in macros):
        estimate = 9 * macros[0] + 4 * macros[1] + 4 * macros[2]
        if estimate > 0 and abs(estimate - macros[3]) / max(estimate, macros[3]) > 0.35:
            confidence = "low"
            notes.append("Energy does not match the fat/carbohydrate/protein values; some numbers may be misread.")

    category = raw.get("category") if raw.get("category") in CATEGORIES else "other"
    fvn = _clean_number(raw.get("fruit_veg_nuts_percent"))
    return ProductData(
        name=(raw.get("product_name") or "Unnamed product").strip()[:200],
        brand=(raw.get("brand") or None),
        category=category,
        is_liquid=bool(raw.get("is_liquid")) or basis == "per_100ml",
        net_quantity=(raw.get("net_quantity") or None),
        serving_size_g=serving,
        ingredients_text=(raw.get("ingredients_text") or None),
        additive_codes=[str(c)[:20] for c in (raw.get("additive_codes") or [])][:80],
        allergens_declared=[str(a)[:60] for a in (raw.get("allergens_declared") or [])][:30],
        traces=[str(a)[:60] for a in (raw.get("traces") or [])][:30],
        nutrition=Nutrition(**{k: v for k, v in nut.items() if v is not None}),
        fruit_veg_nuts_percent=fvn if fvn is not None and fvn <= 100 else None,
        veg_mark=raw.get("veg_mark") if raw.get("veg_mark") in ("veg", "non_veg") else None,
        source=source,  # type: ignore[arg-type]
        read_by=read_by,  # type: ignore[arg-type]
        extraction_confidence=confidence,
        extraction_notes=notes[:20],
    )


def read_label(ai: AIClient, ocr: OCRReader | None, files: list[bytes]) -> ProductData:
    """AI vision first; offline OCR when no AI is configured or the AI service is down."""
    images = [(prepare_image(f), "image/jpeg") for f in files]
    ocr_ok = bool(ocr and ocr.enabled)
    fallback_note = None
    if ai.enabled:
        try:
            return normalise_extraction(ai.extract_label(images), read_by=ai.provider)
        except AIError as exc:
            # Busy/unavailable/misconfigured AI: fall back to OCR if we can. A refusal
            # (422) or an unreadable image (400) would not be helped by OCR.
            if not ocr_ok or exc.status not in (502, 503, 504):
                raise LabelError(str(exc), exc.status) from exc
            log.warning("AI label reading failed (%s); falling back to OCR.", exc)
            fallback_note = "The AI reader was unavailable, so the label was read with offline text recognition."
    if not ocr_ok:
        raise LabelError("Reading photos isn't available on this server. Type or paste the label text instead.", 503)
    product = normalise_extraction(ocr.extract_label(images), read_by="ocr")  # type: ignore[union-attr]
    if fallback_note:
        product.extraction_notes.insert(0, fallback_note)
    return product


def read_label_text(text: str, name: str | None = None, brand: str | None = None) -> ProductData:
    raw = parse_label_text(text, name=name, brand=brand)
    product = normalise_extraction(raw, source="label_text", read_by="text")
    if not name:
        product.name = "Unnamed product"
    return product
