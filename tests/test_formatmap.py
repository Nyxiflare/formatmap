"""Offline tests for formatmap.py. Run from the skill folder:  python -m unittest discover -s tests"""
import contextlib
import copy
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import formatmap as fm  # noqa: E402

CAT = fm.load_catalogue()
EXAMPLE = ROOT / "examples" / "ai-tools-faceless" / "scan.json"


def scan(**creator):
    c = {"faceless": False, "length": "short", "hours_per_week": 10}
    c.update(creator)
    return {"niche": "test niche", "date": "2026-11-22", "sample": {"size": 100},
            "creator": c, "overrides": {}, "entries": []}


def entry(fid, sat=None, count=None, layout=None, basis="estimated", evidence="reason"):
    return {"format": fid, "layout": layout, "saturation": sat, "count": count,
            "basis": basis, "evidence": evidence}


def run(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fm.main(list(args))
    return buf.getvalue()


class CatalogueTests(unittest.TestCase):
    def test_shipped_catalogue_is_valid_and_complete(self):
        ids = set(CAT["_formats"])
        for must in ("talking-head", "green-screen", "text-on-broll", "carousel", "pov", "tutorial", "listicle",
                     "storytime", "faceless-explainer", "vox-collage", "screen-recording", "skit",
                     "interview-street", "mini-doc", "data-visual"):
            self.assertIn(must, ids)
        self.assertGreaterEqual(len(CAT["layouts"]), 8)

    def test_every_format_has_definition_examples_and_all_four_upgrades(self):
        for f in CAT["formats"]:
            self.assertTrue(f["definition"], f["id"])
            self.assertTrue(f["examples"], f["id"])
            for k in ("polish", "insight", "novelty", "detail"):
                self.assertTrue(f["upgrades"].get(k), f"{f['id']} missing {k}")

    def test_bad_catalogue_rejected(self):
        bad = json.loads(fm.DEFAULT_CATALOGUE.read_text(encoding="utf-8"))
        bad["formats"][0]["effort"] = 11
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(SystemExit):
                fm.load_catalogue(p)

    def test_ratings_are_data_editing_catalogue_changes_result(self):
        edited = json.loads(fm.DEFAULT_CATALOGUE.read_text(encoding="utf-8"))
        for f in edited["formats"]:
            if f["id"] == "carousel":
                f["premium"] = 9
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps(edited), encoding="utf-8")
            cat2 = fm.load_catalogue(p)
        s = scan()
        s["entries"] = [entry("carousel", 2)]
        self.assertEqual(fm.evaluate(s, CAT)[0]["status"], "neutral")
        self.assertEqual(fm.evaluate(s, cat2)[0]["status"], "open")

    def test_scoring_thresholds_come_from_catalogue(self):
        cat2 = copy.deepcopy(CAT)
        cat2["scoring"]["open"]["min_premium"] = 3
        s = scan()
        s["entries"] = [entry("carousel", 2)]
        self.assertEqual(fm.evaluate(s, cat2)[0]["status"], "open")


class SaturationTests(unittest.TestCase):
    bands = CAT["scoring"]["saturation_bands"]

    def test_bands(self):
        self.assertEqual(fm.saturation_from_share(0, self.bands), 0)
        self.assertEqual(fm.saturation_from_share(0.05, self.bands), 2)
        self.assertEqual(fm.saturation_from_share(0.10, self.bands), 3)
        self.assertEqual(fm.saturation_from_share(0.25, self.bands), 6)
        self.assertEqual(fm.saturation_from_share(0.5, self.bands), 9)
        self.assertEqual(fm.saturation_from_share(1.0, self.bands), 10)

    def test_count_derives_saturation(self):
        s = scan()
        s["entries"] = [entry("talking-head", count=30, basis="observed", evidence="40 results x 3 queries")]
        r = fm.evaluate(s, CAT)[0]
        self.assertEqual(r["saturation"], 7)
        self.assertAlmostEqual(r["share"], 0.3)


class StatusTests(unittest.TestCase):
    def status(self, fid, sat, layout=None, **creator):
        s = scan(**creator)
        s["entries"] = [entry(fid, sat, layout=layout)]
        return fm.evaluate(s, CAT)[0]

    def test_open_premium_unsaturated_within_capacity(self):
        self.assertEqual(self.status("data-visual", 2)["status"], "open")

    def test_open_but_over_capacity_is_stretch(self):
        r = self.status("mini-doc", 1, hours_per_week=5)
        self.assertEqual(r["status"], "stretch")
        self.assertFalse(r["within_capacity"])
        self.assertEqual(self.status("data-visual", 2, max_effort=4)["status"], "stretch")

    def test_easy_and_crowded_is_upgrade(self):
        self.assertEqual(self.status("text-on-broll", 8)["status"], "upgrade")

    def test_hard_and_crowded_is_crowded(self):
        self.assertEqual(self.status("vox-collage", 8)["status"], "crowded")

    def test_unknown_saturation_never_open(self):
        r = self.status("vox-collage", None)
        self.assertEqual(r["status"], "unknown")
        self.assertIsNone(r["score"])

    def test_faceless_blocks_face_required_only(self):
        self.assertEqual(self.status("talking-head", 1, faceless=True)["status"], "blocked")
        self.assertNotEqual(self.status("storytime", 1, faceless=True)["status"], "blocked")
        self.assertNotEqual(self.status("talking-head", 1, faceless=False)["status"], "blocked")

    def test_layout_adds_effort_and_premium_with_clamp(self):
        r = self.status("faceless-explainer", 1, layout="paper-to-glass")
        self.assertEqual((r["effort"], r["premium"]), (6, 7))
        self.assertEqual(r["status"], "open")
        r = self.status("vox-collage", 1, layout="paper-to-glass")
        self.assertEqual((r["effort"], r["premium"]), (10, 10))

    def test_wrong_length_is_na(self):
        self.assertEqual(self.status("carousel", 1, length="long")["status"], "n/a")

    def test_override_lowers_effort(self):
        s = scan(max_effort=6)
        s["entries"] = [entry("vox-collage", 1)]
        self.assertEqual(fm.evaluate(s, CAT)[0]["status"], "stretch")
        s["overrides"] = {"vox-collage": {"effort": 5, "hours": 4, "reason": "pro animator with templates"}}
        r = fm.evaluate(s, CAT)[0]
        self.assertEqual(r["status"], "open")
        self.assertEqual(r["hours"], 4)

    def test_score_formula(self):
        r = self.status("data-visual", 2)
        w = CAT["scoring"]["weights"]
        self.assertAlmostEqual(r["score"], round(w["premium"] * 8 + w["openness"] * 8 + w["ease"] * 4, 2))


class NewFieldTests(unittest.TestCase):
    def test_not_applicable_is_left_out(self):
        s = scan()
        s["entries"] = [entry("data-visual", 0), {"format": "product-ui-demo", "applicable": False,
                                                    "reason": "no software in an espresso niche"}]
        rows = {r["format"]: r for r in fm.evaluate(s, CAT)}
        self.assertEqual(rows["product-ui-demo"]["status"], "n/a")
        self.assertIn("espresso", rows["product-ui-demo"]["reason"])
        res = fm.build_result(s, CAT)
        self.assertNotIn("product-ui-demo", [r["format"] for r in res["recommendations"]])
        self.assertIn("Left out: Clean UI", fm.render_md(res))
        self.assertIn("no software", fm.render_html(res))

    def test_adjust_nudges_count_derived_saturation(self):
        s = scan()
        s["entries"] = [dict(entry("process-asmr", count=11, basis="observed", evidence="all look the same"), adjust=1)]
        self.assertEqual(fm.validate_scan(s, CAT), ([], []))
        r = fm.evaluate(s, CAT)[0]
        self.assertEqual(r["saturation"], fm.saturation_from_share(0.11, CAT["scoring"]["saturation_bands"]) + 1)
        s["entries"][0]["adjust"] = 2
        self.assertTrue(fm.validate_scan(s, CAT)[0])

    def test_shared_sample_evidence(self):
        s = scan()
        s["sample"] = {"size": 50, "evidence": "5 YouTube Shorts searches, 22 Nov"}
        s["entries"] = [entry("pov", count=3, basis="observed", evidence="")]
        self.assertEqual(fm.validate_scan(s, CAT)[0], [])
        page = fm.render_html(fm.build_result(s, CAT))
        self.assertEqual(page.count("5 YouTube Shorts searches"), 1)

    def test_platform_native_formats(self):
        s = scan(platforms=["youtube-shorts"])
        s["entries"] = [entry("carousel", 1)]
        r = fm.evaluate(s, CAT)[0]
        self.assertEqual(r["status"], "n/a")
        self.assertIn("not native", r["reason"])
        s["creator"]["platforms"] = ["youtube-shorts", "tiktok"]
        r = fm.evaluate(s, CAT)[0]
        self.assertNotEqual(r["status"], "n/a")
        self.assertEqual(r["platform_note"], "only on tiktok")
        s["creator"]["platforms"] = ["instagram-reels"]
        self.assertEqual(fm.evaluate(s, CAT)[0]["platform_note"], "")

    def test_rows_sorted_actionable_first(self):
        s = scan()
        s["entries"] = [entry("mini-doc", 0), entry("data-visual", 2), entry("text-on-broll", 9),
                        entry("case-study", 1, basis="observed", evidence="x")]
        order = [r["format"] for r in fm.evaluate(s, CAT)]
        self.assertEqual(order[:2], ["case-study", "data-visual"])  # observed open before estimated open
        self.assertLess(order.index("text-on-broll"), order.index("mini-doc"))  # upgrade before stretch

    def test_check_warnings_stay_out_of_report(self):
        s = scan()
        s["entries"] = [entry("pov", 3, evidence=""), entry("data-visual", 1)]
        res = fm.build_result(s, CAT)
        self.assertTrue(res["check_warnings"])
        self.assertNotIn("with no reason", fm.render_html(res) + fm.render_md(res))


class ValidationTests(unittest.TestCase):
    def errors(self, s):
        return fm.validate_scan(s, CAT)[0]

    def test_observed_needs_evidence(self):
        s = scan()
        s["entries"] = [entry("pov", 3, basis="observed", evidence="")]
        self.assertTrue(any("needs evidence" in e for e in self.errors(s)))

    def test_count_needs_sample_size_and_fits_it(self):
        s = scan()
        s["sample"] = {}
        s["entries"] = [entry("pov", count=3, basis="user", evidence="pasted")]
        self.assertTrue(any("sample.size" in e for e in self.errors(s)))
        s["sample"] = {"size": 2}
        self.assertTrue(any("larger than" in e for e in self.errors(s)))

    def test_unknown_ids_duplicates_and_ranges(self):
        s = scan()
        s["entries"] = [entry("nope", 2), entry("pov", 2, layout="nope"), entry("skit", 2), entry("skit", 2),
                        entry("listicle", 12)]
        errs = " | ".join(self.errors(s))
        for frag in ("nope: unknown format", "pov + nope: unknown layout", "skit: listed twice", "0-10"):
            self.assertIn(frag, errs)

    def test_creator_required(self):
        s = scan()
        del s["creator"]
        s["entries"] = [entry("pov", 2)]
        self.assertTrue(self.errors(s))

    def test_build_refuses_invalid_scan(self):
        s = scan()
        s["entries"] = [entry("pov", 3, basis="observed", evidence="")]
        with self.assertRaises(SystemExit):
            fm.build_result(s, CAT)


class RecommendAndPlanTests(unittest.TestCase):
    def full_scan(self, hours=10, **creator):
        s = scan(hours_per_week=hours, **creator)
        sats = {"text-on-broll": 9, "talking-head": 8, "listicle": 7, "carousel": 6, "data-visual": 1,
                "product-ui-demo": 2, "case-study": 3, "whiteboard": 2, "vox-collage": 0, "storytime": 4,
                "tutorial": 3}
        s["entries"] = [entry(k, v) for k, v in sats.items()]
        s["creator"]["current_formats"] = ["text-on-broll", "talking-head"]
        return s

    def test_three_to_five_distinct_and_includes_an_upgrade(self):
        res = fm.build_result(self.full_scan(), CAT, top=5)
        recs = res["recommendations"]
        self.assertTrue(3 <= len(recs) <= 5)
        self.assertEqual(len({r["format"] for r in recs}), len(recs))
        self.assertTrue(any(r["status"] == "upgrade" for r in recs))
        self.assertEqual(recs[0]["status"], "upgrade")
        self.assertTrue(all(r["status"] in ("open", "upgrade", "neutral") for r in recs))

    def test_top_is_clamped(self):
        self.assertLessEqual(len(fm.build_result(self.full_scan(hours=40), CAT, top=9)["recommendations"]), 5)

    def test_plan_fits_budget_when_possible(self):
        for hours in (3, 6, 10, 20):
            res = fm.build_result(self.full_scan(hours=hours), CAT)
            p = res["plan"]
            self.assertAlmostEqual(p["budget_hours"], hours * 2)
            if not p["warnings"]:
                self.assertLessEqual(p["total_hours"], p["budget_hours"] + 1e-9)
            self.assertGreaterEqual(len(res["recommendations"]), 3)

    def test_plan_calendar_within_days_and_interleaved(self):
        p = fm.build_result(self.full_scan(), CAT)["plan"]
        days = [k["day"] for k in p["calendar"]]
        self.assertEqual(days, sorted(days))
        self.assertTrue(all(1 <= d <= 14 for d in days))
        n = len(p["items"])
        firsts = [k["piece"] for k in p["calendar"][:n]]
        self.assertEqual(firsts, [1] * n)
        self.assertEqual(sum(i["pieces"] for i in p["items"]), len(p["calendar"]))

    def test_tiny_budget_warns_instead_of_pretending(self):
        s = self.full_scan(hours=0.5)
        res = fm.build_result(s, CAT)
        self.assertTrue(res["plan"]["warnings"])

    def test_upgrade_of_current_format_costs_only_extra_hours(self):
        res = fm.build_result(self.full_scan(), CAT)
        up = [i for i in res["plan"]["items"] if i["status"] == "upgrade"][0]
        self.assertTrue(up["upgrade_of_current"])
        base = CAT["_formats"][up["format"]]["hours"]["short"]
        sc = CAT["scoring"]
        self.assertAlmostEqual(up["hours_each"], round(max(base * (sc["upgrade_hours_factor"] - 1), sc["upgrade_min_extra_hours"]), 2))
        self.assertTrue(any(k["replaces_usual_post"] for k in res["plan"]["calendar"]))

    def test_upgrade_of_new_format_costs_full_upgraded_time(self):
        s = self.full_scan()
        s["creator"]["current_formats"] = []
        res = fm.build_result(s, CAT)
        up = [i for i in res["plan"]["items"] if i["status"] == "upgrade"][0]
        base = CAT["_formats"][up["format"]]["hours"]["short"]
        self.assertAlmostEqual(up["hours_each"], round(base * CAT["scoring"]["upgrade_hours_factor"], 2))

    def test_low_hours_prefers_open_cells_over_neutral_fillers(self):
        """Tester case: 6 h/week must not fill the test with cheap neutral formats while open ones fit."""
        s = self.full_scan(hours=6)
        s["entries"] += [entry("pov", 3), entry("before-after", 4)]  # cheap neutral candidates
        res = fm.build_result(s, CAT)
        statuses = [r["status"] for r in res["recommendations"]]
        self.assertNotIn("neutral", statuses)
        self.assertEqual(statuses[0], "upgrade")
        self.assertGreaterEqual(statuses.count("open"), 2)

    def test_more_hours_never_means_fewer_planned_pieces(self):
        prev_pieces = prev_formats = 0
        for hours in (2, 4, 6, 8, 10, 15, 20, 30):
            p = fm.build_result(self.full_scan(hours=hours), CAT)["plan"]
            pieces = sum(i["pieces"] for i in p["items"])
            self.assertGreaterEqual(pieces, prev_pieces, hours)
            self.assertGreaterEqual(len(p["items"]), prev_formats, hours)
            prev_pieces, prev_formats = pieces, len(p["items"])

    def test_test_hours_per_week_sets_budget(self):
        s = self.full_scan(hours=10)
        s["creator"]["test_hours_per_week"] = 4
        self.assertAlmostEqual(fm.build_result(s, CAT)["plan"]["budget_hours"], 8)

    def test_faceless_never_recommends_face_required(self):
        res = fm.build_result(self.full_scan(faceless=True), CAT)
        for r in res["recommendations"]:
            self.assertNotEqual(CAT["_formats"][r["format"]]["face"], "required")

    def test_upgrade_checklists_cover_easy_current_formats(self):
        res = fm.build_result(self.full_scan(), CAT)
        ids = [u["id"] for u in res["upgrades"]]
        self.assertIn("text-on-broll", ids)
        self.assertIn("talking-head", ids)
        for u in res["upgrades"]:
            self.assertEqual(set(u["checklist"]), {"polish", "insight", "novelty", "detail"})

    def test_mostly_estimated_is_flagged(self):
        res = fm.build_result(self.full_scan(), CAT)
        self.assertTrue(any("hypothesis" in w for w in res["warnings"]))


class OutputTests(unittest.TestCase):
    def test_html_is_self_contained_and_escaped(self):
        s = scan()
        s["niche"] = "<script>alert(1)</script> & co"
        s["entries"] = [entry("data-visual", 1, evidence="see https://example.com <b>x</b>"),
                        entry("pov", 8), entry("carousel", 2)]
        page = fm.render_html(fm.build_result(s, CAT))
        self.assertNotIn("<script", page.lower())
        self.assertNotRegex(page, r"(src|href)\s*=")
        self.assertNotIn("@import", page)
        self.assertNotIn("url(", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", page)
        self.assertEqual(len(re.findall(r'class="cell[ "]', page)), 25)

    def test_grid_buckets(self):
        self.assertEqual([fm.bucket(v) for v in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)], [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])

    def test_markdown_table_and_recommendation_marks(self):
        res = fm.build_result(json.loads(EXAMPLE.read_text(encoding="utf-8")), CAT)
        md = fm.render_md(res)
        self.assertIn("| # | Format | Effort | Premium | Saturation |", md)
        self.assertEqual(md.count("★") - 1, len(res["recommendations"]))  # one ★ in the legend line
        self.assertIn("2-week test plan", md)

    def test_cli_build_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            text = run("build", str(EXAMPLE), "--out-dir", d, "--json")
            self.assertIn("Format map", text)
            for name in ("formatmap.html", "formatmap.md", "formatmap.json"):
                self.assertTrue((Path(d) / name).exists(), name)

    def test_cli_template_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scan.json"
            run("template", "--niche", "home coffee", "--faceless", "--hours", "5",
                "--current", "text-on-broll", "--out", str(p))
            s = json.loads(p.read_text(encoding="utf-8"))
            self.assertTrue(s["creator"]["faceless"])
            self.assertTrue(all("short" in CAT["_formats"][e["format"]]["lengths"] for e in s["entries"]))
            self.assertIn("ok", run("check", str(p)))
            res = fm.build_result(s, CAT)  # all unknown: no crash, nothing open
            self.assertFalse(any(r["status"] == "open" for r in res["rows"]))

    def test_cli_catalogue_and_show(self):
        self.assertIn("vox-collage", run("catalogue"))
        self.assertNotIn("| carousel |", run("catalogue", "--length", "long"))
        self.assertIn("paper-to-glass", run("catalogue", "--layouts"))
        self.assertIn("Polish", run("show", "talking-head"))

    def test_example_scan_acceptance(self):
        """The README example: faceless, 10h/week, short-form AI-tools niche."""
        res = fm.build_result(json.loads(EXAMPLE.read_text(encoding="utf-8")), CAT)
        names = [r["format"] for r in res["recommendations"]]
        self.assertIn("text-on-broll", names)  # the easy crowded format, upgraded
        self.assertTrue(any(r["layout"] == "paper-to-glass" for r in res["recommendations"]))
        self.assertLessEqual(res["plan"]["total_hours"], res["plan"]["budget_hours"])
        self.assertFalse(re.search(r"\bviews?\b", json.dumps(res["rows"])))


if __name__ == "__main__":
    unittest.main()
