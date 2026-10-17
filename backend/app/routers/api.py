"""HTTP API (version 1). All routes are under /api/v1.

Endpoints
  GET  /api/v1/health                      liveness + what is enabled
  GET  /api/v1/meta                        categories, conditions, diets, allergen groups, data versions
  GET  /api/v1/additives?q=...             search the additive reference list
  GET  /api/v1/additives/{code}            one additive (INS / E number)
  POST /api/v1/label/read                  photos  -> product draft to review (no report)
  POST /api/v1/label/text                  label text -> product draft to review
  POST /api/v1/analyze/label               photos  -> full report (one step)
  POST /api/v1/analyze/product             product JSON (reviewed draft or manual entry) -> report
  GET  /api/v1/products/barcode/{barcode}  barcode -> report (our database, then Open Food Facts)
  GET  /api/v1/reports/{id}                saved report, re-personalised with ?profile=
  GET  /api/v1/reports/{id}/simulation     long-term illustration data
  GET  /api/v1/reports/{id}/video.mp4|webm long-term illustration video
"""
from __future__ import annotations

import logging
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

try:
    from python_multipart.exceptions import FormParserError
except ImportError:  # older python-multipart releases
    from multipart.exceptions import FormParserError  # type: ignore[no-redef]
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

from ..models import CATEGORIES, AnalyzeProductRequest, Condition, Diet, LabelTextRequest, Profile, ProductData
from ..services import scoring, simulation, video
from ..services.label import read_label, read_label_text
from ..services.openfoodfacts import OpenFoodFactsError, guess_category, to_product

log = logging.getLogger("labelcheck.api")

BARCODE_RE = re.compile(r"^\d{6,14}$")
REPORT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
AGE_RE = re.compile(r"^(child|teen|adult|senior)$")
APP_VERSION = "1.1.0"
JSON_LIMIT = 256 * 1024

M = TypeVar("M", bound=BaseModel)


class InputError(Exception):
    """Invalid request input (422)."""


# ---- helpers -------------------------------------------------------------
def describe_validation(exc: ValidationError) -> str:
    errors = exc.errors()
    first = errors[0] if errors else {}
    where = ".".join(str(p) for p in first.get("loc", []))
    return f"Invalid input{(' at ' + where) if where else ''}: {first.get('msg', 'check your request')}"


async def read_body(request: Request, limit: int = JSON_LIMIT) -> bytes:
    """Reads the request body, refusing anything larger than `limit` bytes."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="Request too large.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="Request too large.")
        chunks.append(chunk)
    return b"".join(chunks)


async def json_body(request: Request, model: type[M]) -> M:
    raw = await read_body(request)
    if not raw:
        raise InputError("Send a JSON body.")
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        if any(e.get("type") == "json_invalid" for e in exc.errors()):
            raise InputError("The request body is not valid JSON.") from exc
        raise InputError(describe_validation(exc)) from exc


def q_bool(request: Request, name: str, default: bool) -> bool:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def q_number(request: Request, name: str, default: float, lo: float, hi: float, integer: bool = False) -> float:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        raise InputError(f"Invalid input at {name}: must be a number.")
    if not lo <= value <= hi:
        raise InputError(f"Invalid input at {name}: must be between {lo:g} and {hi:g}.")
    return value


def q_age(request: Request) -> str:
    raw = request.query_params.get("age_group", "adult")
    if not AGE_RE.match(raw):
        raise InputError("Invalid input at age_group: use child, teen, adult or senior.")
    return raw


def client_ip(request: Request) -> str:
    settings = request.app.state.settings
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, bucket: str) -> None:
    s = request.app.state.settings
    limits = {
        "ai": [(s.rate_ai_per_min, 60), (s.rate_ai_per_day, 86400)],
        "video": [(s.rate_video_per_min, 60)],
        "default": [(s.rate_default_per_min, 60)],
    }[bucket]
    wait = request.app.state.limiter.check(client_ip(request), bucket, limits)
    if wait is not None:
        raise HTTPException(status_code=429, detail=f"Too many requests. Please wait {wait} seconds.",
                            headers={"Retry-After": str(wait)})


def parse_profile(raw: str | None) -> Profile:
    if not raw:
        return Profile()
    try:
        return Profile.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid profile.")


def check_report_id(report_id: str) -> None:
    if not REPORT_ID_RE.match(report_id):
        raise HTTPException(status_code=404, detail="Report not found.")


async def read_photos(request: Request) -> tuple[list[bytes], Any]:
    """Reads 1..MAX_IMAGES photos from a multipart form. Returns (photos, form)."""
    st = request.app.state
    limit = st.settings.max_upload_mb * 1024 * 1024
    try:
        form = await request.form(max_files=st.settings.max_images, max_fields=10)
    except FormParserError as exc:  # malformed multipart body
        raise HTTPException(status_code=400, detail="Couldn't read the upload. Send the photos as a multipart form "
                                                    "with the field name 'files'.") from exc
    try:
        files = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
        if not files:
            raise HTTPException(status_code=400, detail="Add at least one photo.")
        blobs = []
        for f in files:
            data = await f.read(limit + 1)
            if len(data) > limit:
                raise HTTPException(status_code=413, detail=f"Each photo must be under {st.settings.max_upload_mb} MB.")
            if not data:
                raise HTTPException(status_code=400, detail="One of the photos is empty.")
            blobs.append(data)
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        return blobs, fields
    finally:
        await form.close()


def _draft_response(request: Request, product: ProductData) -> dict[str, Any]:
    st = request.app.state
    if product.category == "other" and product.name and product.name != "Unnamed product":
        product.category = guess_category([], product.name, st.standards)  # type: ignore[assignment]
    return {"product": product.model_dump(), "read_by": product.read_by,
            "confidence": product.extraction_confidence, "notes": product.extraction_notes}


# ---- routes --------------------------------------------------------------
async def health(request: Request) -> JSONResponse:
    st = request.app.state
    reader = st.ai.provider if st.ai.enabled else ("ocr" if st.ocr.enabled else None)
    return JSONResponse({
        "status": "ok", "version": APP_VERSION,
        "label_reading_enabled": reader is not None, "label_reader": reader,
        "ai_provider": st.ai.provider if st.ai.enabled else None,
        "model": st.ai.model if st.ai.enabled else None,
        "ocr_fallback": st.ocr.enabled,
        "db": await run_in_threadpool(st.db.stats),
    })


async def meta(request: Request) -> JSONResponse:
    st = request.app.state
    std = st.standards
    return JSONResponse({
        "version": APP_VERSION,
        "scoring_version": scoring.SCORING_VERSION,
        "categories": {c: std.swaps[c]["label"] for c in CATEGORIES},
        "conditions": list(Condition.__args__),  # type: ignore[attr-defined]
        "diets": list(Diet.__args__),  # type: ignore[attr-defined]
        "allergen_groups": list(std.standards["allergens"]["groups"].keys()),
        "data": std.meta,
        "label_reading_enabled": st.ai.enabled or st.ocr.enabled,
    })


async def additive(request: Request) -> JSONResponse:
    entry = request.app.state.standards.additive(request.path_params["code"])
    if not entry:
        raise HTTPException(status_code=404, detail="Additive not in the reference list.")
    return JSONResponse(entry)


async def additive_search(request: Request) -> JSONResponse:
    q = (request.query_params.get("q") or "").strip().lower()[:60]
    std = request.app.state.standards
    if not q:
        raise InputError("Invalid input at q: type a name or INS / E number.")
    exact = std.additive(q) if re.search(r"\d{3}", q) else None
    results = [exact] if exact else []
    for entry in std.additives.values():
        if len(results) >= 20:
            break
        names = [entry["name"].lower(), *[a.lower() for a in entry.get("aliases", [])]]
        if entry is not exact and any(q in n for n in names):
            results.append(entry)
    return JSONResponse({"query": q, "results": results})


async def label_read(request: Request) -> JSONResponse:
    st = request.app.state
    rate_limit(request, "ai")
    blobs, _ = await read_photos(request)
    product = await run_in_threadpool(read_label, st.ai, st.ocr, blobs)
    return JSONResponse(_draft_response(request, product))


async def label_text(request: Request) -> JSONResponse:
    rate_limit(request, "default")
    body = await json_body(request, LabelTextRequest)
    product = await run_in_threadpool(read_label_text, body.text, body.name, body.brand)
    return JSONResponse(_draft_response(request, product))


async def analyze_label(request: Request) -> JSONResponse:
    st = request.app.state
    rate_limit(request, "ai")
    blobs, fields = await read_photos(request)
    prof = parse_profile(fields.get("profile"))
    explain = str(fields.get("explain", "true")).lower() not in ("0", "false", "no", "off")
    product = await run_in_threadpool(read_label, st.ai, st.ocr, blobs)
    if product.category == "other" and product.name != "Unnamed product":
        product.category = guess_category([], product.name, st.standards)  # type: ignore[assignment]
    return JSONResponse(await run_in_threadpool(st.reports.create, product, prof, explain))


async def analyze_product(request: Request) -> JSONResponse:
    st = request.app.state
    body = await json_body(request, AnalyzeProductRequest)
    rate_limit(request, "ai" if body.explain and st.ai.enabled else "default")
    return JSONResponse(await run_in_threadpool(st.reports.create, body.product, body.profile, body.explain))


async def by_barcode(request: Request) -> JSONResponse:
    st = request.app.state
    rate_limit(request, "default")
    barcode = request.path_params["barcode"]
    if not BARCODE_RE.match(barcode):
        raise HTTPException(status_code=400, detail="A barcode has 6 to 14 digits.")
    prof = parse_profile(request.query_params.get("profile"))
    explain = q_bool(request, "explain", True)

    def work() -> dict[str, Any]:
        stored = st.db.get_product_by_barcode(barcode)
        if stored:
            product = ProductData.model_validate(stored)
        else:
            raw = st.off.lookup(barcode)
            if not raw:
                raise HTTPException(status_code=404, detail="Product not found. Photograph the label instead — "
                                                            "it will be added for everyone.")
            product = to_product(raw, st.standards)
        return st.reports.create(product, prof, explain)

    try:
        return JSONResponse(await run_in_threadpool(work))
    except OpenFoodFactsError:
        raise HTTPException(status_code=503, detail="Barcode lookup is temporarily unavailable. "
                                                    "Try the label photo instead.")


async def get_report(request: Request) -> JSONResponse:
    report_id = request.path_params["report_id"]
    check_report_id(report_id)
    rate_limit(request, "default")
    prof = parse_profile(request.query_params.get("profile"))
    report = await run_in_threadpool(request.app.state.reports.load, report_id, prof, q_bool(request, "explain", True))
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    return JSONResponse(report)


def _simulation_inputs(request: Request, min_per_week: float):
    report_id = request.path_params["report_id"]
    check_report_id(report_id)
    per_week = q_number(request, "per_week", 7, min_per_week, 35)
    years = int(q_number(request, "years", 10, 1, 30, integer=True))
    age_group = q_age(request)
    st = request.app.state
    row = st.db.get_report(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found.")
    product = ProductData.model_validate(row["product"])
    analysis = scoring.analyse(product, st.standards)
    sim = simulation.simulate(product, analysis, st.standards, per_week, years, age_group)
    return report_id, product, sim, age_group


async def get_simulation(request: Request) -> JSONResponse:
    rate_limit(request, "default")
    _, _, sim, _ = await run_in_threadpool(_simulation_inputs, request, 0)
    return JSONResponse(sim)


async def get_video(request: Request) -> FileResponse:
    fmt = request.path_params["fmt"]
    if fmt not in video.FORMATS:
        raise HTTPException(status_code=404, detail="Video format not available. Use .mp4 or .webm.")
    st = request.app.state
    report_id, product, sim, age_group = await run_in_threadpool(_simulation_inputs, request, 0.5)
    key = video.video_cache_key(report_id, sim, age_group)
    path = video.video_path(st.settings.video_dir, key, fmt)
    if not path.exists():
        rate_limit(request, "video")  # only renders count against the limit
        swaps = (st.standards.swaps.get(product.category) or st.standards.swaps["other"])["swaps"]
        try:
            path = await run_in_threadpool(video.get_or_render, st.settings.video_dir, key, sim, product.name,
                                           swaps[0]["name"] if swaps else None, fmt)
        except (OSError, RuntimeError) as exc:
            log.error("Video render failed (%s): %s", fmt, exc)
            raise HTTPException(status_code=503, detail="The video could not be made right now.")
    return FileResponse(path, media_type=video.FORMATS[fmt]["media_type"], filename=f"labelcheck-{report_id}.{fmt}",
                        content_disposition_type="inline", headers={"Cache-Control": "public, max-age=86400"})


v1_routes = [
    Route("/health", health, methods=["GET"]),
    Route("/meta", meta, methods=["GET"]),
    Route("/additives", additive_search, methods=["GET"]),
    Route("/additives/{code}", additive, methods=["GET"]),
    Route("/label/read", label_read, methods=["POST"]),
    Route("/label/text", label_text, methods=["POST"]),
    Route("/analyze/label", analyze_label, methods=["POST"]),
    Route("/analyze/product", analyze_product, methods=["POST"]),
    Route("/products/barcode/{barcode}", by_barcode, methods=["GET"]),
    Route("/reports/{report_id}", get_report, methods=["GET"]),
    Route("/reports/{report_id}/simulation", get_simulation, methods=["GET"]),
    Route("/reports/{report_id}/video.{fmt}", get_video, methods=["GET"]),
]
# Mounted as its own sub-app so that, under /api, a wrong method gets 405 and an
# unknown path gets a JSON 404 (never the web app's HTML).
routes = [Mount("/api/v1", routes=v1_routes)]
