"""Unit tests for design-system/scripts (no browser). Run: python3 -m unittest design-system/tests/test_map.py"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import dslib  # noqa: E402
import map as dsmap  # noqa: E402

TARGET = os.path.join(HERE, "fixture", "target.manifest.json")


def read(path):
    with open(path) as f:
        return json.load(f)
INVENTORY = {
    "meta": {"schema": "ds-inventory/1", "generatedAt": "2026-10-20T00:00:00Z", "baseUrl": "x", "commit": "t"},
    "states": [{"id": "d/home/default", "url": "x", "elements": 3}], "errors": [], "summary": {},
    "values": {
        "color": {
            "color": {"rgb(26, 26, 26)": {"count": 5, "states": ["d/home/default"], "samples": ["h1"]},
                      "rgb(153, 153, 153)": {"count": 2, "states": ["d/home/default"], "samples": ["p"]}},
            "background-color": {"rgb(255, 255, 255)": {"count": 1, "states": ["d/home/default"], "samples": ["body"]},
                                 "rgb(52, 103, 254)": {"count": 2, "states": ["d/home/default"], "samples": ["b"]},
                                 "rgb(10, 200, 10)": {"count": 1, "states": ["d/home/default"], "samples": ["c"]}}},
        "spacing": {"padding-left": {"16px": {"count": 4, "states": ["d/home/default"], "samples": ["b"]},
                                     "15px": {"count": 1, "states": ["d/home/default"], "samples": ["c"]},
                                     "40px": {"count": 1, "states": ["d/home/default"], "samples": ["d"]}}},
        "radius": {"border-top-left-radius": {"6px": {"count": 1, "states": ["d/home/default"], "samples": ["b"]}}},
        "elevation": {"box-shadow": {"rgba(0, 0, 0, 0.2) 0px 4px 12px 0px": {"count": 1, "states": ["d/home/default"], "samples": ["m"]}}},
    },
    "pairs": {"rgb(153, 153, 153) | rgb(255, 255, 255)": {"count": 2, "states": ["d/home/default"], "samples": ["p"], "fontSizes": ["13px"]},
              "rgb(26, 26, 26) | rgb(255, 255, 255)": {"count": 5, "states": ["d/home/default"], "samples": ["h1"], "fontSizes": ["32px"], "bold": True}},
}


def run_map(source):
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.json")
        out = os.path.join(d, "mapping.json")
        with open(src, "w") as f:
            json.dump(source, f)
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "map.py"), "map", "--source", src,
                        "--target", TARGET, "--out", out], check=True, capture_output=True)
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "map.py"), "check", out], check=True,
                       capture_output=True)
        return read(out)


class Lib(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(dslib.hex_of(dslib.parse_color("rgb(51, 102, 255)")), "#3366ff")
        self.assertEqual(dslib.hex_of(dslib.parse_color("#36f")), "#3366ff")
        self.assertAlmostEqual(dslib.parse_color("rgba(0,0,0,.5)")[3], 0.5)
        self.assertEqual(dslib.hex_of(dslib.parse_color("oklch(1 0 0)")), "#ffffff")
        self.assertIsNone(dslib.parse_color("currentcolor"))

    def test_contrast(self):
        self.assertAlmostEqual(dslib.contrast(dslib.parse_color("#000"), dslib.parse_color("#fff")), 21, places=1)
        self.assertAlmostEqual(dslib.contrast(dslib.parse_color("#999"), dslib.parse_color("#fff")), 2.85, places=2)

    def test_transparent_never_matches_opaque(self):
        self.assertGreaterEqual(dslib.delta_e(dslib.parse_color("#fff"), dslib.parse_color("rgba(255,255,255,0)")), 1)

    def test_px(self):
        self.assertEqual(dslib.px("1rem"), 16)
        self.assertEqual(dslib.px("-8px"), -8)
        self.assertIsNone(dslib.px("auto"))


class MapInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = run_map(INVENTORY)
        cls.rows = {(r["property"], r["value"]): r for r in cls.m["rows"]}

    def test_role_filter_excludes_unroled_tokens(self):
        r = self.rows[("color", "rgb(153, 153, 153)")]
        self.assertNotEqual(r["token"], "avatar-ring")
        self.assertEqual(r["otherRole"], "avatar-ring")

    def test_white_maps_to_opaque_token(self):
        self.assertEqual(self.rows[("background-color", "rgb(255, 255, 255)")]["token"], "bg-default")

    def test_near_duplicate_maps(self):
        self.assertEqual(self.rows[("background-color", "rgb(52, 103, 254)")]["status"], "mapped")

    def test_spacing_statuses(self):
        self.assertEqual(self.rows[("padding-left", "16px")]["status"], "mapped")
        self.assertEqual(self.rows[("padding-left", "15px")]["status"], "near")
        self.assertEqual(self.rows[("padding-left", "40px")]["status"], "unmapped")

    def test_coverage_is_instance_weighted(self):
        self.assertEqual(self.m["coverage"]["spacing"]["share"], round(4 / 6, 4))

    def test_no_scale_reported(self):
        self.assertFalse(self.m["coverage"]["shadow"]["targetHasScale"])

    def test_residual_for_offscale_color(self):
        self.assertIn("rgb(10, 200, 10)", [g["representative"] for g in self.m["residuals"]])

    def test_pairs(self):
        p = {x["pair"]: x for x in self.m["pairs"]}
        self.assertEqual(p["rgb(153, 153, 153) | rgb(255, 255, 255)"]["status"], "fail")
        self.assertEqual(p["rgb(26, 26, 26) | rgb(255, 255, 255)"]["required"], 3.0)
        tp = {(x["fg"], x["bg"]): x["status"] for x in self.m["targetPairs"]}
        self.assertEqual(tp[("text-muted", "bg-default")], "pass")
        self.assertEqual(tp[("text-primary", "missing")], "missing-token")


class MapManifest(unittest.TestCase):
    def test_token_translation(self):
        src = read(TARGET)
        src["meta"]["name"] = "Self"
        m = run_map(src)
        self.assertEqual(m["meta"]["source"]["kind"], "manifest")
        self.assertTrue(all(r["status"] == "mapped" for r in m["rows"] if r["category"] in ("color", "spacing")))


if __name__ == "__main__":
    unittest.main()
