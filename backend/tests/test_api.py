"""End-to-end API tests with fake Gemini and Open Food Facts clients."""
import io
import json
import unittest

from PIL import Image

from app.main import create_app

from .asgi_client import ASGIClient as TestClient
from .fixtures import COLA, DAHI, NOODLES, OFF_PRODUCT, FakeGemini, FakeOCR, FakeOFF, make_settings


def photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (240, 240, 240)).save(buf, format="JPEG")
    return buf.getvalue()


class APITestCase(unittest.TestCase):
    def make_client(self, **settings) -> TestClient:
        self.gemini = FakeGemini()
        self.ocr = FakeOCR()
        self.off = FakeOFF({OFF_PRODUCT["code"]: OFF_PRODUCT})
        app = create_app(make_settings(**settings), ai=self.gemini, off=self.off, ocr=self.ocr)
        self.addCleanup(app.state.db.close)
        return TestClient(app)

    def setUp(self):
        self.client = self.make_client()


class TestBasics(APITestCase):
    def test_health_and_meta(self):
        h = self.client.get("/api/v1/health").json()
        self.assertEqual(h["status"], "ok")
        m = self.client.get("/api/v1/meta").json()
        self.assertIn("instant_noodles", m["categories"])
        self.assertIn("diabetes", m["conditions"])
        self.assertIn("milk", m["allergen_groups"])

    def test_additive_lookup(self):
        self.assertEqual(self.client.get("/api/v1/additives/E621").json()["ins"], "621")
        self.assertEqual(self.client.get("/api/v1/additives/9999").status_code, 404)

    def test_security_headers_and_web(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.client.get("/r/abcdefgh").status_code, 200)


class TestAnalyze(APITestCase):
    def test_label_photo_flow(self):
        files = [("files", ("ingredients.jpg", photo(), "image/jpeg")), ("files", ("nutrition.jpg", photo(), "image/jpeg"))]
        r = self.client.post("/api/v1/analyze/label", files=files,
                             data={"profile": json.dumps({"conditions": ["hypertension"], "allergies": ["milk"]})})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(self.gemini.extract_calls, 1)
        self.assertEqual(d["product"]["source"], "label_photo")
        self.assertEqual(d["analysis"]["grade"], "D")
        self.assertEqual(d["personal"]["suitability"], "not_suitable")
        self.assertEqual(d["explanation"]["generated_by"], "gemini")
        self.assertEqual(d["alternatives"]["from_open_food_facts"][0]["name"], "Millet noodles")
        self.assertTrue(d["alternatives"]["attribution"])
        self.assertIn("disclaimer", d)

        # The report can be re-opened later with a different profile.
        rid = d["report_id"]
        again = self.client.get(f"/api/v1/reports/{rid}").json()
        self.assertEqual(again["analysis"]["score"], d["analysis"]["score"])
        self.assertEqual(again["personal"]["suitability"], "suitable")  # no profile given this time
        # explanation is cached: same facts for same profile -> no new Gemini call
        calls = self.gemini.explain_calls
        self.client.get(f"/api/v1/reports/{rid}")
        self.assertEqual(self.gemini.explain_calls, calls)

    def test_label_validation(self):
        r = self.client.post("/api/v1/analyze/label", files=[("files", ("a.txt", b"hello", "text/plain"))])
        self.assertEqual(r.status_code, 400)
        self.assertIn("readable image", r.json()["error"])
        many = [("files", (f"{i}.jpg", photo(), "image/jpeg")) for i in range(5)]
        self.assertEqual(self.client.post("/api/v1/analyze/label", files=many).status_code, 400)
        bad_profile = self.client.post("/api/v1/analyze/label", files=[("files", ("a.jpg", photo(), "image/jpeg"))],
                                       data={"profile": "{not json"})
        self.assertEqual(bad_profile.status_code, 400)

    def test_upload_size_limit(self):
        client = self.make_client(max_upload_mb=1)
        big = b"\xff\xd8" + b"0" * (1024 * 1024 + 10)
        r = client.post("/api/v1/analyze/label", files=[("files", ("big.jpg", big, "image/jpeg"))])
        self.assertEqual(r.status_code, 413)

    def test_not_a_label(self):
        self.gemini.extraction = {"is_food_label": False}
        r = self.client.post("/api/v1/analyze/label", files=[("files", ("a.jpg", photo(), "image/jpeg"))])
        self.assertEqual(r.status_code, 422)

    def test_manual_product(self):
        r = self.client.post("/api/v1/analyze/product", json={"product": COLA, "explain": False,
                                                                "profile": {"age_group": "child", "language": "hi"}})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["analysis"]["grade"], "E")
        self.assertEqual(d["explanation"]["generated_by"], "template")
        self.assertIn("स्कोर", d["explanation"]["headline"])
        self.assertEqual(self.gemini.explain_calls, 0)

    def test_invalid_product(self):
        bad = {**DAHI, "nutrition": {"fat_g": -3}}
        r = self.client.post("/api/v1/analyze/product", json={"product": bad})
        self.assertEqual(r.status_code, 422)
        self.assertIn("error", r.json())


class TestBarcode(APITestCase):
    def test_found_then_served_from_db(self):
        r = self.client.get(f"/api/v1/products/barcode/{OFF_PRODUCT['code']}?explain=false")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["product"]["category"], "chips_namkeen")
        self.client.get(f"/api/v1/products/barcode/{OFF_PRODUCT['code']}?explain=false")
        self.assertEqual(self.off.lookups, [OFF_PRODUCT["code"]])  # second time from our database

    def test_not_found_and_invalid(self):
        self.assertEqual(self.client.get("/api/v1/products/barcode/8900000000999").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/products/barcode/12ab").status_code, 400)

    def test_scans_feed_alternatives(self):
        # A good noodle product scanned by someone else shows up as an alternative.
        better = {**NOODLES, "name": "Millet noodles", "nutrition": {**NOODLES["nutrition"], "saturated_fat_g": 1,
                                                                      "sodium_mg": 300, "fiber_g": 8}}
        self.gemini.extraction = {**self.gemini.extraction, "product_name": "Millet noodles",
                                  "nutrition": better["nutrition"]}
        self.client.post("/api/v1/analyze/label", files=[("files", ("a.jpg", photo(), "image/jpeg"))])
        self.gemini.extraction = FakeGemini().extraction
        d = self.client.post("/api/v1/analyze/label", files=[("files", ("a.jpg", photo(), "image/jpeg"))]).json()
        names = [p["name"] for p in d["alternatives"]["from_scans"]]
        self.assertIn("Millet noodles", names)


class TestSimulationAndVideo(APITestCase):
    def setUp(self):
        super().setUp()
        self.rid = self.client.post("/api/v1/analyze/product", json={"product": NOODLES, "explain": False}).json()["report_id"]

    def test_simulation(self):
        s = self.client.get(f"/api/v1/reports/{self.rid}/simulation?per_week=14&years=5").json()
        self.assertEqual(s["years"], 5)
        self.assertEqual(len(s["timeline"]), 6)
        self.assertTrue(s["findings"])
        self.assertIn("not a prediction", s["model_note"])

    def test_video(self):
        r = self.client.get(f"/api/v1/reports/{self.rid}/video.mp4?per_week=7&years=3")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "video/mp4")
        self.assertIn("inline", r.headers["content-disposition"])
        self.assertEqual(r.content[4:8], b"ftyp")

    def test_bad_ids_and_params(self):
        self.assertEqual(self.client.get("/api/v1/reports/nope!!").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/reports/abcdefghijk").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/reports/{self.rid}/simulation?years=99").status_code, 422)


class TestRateLimit(unittest.TestCase):
    def test_ai_limit(self):
        app = create_app(make_settings(rate_ai_per_min=2), ai=FakeGemini(), off=FakeOFF(), ocr=FakeOCR())
        self.addCleanup(app.state.db.close)
        client = TestClient(app)
        files = [("files", ("a.jpg", photo(), "image/jpeg"))]
        codes = [client.post("/api/v1/analyze/label", files=files).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        r = client.post("/api/v1/analyze/label", files=files)
        self.assertIn("Retry-After", r.headers)
        # A different client IP is not affected.
        r2 = client.post("/api/v1/analyze/label", files=files, headers={"X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(r2.status_code, 200)


if __name__ == "__main__":
    unittest.main()
