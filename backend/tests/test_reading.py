"""Label reading without AI (text parser, OCR), the Claude provider, provider
selection, diet checks and the review-first API flow."""
import io
import json
import unittest
from unittest import mock

from PIL import Image, ImageDraw, ImageFont

from app.main import create_app
from app.models import Profile
from app.services import scoring
from app.services.ai import AIError, NullAI, build_ai_client, to_json_schema
from app.services.claude import EXTRACTION_TOOL, ClaudeClient, ClaudeError
from app.services.label import LabelError, read_label, read_label_text
from app.services.label_text import parse_label_text
from app.services.ocr import OCRReader
from app.services.personalize import personalise
from app.services.standards import get_standards

from .asgi_client import ASGIClient
from .fixtures import NOODLES, SAMPLE_LABEL_TEXT, FakeAI, FakeOCR, FakeOFF, make_settings, product

STD = get_standards()


def jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def blank_photo() -> bytes:
    return jpeg(Image.new("RGB", (640, 480), (240, 240, 240)))


class TestLabelTextParser(unittest.TestCase):
    def test_indian_two_column_table(self):
        r = parse_label_text(SAMPLE_LABEL_TEXT)
        n = r["nutrition"]
        self.assertEqual(r["nutrition_basis"], "per_100g")
        self.assertEqual((n["energy_kcal"], n["protein_g"], n["sugars_g"], n["added_sugars_g"]), (427, 8.9, 2.1, 1.0))
        self.assertEqual((n["fat_g"], n["saturated_fat_g"], n["trans_fat_g"], n["sodium_mg"]), (15.7, 7.5, 0.1, 1167))
        self.assertEqual(r["serving_size_g"], 70)
        self.assertEqual(r["net_quantity"], "70 g")
        self.assertEqual(r["allergens_declared"], ["wheat"])
        self.assertEqual(r["traces"], ["milk", "mustard", "soy"])
        self.assertTrue(r["ingredients_text"].startswith("Refined Wheat Flour"))
        self.assertNotIn("NUTRITIONAL", r["ingredients_text"])
        self.assertEqual(r["confidence"], "medium")

    def test_ingredient_numbers_are_not_nutrition(self):
        r = parse_label_text("Ingredients: sugar, salt, emulsifier (322, 471), fat (12%).")
        self.assertEqual(r["nutrition"], {})

    def test_inline_drink_table(self):
        r = parse_label_text("Ingredients: water, sugar.\nNutrition Information per 100 ml: Energy 44 kcal, "
                             "Carbohydrate 10.9 g, of which sugars 10.9 g, Protein 0 g, Fat 0 g, Sodium 10 mg")
        self.assertEqual(r["nutrition_basis"], "per_100ml")
        self.assertTrue(r["is_liquid"])
        self.assertEqual(r["nutrition"]["sugars_g"], 10.9)
        self.assertEqual(r["nutrition"]["sodium_mg"], 10)

    def test_serve_column_first_and_units(self):
        r = parse_label_text("Nutrition facts Per serve (30 g) Per 100 g\nEnergy 627 kJ 2090 kJ\n"
                             "Fat 6 g 20 g\nSodium 0.15 g 0.5 g\nIngredients: oats (60%), sugar, salt.")
        n = r["nutrition"]
        self.assertEqual(n["fat_g"], 20)
        self.assertEqual(n["sodium_mg"], 500)
        self.assertAlmostEqual(n["energy_kcal"], 499.5, places=1)  # 2090 kJ / 4.184
        self.assertEqual(r["serving_size_g"], 30)

    def test_misread_row_is_left_empty(self):
        r = parse_label_text("Nutritional information Per 100 g Per serve (25 g)\nEnergy (kcal) 486 122\n"
                             "Protein (g) Thalk 1.8\nTotal Fat (g) 20.2 5.1\nSodium (mg) 350 88")
        self.assertIsNone(r["nutrition"].get("protein_g"))
        self.assertEqual(r["nutrition"]["fat_g"], 20.2)
        self.assertTrue(any("protein" in n for n in r["notes"]))

    def test_polyunsaturated_is_not_saturated(self):
        r = parse_label_text("Nutrition per 100 g\nPolyunsaturated fat 4.0 g\nSaturated fat 2.0 g\nTotal fat 9 g")
        self.assertEqual(r["nutrition"]["saturated_fat_g"], 2.0)
        self.assertEqual(r["nutrition"]["fat_g"], 9)

    def test_ocr_number_cleanup(self):
        r = parse_label_text("Nutrition per 100g\nTotal Fat (g) 1O,5\nSodium (mg) 1,050")
        self.assertEqual(r["nutrition"]["fat_g"], 10.5)
        self.assertEqual(r["nutrition"]["sodium_mg"], 1050)

    def test_text_entry_end_to_end(self):
        p = read_label_text(SAMPLE_LABEL_TEXT, name="Masala noodles", brand="Test")
        self.assertEqual(p.source, "label_text")
        self.assertEqual(p.read_by, "text")
        self.assertEqual(p.nutrition.salt_g, round(1167 * 2.5 / 1000, 3))
        a = scoring.analyse(p, STD)
        self.assertIn("HIGH SALT", a["front_of_pack_warnings"])
        self.assertIn("635", [x["ins"] for x in a["additives"]])

    def test_not_a_label(self):
        with self.assertRaises(LabelError):
            read_label_text("hello there, this is just some random text")


@unittest.skipUnless(OCRReader().enabled, "Tesseract not installed")
class TestRealOCR(unittest.TestCase):
    def test_reads_a_rendered_label(self):
        lines = ["INGREDIENTS: Whole Wheat Flour, Sugar, Palm Oil, Salt,", "Emulsifier (322), Raising Agent [503(ii)].",
                 "", "NUTRITION INFORMATION Per 100 g", "Energy (kcal) 480", "Protein (g) 8.0", "Carbohydrate (g) 66.0",
                 "Total Sugars (g) 22.0", "Total Fat (g) 20.0", "Saturated Fat (g) 9.5", "Sodium (mg) 400"]
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
        img = Image.new("RGB", (1100, 60 + 46 * len(lines)), (252, 250, 240))
        d = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            d.text((40, 30 + 46 * i), line, font=font, fill=(25, 25, 25))
        p = read_label(NullAI(), OCRReader(), [jpeg(img)])
        self.assertEqual(p.read_by, "ocr")
        n = p.nutrition
        self.assertEqual((n.energy_kcal, n.sugars_g, n.fat_g, n.saturated_fat_g, n.sodium_mg), (480, 22, 20, 9.5, 400))
        self.assertIn("whole wheat flour", p.ingredients_text.lower())


class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def tool_answer(name: str, data: dict, stop: str = "tool_use") -> dict:
    return {"content": [{"type": "tool_use", "id": "t1", "name": name, "input": data}], "stop_reason": stop}


class TestClaudeClient(unittest.TestCase):
    def client(self, *responses):
        session = mock.Mock()
        session.post.side_effect = list(responses)
        return ClaudeClient(make_settings(anthropic_api_key="sk-test", ai_provider="anthropic"), session=session), session

    def test_request_shape_and_answer(self):
        c, session = self.client(FakeResponse(200, tool_answer("record_label", {"is_food_label": True, "category": "other"})))
        out = c.extract_label([(b"jpegbytes", "image/jpeg")])
        self.assertEqual(out["category"], "other")
        args, kwargs = session.post.call_args
        self.assertTrue(args[0].endswith("/v1/messages"))
        self.assertEqual(kwargs["headers"]["x-api-key"], "sk-test")
        self.assertEqual(kwargs["headers"]["anthropic-version"], "2023-06-01")
        body = kwargs["json"]
        self.assertEqual(body["model"], "claude-sonnet-5-5")
        self.assertEqual(body["tool_choice"], {"type": "tool", "name": "record_label"})
        image = body["messages"][0]["content"][0]
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["source"]["type"], "base64")
        self.assertEqual(image["source"]["media_type"], "image/jpeg")

    def test_schema_is_json_schema(self):
        schema = EXTRACTION_TOOL["input_schema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["serving_size_g"]["type"], ["number", "null"])
        self.assertIn("veg_mark", schema["properties"])
        self.assertEqual(to_json_schema({"type": "STRING", "nullable": True, "enum": ["a"]}),
                         {"type": ["string", "null"], "enum": ["a", None]})

    def test_explain(self):
        c, _ = self.client(FakeResponse(200, tool_answer("write_explanation", {"headline": "h", "summary": "s",
                                                                                "key_points": ["a"], "tip": "t"})))
        self.assertEqual(c.explain({"x": 1}, "hi")["headline"], "h")

    def test_refusal(self):
        c, _ = self.client(FakeResponse(200, {"content": [{"type": "text", "text": "no"}], "stop_reason": "refusal"}))
        with self.assertRaises(ClaudeError) as cm:
            c.extract_label([(b"x", "image/jpeg")])
        self.assertEqual(cm.exception.status, 422)

    def test_rate_limit_is_503(self):
        c, _ = self.client(FakeResponse(429, {"error": {"message": "slow down"}}))
        with self.assertRaises(ClaudeError) as cm:
            c.extract_label([(b"x", "image/jpeg")])
        self.assertEqual(cm.exception.status, 503)

    @mock.patch("app.services.claude.time.sleep")
    def test_overloaded_retries_then_succeeds(self, _sleep):
        c, session = self.client(FakeResponse(529, {}), FakeResponse(200, tool_answer("record_label", {"is_food_label": False})))
        self.assertFalse(c.extract_label([(b"x", "image/jpeg")])["is_food_label"])
        self.assertEqual(session.post.call_count, 2)

    def test_bad_key_is_not_retried(self):
        c, session = self.client(FakeResponse(401, {"error": {"message": "invalid x-api-key"}}))
        with self.assertRaises(ClaudeError):
            c.extract_label([(b"x", "image/jpeg")])
        self.assertEqual(session.post.call_count, 1)

    def test_disabled_without_key(self):
        c = ClaudeClient(make_settings(anthropic_api_key=""))
        self.assertFalse(c.enabled)
        with self.assertRaises(AIError):
            c.extract_label([(b"x", "image/jpeg")])


class TestProviderSelection(unittest.TestCase):
    def test_auto_and_explicit(self):
        self.assertEqual(build_ai_client(make_settings(gemini_api_key="", anthropic_api_key="")).provider, "none")
        self.assertEqual(build_ai_client(make_settings(gemini_api_key="g", anthropic_api_key="")).provider, "gemini")
        self.assertEqual(build_ai_client(make_settings(gemini_api_key="g", anthropic_api_key="a")).provider, "claude")
        self.assertEqual(build_ai_client(make_settings(gemini_api_key="g", anthropic_api_key="a",
                                                       ai_provider="gemini")).provider, "gemini")
        self.assertEqual(build_ai_client(make_settings(gemini_api_key="g", ai_provider="none")).provider, "none")
        # Asking for a provider without its key falls back to none rather than failing at request time.
        self.assertEqual(build_ai_client(make_settings(anthropic_api_key="", ai_provider="anthropic")).provider, "none")


class TestDiet(unittest.TestCase):
    def alerts(self, data, diet, **over):
        p = product(data, **over)
        a = scoring.analyse(p, STD)
        return personalise(p, a, Profile(diet=diet), STD)

    def test_vegetarian_gelatin_and_egg(self):
        res = self.alerts({**NOODLES, "ingredients_text": "Sugar, gelatine, egg powder, flavour"}, "vegetarian")
        titles = " | ".join(a["title"] for a in res["alerts"])
        self.assertIn("gelatine", titles)
        self.assertIn("egg", titles)
        self.assertEqual(res["suitability"], "not_suitable")

    def test_eggetarian_accepts_egg_but_flags_brown_mark(self):
        res = self.alerts({**NOODLES, "ingredients_text": "Wheat flour, egg, salt"}, "eggetarian", veg_mark="non_veg")
        self.assertFalse(any(a["level"] == "avoid" for a in res["alerts"]))
        self.assertTrue(any("non-veg" in a["title"] for a in res["alerts"]))

    def test_vegan_dairy_but_not_coconut_milk(self):
        res = self.alerts({**NOODLES, "ingredients_text": "Coconut milk, sugar, milk solids"}, "vegan")
        self.assertTrue(any("milk solids" in a["title"] for a in res["alerts"]))
        res2 = self.alerts({**NOODLES, "ingredients_text": "Coconut milk, sugar, cocoa butter"}, "vegan")
        self.assertFalse(any(a["level"] == "avoid" for a in res2["alerts"]))

    def test_jain_root_vegetables_and_maybe_animal_additives(self):
        res = self.alerts({**NOODLES, "ingredients_text": SAMPLE_LABEL_TEXT.split("NUTRITIONAL")[0]}, "jain")
        self.assertTrue(any("onion" in a["title"] for a in res["alerts"]))
        self.assertEqual(res["suitability"], "not_suitable")
        res2 = self.alerts({**NOODLES, "ingredients_text": "Rice, salt, flavour enhancer (631)"}, "vegetarian")
        cautions = [a for a in res2["alerts"] if a["level"] == "caution"]
        self.assertTrue(any("631" in a["title"] for a in cautions))

    def test_carmine_is_not_vegetarian_but_shellac_is(self):
        res = self.alerts({**NOODLES, "ingredients_text": "Sugar, colour (120), glazing agent (904)"}, "vegetarian")
        avoid = [a["title"] for a in res["alerts"] if a["level"] == "avoid"]
        self.assertTrue(any("Carmine" in t for t in avoid))
        self.assertFalse(any("Shellac" in t for t in avoid))
        vegan = self.alerts({**NOODLES, "ingredients_text": "Sugar, glazing agent (904)"}, "vegan")
        self.assertTrue(any("Shellac" in a["title"] for a in vegan["alerts"] if a["level"] == "avoid"))


class TestReviewFlowAPI(unittest.TestCase):
    def make(self, ai=None, ocr=None):
        self.ai = ai or FakeAI()
        self.ocr = ocr or FakeOCR()
        app = create_app(make_settings(), ai=self.ai, off=FakeOFF(), ocr=self.ocr)
        self.addCleanup(app.state.db.close)
        return ASGIClient(app)

    def test_read_returns_draft_without_report(self):
        c = self.make()
        r = c.post("/api/v1/label/read", files=[("files", ("a.jpg", blank_photo(), "image/jpeg"))])
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["read_by"], "gemini")
        self.assertEqual(d["product"]["name"], "Masala instant noodles")
        self.assertNotIn("report_id", d)
        # The user reviews/edits and then asks for the report.
        draft = {**d["product"], "serving_size_g": 80, "reviewed": True}
        rep = c.post("/api/v1/analyze/product", json={"product": draft, "explain": False}).json()
        self.assertTrue(rep["analysis"]["data_quality"]["reviewed_by_user"])
        self.assertEqual(rep["personal"]["per_serving"]["serving_size"], 80)

    def test_ai_outage_falls_back_to_ocr(self):
        c = self.make(ai=FakeAI(error=AIError("busy", 503)))
        d = c.post("/api/v1/label/read", files=[("files", ("a.jpg", blank_photo(), "image/jpeg"))]).json()
        self.assertEqual(d["read_by"], "ocr")
        self.assertIn("offline text recognition", d["notes"][0])
        self.assertEqual(self.ocr.calls, 1)

    def test_no_ai_uses_ocr_and_health_says_so(self):
        c = self.make(ai=NullAI())
        h = c.get("/api/v1/health").json()
        self.assertEqual(h["label_reader"], "ocr")
        self.assertTrue(h["label_reading_enabled"])
        d = c.post("/api/v1/label/read", files=[("files", ("a.jpg", blank_photo(), "image/jpeg"))]).json()
        self.assertEqual(d["product"]["nutrition"]["sodium_mg"], 1167)

    def test_nothing_available_is_503(self):
        c = self.make(ai=NullAI(), ocr=FakeOCR(enabled=False))
        r = c.post("/api/v1/label/read", files=[("files", ("a.jpg", blank_photo(), "image/jpeg"))])
        self.assertEqual(r.status_code, 503)
        self.assertIn("Type or paste", r.json()["error"])

    def test_refusal_is_not_hidden_by_ocr(self):
        c = self.make(ai=FakeAI(error=AIError("declined", 422)))
        r = c.post("/api/v1/label/read", files=[("files", ("a.jpg", blank_photo(), "image/jpeg"))])
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.ocr.calls, 0)

    def test_label_text_endpoint(self):
        c = self.make()
        r = c.post("/api/v1/label/text", json={"text": SAMPLE_LABEL_TEXT, "name": "Masala noodles"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["product"]["category"], "instant_noodles")  # guessed from the name
        self.assertEqual(d["product"]["source"], "label_text")
        self.assertEqual(c.post("/api/v1/label/text", json={"text": "short"}).status_code, 422)
        self.assertEqual(c.post("/api/v1/label/text", json={"text": "random words that are not a label"}).status_code, 422)
        bad = c.post("/api/v1/label/text", data="{nope", headers={"content-type": "application/json"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("JSON", bad.json()["error"])

    def test_additive_search_and_api_errors_are_json(self):
        c = self.make()
        res = c.get("/api/v1/additives", params={"q": "benzoate"}).json()["results"]
        self.assertTrue({"211", "212"} <= {a["ins"] for a in res})
        self.assertEqual(c.get("/api/v1/additives", params={"q": "E211"}).json()["results"][0]["ins"], "211")
        nf = c.get("/api/v1/nope")
        self.assertEqual(nf.status_code, 404)
        self.assertIn("error", nf.json())
        wrong = c.get("/api/v1/analyze/product")
        self.assertEqual(wrong.status_code, 405)
        self.assertIn("error", wrong.json())
        self.assertEqual(c.get("/api/v1/health").headers["cache-control"], "no-store")

    def test_diet_profile_through_api(self):
        c = self.make()
        prof = json.dumps({"diet": "jain"})
        jain_check = {**NOODLES, "ingredients_text": "Rice flour, salt, garlic powder, chilli"}
        rid = c.post("/api/v1/analyze/product", json={"product": jain_check, "explain": False}).json()["report_id"]
        rep = c.get(f"/api/v1/reports/{rid}", params={"profile": prof, "explain": "false"}).json()
        self.assertEqual(rep["personal"]["diet"], "jain")
        self.assertEqual(rep["personal"]["suitability"], "not_suitable")

    def test_size_limits_answer_in_json(self):
        c = self.make()
        big_text = c.post("/api/v1/label/text", json={"text": "Ingredients: " + "sugar, " * 50000})
        self.assertEqual(big_text.status_code, 413)
        self.assertIn("error", big_text.json())
        app = create_app(make_settings(max_upload_mb=1, max_images=1), ai=FakeAI(), off=FakeOFF(), ocr=FakeOCR())
        self.addCleanup(app.state.db.close)
        huge = ASGIClient(app).post("/api/v1/label/read", files=[("files", ("a.jpg", b"0" * (3 * 1024 * 1024), "image/jpeg"))])
        self.assertEqual(huge.status_code, 413)
        self.assertEqual(huge.json()["error"], "Upload too large.")

    def test_malformed_upload_is_400(self):
        c = self.make()
        r = c.post("/api/v1/label/read", data=b"\x00" * 100,
                   headers={"content-type": "multipart/form-data; boundary=xyz"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("multipart", r.json()["error"])

    def test_webm_video(self):
        c = self.make()
        rid = c.post("/api/v1/analyze/product", json={"product": NOODLES, "explain": False}).json()["report_id"]
        r = c.get(f"/api/v1/reports/{rid}/video.webm", params={"per_week": 3, "years": 2})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "video/webm")
        self.assertEqual(r.content[:4], b"\x1a\x45\xdf\xa3")  # EBML (Matroska/WebM) header


if __name__ == "__main__":
    unittest.main()
