"""Tests for the label pipeline, the Gemini REST client and Open Food Facts mapping."""
import io
import json
import unittest
from unittest import mock

from PIL import Image

from app.services.gemini import EXTRACTION_SCHEMA, GeminiClient, GeminiError
from app.services.label import LabelError, normalise_extraction, prepare_image
from app.services.openfoodfacts import to_product
from app.services.standards import get_standards

from .fixtures import GOOD_EXTRACTION, OFF_PRODUCT, make_settings

STD = get_standards()


def jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (3000, 1500), (200, 120, 40))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"   # Make
    exif[0x0112] = 6              # Orientation: rotate 90
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


class TestImagePrep(unittest.TestCase):
    def test_downscale_rotate_and_strip_metadata(self):
        out = prepare_image(jpeg_with_exif())
        with Image.open(io.BytesIO(out)) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertLessEqual(max(img.size), 2000)
            self.assertGreater(img.size[1], img.size[0])  # rotated to portrait
            self.assertEqual(len(img.getexif()), 0)

    def test_rejects_non_images(self):
        with self.assertRaises(LabelError) as ctx:
            prepare_image(b"%PDF-1.4 not an image")
        self.assertEqual(ctx.exception.status, 400)


class TestNormaliseExtraction(unittest.TestCase):
    def test_good(self):
        p = normalise_extraction(GOOD_EXTRACTION)
        self.assertEqual(p.source, "label_photo")
        self.assertEqual(p.nutrition.sodium_mg, 1167)
        self.assertAlmostEqual(p.nutrition.salt_g, 2.918, places=2)
        self.assertEqual(p.extraction_confidence, "high")

    def test_per_serving_is_converted(self):
        raw = {**GOOD_EXTRACTION, "nutrition_basis": "per_serving", "serving_size_g": 50,
               "nutrition": {"energy_kcal": 250, "sugars_g": 10, "fat_g": 12, "carbohydrates_g": 30, "protein_g": 4}}
        p = normalise_extraction(raw)
        self.assertEqual(p.nutrition.energy_kcal, 500)
        self.assertEqual(p.nutrition.sugars_g, 20)

    def test_per_serving_without_size_is_dropped(self):
        raw = {**GOOD_EXTRACTION, "nutrition_basis": "per_serving", "serving_size_g": None}
        p = normalise_extraction(raw)
        self.assertIsNone(p.nutrition.energy_kcal)
        self.assertTrue(any("could not be used" in n for n in p.extraction_notes))

    def test_kj_and_impossible_values(self):
        raw = {**GOOD_EXTRACTION, "nutrition": {"energy_kcal": 1787, "fat_g": 150, "sugars_g": 2}}
        p = normalise_extraction(raw)
        self.assertAlmostEqual(p.nutrition.energy_kcal, 427.1, places=1)
        self.assertIsNone(p.nutrition.fat_g)

    def test_mismatched_energy_lowers_confidence(self):
        raw = {**GOOD_EXTRACTION, "nutrition": {"energy_kcal": 100, "fat_g": 30, "carbohydrates_g": 50, "protein_g": 10}}
        self.assertEqual(normalise_extraction(raw).extraction_confidence, "low")

    def test_not_a_label(self):
        with self.assertRaises(LabelError):
            normalise_extraction({"is_food_label": False})

    def test_bad_category_falls_back(self):
        p = normalise_extraction({**GOOD_EXTRACTION, "category": "spaceship"})
        self.assertEqual(p.category, "other")


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def gemini_ok(obj: dict) -> FakeResponse:
    return FakeResponse(200, {"candidates": [{"content": {"parts": [
        {"text": "thinking...", "thought": True},
        {"text": "```json\n" + json.dumps(obj) + "\n```"},
    ]}}]})


class TestGeminiClient(unittest.TestCase):
    def setUp(self):
        self.session = mock.Mock()
        self.client = GeminiClient(make_settings(gemini_model="gemini-test"), session=self.session)

    def test_request_shape(self):
        self.session.post.return_value = gemini_ok(GOOD_EXTRACTION)
        out = self.client.extract_label([(b"\xff\xd8jpeg", "image/jpeg")])
        self.assertEqual(out["product_name"], "Masala instant noodles")
        url = self.session.post.call_args.args[0]
        body = self.session.post.call_args.kwargs["json"]
        headers = self.session.post.call_args.kwargs["headers"]
        self.assertTrue(url.endswith("/models/gemini-test:generateContent"))
        self.assertEqual(headers["x-goog-api-key"], "test-key")
        parts = body["contents"][0]["parts"]
        self.assertEqual(parts[0]["inline_data"]["mime_type"], "image/jpeg")
        self.assertIn("NEVER guess", parts[-1]["text"])
        self.assertEqual(body["generationConfig"]["response_mime_type"], "application/json")
        self.assertEqual(body["generationConfig"]["response_schema"], EXTRACTION_SCHEMA)

    def test_schema_rejection_retries_without_schema(self):
        self.session.post.side_effect = [FakeResponse(400, {"error": {"message": "bad schema"}}), gemini_ok({"ok": 1})]
        self.assertEqual(self.client.extract_label([(b"x", "image/jpeg")]), {"ok": 1})
        second = self.session.post.call_args_list[1].kwargs["json"]
        self.assertNotIn("response_schema", second["generationConfig"])

    def test_quota_maps_to_503(self):
        self.session.post.return_value = FakeResponse(429, {})
        with self.assertRaises(GeminiError) as ctx:
            self.client.explain({"a": 1}, "en")
        self.assertEqual(ctx.exception.status, 503)

    @mock.patch("app.services.gemini.time.sleep")
    def test_server_errors_retry_then_fail(self, _sleep):
        self.session.post.return_value = FakeResponse(503, {})
        with self.assertRaises(GeminiError):
            self.client.explain({"a": 1}, "en")
        self.assertEqual(self.session.post.call_count, 3)

    def test_blocked(self):
        self.session.post.return_value = FakeResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}})
        with self.assertRaises(GeminiError) as ctx:
            self.client.extract_label([(b"x", "image/jpeg")])
        self.assertEqual(ctx.exception.status, 422)

    def test_disabled_without_key(self):
        client = GeminiClient(make_settings(gemini_api_key=""), session=self.session)
        with self.assertRaises(GeminiError):
            client.extract_label([(b"x", "image/jpeg")])
        self.session.post.assert_not_called()


class TestOpenFoodFactsMapping(unittest.TestCase):
    def test_to_product(self):
        p = to_product(OFF_PRODUCT, STD)
        self.assertEqual(p.barcode, "8901234567890")
        self.assertEqual(p.brand, "Crunch Co")
        self.assertEqual(p.category, "chips_namkeen")
        self.assertEqual(p.serving_size_g, 26)
        self.assertEqual(p.nutrition.sodium_mg, 560)
        self.assertEqual(p.nutrition.salt_g, 1.4)
        self.assertFalse(p.is_liquid)
        self.assertEqual(p.traces, ["milk"])

    def test_liquid_and_kj(self):
        raw = {**OFF_PRODUCT, "quantity": "1.25 l", "nutriments": {"energy_100g": 180}, "categories_tags": []}
        p = to_product(raw, STD)
        self.assertTrue(p.is_liquid)
        self.assertAlmostEqual(p.nutrition.energy_kcal, 43.0, places=0)


if __name__ == "__main__":
    unittest.main()
