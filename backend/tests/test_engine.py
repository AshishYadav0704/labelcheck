"""Unit tests for the rule engine: ingredient parsing, Nutri-Score, scoring,
personalisation and the long-term simulation."""
import unittest

from app.models import Nutrition, Profile
from app.services import nutriscore, scoring, simulation
from app.services.ingredients import analyse_ingredients, find_additives
from app.services.personalize import personalise
from app.services.standards import get_standards, normalise_ins

from .fixtures import BROMATE_BREAD, COLA, DAHI, NOODLES, product

STD = get_standards()


class TestStandardsData(unittest.TestCase):
    def test_every_additive_entry_is_complete(self):
        required = {"ins", "name", "function", "concern", "note", "fssai", "at_risk", "regulatory", "adi_source"}
        for code, entry in STD.additives.items():
            self.assertTrue(required <= entry.keys(), f"{code} missing {required - entry.keys()}")
            self.assertIn(entry["concern"], {"none", "low", "moderate", "high"})
            self.assertTrue(entry["adi"] is None or entry["adi"] > 0, code)

    def test_health_links_have_sources(self):
        for link in STD.health_links.values():
            self.assertTrue(link["url"].startswith("https://"))
            self.assertIn(link["evidence"], {"strong", "moderate", "limited"})

    def test_every_category_has_swaps(self):
        from app.models import CATEGORIES
        for cat in CATEGORIES:
            self.assertIn(cat, STD.swaps)
            self.assertTrue(STD.swaps[cat]["swaps"])


class TestIngredients(unittest.TestCase):
    def test_normalise_codes(self):
        self.assertEqual(normalise_ins("E 330"), "330")
        self.assertEqual(normalise_ins("INS150d"), "150d")
        self.assertEqual(normalise_ins("(471)"), "471")
        self.assertEqual(normalise_ins("e1422"), "1422")
        self.assertIsNone(normalise_ins("vitamin"))

    def test_finds_codes_in_all_label_styles(self):
        text = ("emulsifiers (322, 471), acidity regulators (500 (ii), 501 (i)), ins 621, e-330, "
                "colour [150d], sweetener: sucralose. tomato paste (28%), salt (2.5 g)")
        found, unknown = find_additives(text, [], STD)
        codes = {a["ins"] for a in found}
        self.assertTrue({"322", "471", "500", "501", "621", "330", "150d", "955"} <= codes, codes)
        self.assertEqual(unknown, [])

    def test_quantities_are_not_mistaken_for_codes(self):
        found, _ = find_additives("sugar (100 g), milk solids (102 mg)", [], STD)
        self.assertEqual(found, [])

    def test_unknown_prefixed_codes_are_reported(self):
        _, unknown = find_additives("stabiliser (ins 9999)", [], STD)
        self.assertEqual(unknown, ["9999"])

    def test_allergens_and_traces(self):
        ing = analyse_ingredients(product(NOODLES), STD)
        self.assertIn("gluten", ing.allergens)
        self.assertIn("peanut", ing.allergens)  # 'groundnut'
        self.assertEqual(ing.traces, ["milk", "mustard", "soy"])

    def test_allergen_false_friends(self):
        p = product(DAHI, ingredients_text="coconut milk, cocoa butter, maltodextrin, buckwheat")
        ing = analyse_ingredients(p, STD)
        self.assertNotIn("milk", ing.allergens)
        self.assertNotIn("gluten", ing.allergens)

    def test_flags(self):
        p = product(NOODLES, ingredients_text="maida, hydrogenated vegetable fat (vanaspati), sugar, caffeine")
        ids = {f["id"] for f in analyse_ingredients(p, STD).flags}
        self.assertEqual(ids, {"refined_flour", "trans_fat_source", "added_sugar", "caffeine"})

    def test_no_added_sugar_is_not_flagged(self):
        p = product(DAHI, ingredients_text="milk, no added sugar")
        ids = {f["id"] for f in analyse_ingredients(p, STD).flags}
        self.assertNotIn("added_sugar", ids)

    def test_nova(self):
        self.assertEqual(analyse_ingredients(product(NOODLES), STD).nova_group, 4)
        self.assertEqual(analyse_ingredients(product(DAHI), STD).nova_group, 1)
        chips = product(DAHI, ingredients_text="potato, sunflower oil, salt")
        self.assertEqual(analyse_ingredients(chips, STD).nova_group, 3)
        oil = product(DAHI, ingredients_text="refined groundnut oil", ingredients=["refined groundnut oil"])
        self.assertEqual(analyse_ingredients(oil, STD).nova_group, 2)
        self.assertIsNone(analyse_ingredients(product(DAHI, ingredients_text=None), STD).nova_group)


class TestNutriScore(unittest.TestCase):
    def test_food_points(self):
        n = Nutrition(energy_kcal=427, sugars_g=2.1, saturated_fat_g=7.5, sodium_mg=1167, fiber_g=2.3, protein_g=8.9)
        ns = nutriscore.compute(n, beverage=False, fruit_veg_nuts_percent=None)
        # energy 1787 kJ -> 5, sugars 0, sat fat 7, sodium 10 => N=22; fibre 2 ; protein ignored (N>=11)
        self.assertEqual(ns.negative, {"energy": 5, "sugars": 0, "saturated_fat": 7, "sodium": 10})
        self.assertEqual(ns.points, 20)
        self.assertEqual(ns.grade, "E")

    def test_protein_counts_when_negative_is_low(self):
        n = Nutrition(energy_kcal=62, sugars_g=4.6, saturated_fat_g=2.0, sodium_mg=45, protein_g=3.6)
        ns = nutriscore.compute(n, beverage=False, fruit_veg_nuts_percent=None)
        self.assertEqual(ns.points, 0)  # N=2 (sugar 1, sat fat 1) minus protein 2
        self.assertEqual(ns.grade, "B")

    def test_beverage(self):
        n = Nutrition(energy_kcal=44, sugars_g=10.9, saturated_fat_g=0, sodium_mg=10)
        ns = nutriscore.compute(n, beverage=True, fruit_veg_nuts_percent=None)
        self.assertEqual(ns.negative["energy"], 7)   # 184 kJ
        self.assertEqual(ns.negative["sugars"], 8)
        self.assertEqual(ns.grade, "E")
        water = nutriscore.compute(Nutrition(energy_kcal=0, sugars_g=0, saturated_fat_g=0, sodium_mg=0), True, None, is_water=True)
        self.assertEqual(water.grade, "A")

    def test_incomplete(self):
        ns = nutriscore.compute(Nutrition(energy_kcal=100), beverage=False, fruit_veg_nuts_percent=None)
        self.assertIsNone(ns.grade)
        self.assertFalse(ns.complete)

    def test_salt_sodium_conversion(self):
        self.assertAlmostEqual(Nutrition(sodium_mg=400).salt_g, 1.0)
        self.assertAlmostEqual(Nutrition(salt_g=2.5).sodium_mg, 1000)


class TestScoring(unittest.TestCase):
    def test_noodles(self):
        a = scoring.analyse(product(NOODLES), STD)
        self.assertEqual(a["grade"], "D")
        self.assertEqual(a["front_of_pack_warnings"], ["HIGH SATURATED FAT", "HIGH SALT"])
        self.assertEqual(a["additives"][0]["ins"], "319")  # most concerning first
        risk_ids = {r["id"] for r in a["health_risks"]}
        self.assertTrue({"salt", "saturated_fat", "ultra_processed", "low_fibre"} <= risk_ids)
        self.assertAlmostEqual(a["per_serving"]["percent_of_daily_limit"]["salt_g"], 40.8, places=1)

    def test_cola_is_e(self):
        a = scoring.analyse(product(COLA), STD)
        self.assertEqual(a["grade"], "E")
        self.assertIn("SWEETENED BEVERAGE", a["front_of_pack_warnings"])
        self.assertIn("sugary_drink", {r["id"] for r in a["health_risks"]})

    def test_dahi_is_a(self):
        a = scoring.analyse(product(DAHI), STD)
        self.assertEqual(a["grade"], "A")
        self.assertIn("Minimally processed.", a["positives"])
        self.assertEqual(a["health_risks"], [])

    def test_banned_additive_caps_score(self):
        a = scoring.analyse(product(BROMATE_BREAD), STD)
        self.assertLessEqual(a["score"], 10)
        self.assertTrue(any("banned in India" in p["reason"] for p in a["breakdown"]["penalties"]))

    def test_score_is_deterministic_and_bounded(self):
        for data in (NOODLES, COLA, DAHI, BROMATE_BREAD):
            a1 = scoring.analyse(product(data), STD)
            a2 = scoring.analyse(product(data), STD)
            self.assertEqual(a1, a2)
            self.assertTrue(0 <= a1["score"] <= 100)

    def test_child_limits_are_lower(self):
        adult = scoring.daily_limits(STD, "adult")
        child = scoring.daily_limits(STD, "child")
        self.assertLess(child["salt_g"]["limit"], adult["salt_g"]["limit"])


class TestPersonalise(unittest.TestCase):
    def test_hypertension_and_allergy(self):
        p = product(NOODLES)
        a = scoring.analyse(p, STD)
        out = personalise(p, a, Profile(conditions=["hypertension"], allergies=["peanut", "milk"]), STD)
        titles = [al["title"] for al in out["alerts"]]
        self.assertEqual(out["suitability"], "not_suitable")
        self.assertIn("Contains peanut", titles)
        self.assertIn("May contain milk", titles)
        self.assertIn("High in salt", titles)
        self.assertLess(out["personal_score"], a["score"])
        self.assertEqual(out["alerts"][0]["level"], "avoid")

    def test_child_and_caffeine(self):
        p = product(COLA)
        a = scoring.analyse(p, STD)
        out = personalise(p, a, Profile(age_group="child"), STD)
        self.assertIn("Contains caffeine", [al["title"] for al in out["alerts"]])
        self.assertLess(out["daily_limits"]["salt_g"], 5)

    def test_pku_aspartame(self):
        p = product(COLA, ingredients_text="water, aspartame, citric acid")
        a = scoring.analyse(p, STD)
        out = personalise(p, a, Profile(conditions=["pku"]), STD)
        self.assertEqual(out["suitability"], "not_suitable")

    def test_no_profile_is_suitable_for_dahi(self):
        p = product(DAHI)
        out = personalise(p, scoring.analyse(p, STD), Profile(), STD)
        self.assertEqual(out["suitability"], "suitable")
        self.assertFalse(out["profile_applied"])


class TestSimulation(unittest.TestCase):
    def test_monotonic_and_bounded(self):
        p = product(NOODLES)
        sim = simulation.simulate(p, scoring.analyse(p, STD), STD, servings_per_week=7, years=10)
        self.assertEqual(len(sim["timeline"]), 11)
        for key in sim["systems"]:
            series = [t["systems"][key]["strain"] for t in sim["timeline"]]
            self.assertEqual(series[0], 0)
            self.assertEqual(series, sorted(series))
            self.assertLessEqual(series[-1], 1)

    def test_more_often_means_more_strain(self):
        p = product(COLA)
        a = scoring.analyse(p, STD)
        weekly = simulation.simulate(p, a, STD, 1, 10)["timeline"][-1]["systems"]["teeth"]["strain"]
        daily = simulation.simulate(p, a, STD, 7, 10)["timeline"][-1]["systems"]["teeth"]["strain"]
        self.assertGreater(daily, weekly)

    def test_healthy_food_has_no_findings(self):
        p = product(DAHI, serving_size_g=100)
        sim = simulation.simulate(p, scoring.analyse(p, STD), STD, 7, 10)
        self.assertEqual(sim["findings"], [])

    def test_inputs_are_clamped(self):
        p = product(DAHI)
        sim = simulation.simulate(p, scoring.analyse(p, STD), STD, 999, 999)
        self.assertEqual(sim["years"], 30)
        self.assertEqual(sim["servings_per_week"], 35)


if __name__ == "__main__":
    unittest.main()
