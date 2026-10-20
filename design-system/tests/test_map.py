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
        "spacing": {"padding": {"16px": {"count": 4, "states": ["d/home/default"], "samples": ["b"]},
                                "15px": {"count": 1, "states": ["d/home/default"], "samples": ["c"]},
                                "40px": {"count": 1, "states": ["d/home/default"], "samples": ["d"]}},
                    "margin": {"16px": {"count": 2, "ua": 2, "states": ["d/home/default"], "samples": ["p"]}}},
        "radius": {"border-radius": {"6px": {"count": 1, "states": ["d/home/default"], "samples": ["b"]}}},
        "border": {"border-width": {"1px": {"count": 2, "states": ["d/home/default"], "samples": ["b"]},
                                    "2px": {"count": 2, "states": ["d/home/default"], "samples": ["c"]}}},
        "typography": {"font-family": {"Arial": {"count": 2, "ua": 2, "states": ["d/home/default"], "samples": ["button"]},
                                       "Helvetica": {"count": 1, "states": ["d/home/default"], "samples": ["x"]}},
                       "font-weight": {"700": {"count": 1, "states": ["d/home/default"], "samples": ["h1"]}}},
        "elevation": {"box-shadow": {"rgba(0, 0, 0, 0.2) 0px 4px 12px 0px": {"count": 1, "states": ["d/home/default"], "samples": ["m"]}}},
    },
    "pairs": {"rgb(153, 153, 153) | rgb(255, 255, 255)": {"count": 2, "states": ["d/home/default"], "samples": ["p"], "texts": [{"fontSize": "13px", "fontWeight": 400}]},
              "rgb(26, 26, 26) | rgb(255, 255, 255)": {"count": 5, "states": ["d/home/default"], "samples": ["h1"], "texts": [{"fontSize": "32px", "fontWeight": 700}]},
              "rgb(26, 26, 26) | rgb(250, 250, 250)": {"count": 1, "states": ["d/home/default"], "samples": ["h2"], "texts": [{"fontSize": "32px", "fontWeight": 700}, {"fontSize": "14px", "fontWeight": 400}]}},
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
        self.assertEqual(self.rows[("padding", "16px")]["status"], "mapped")
        self.assertEqual(self.rows[("padding", "15px")]["status"], "near")
        self.assertEqual(self.rows[("padding", "40px")]["status"], "unmapped")

    def test_coverage_is_instance_weighted(self):
        # browser-default margins are excluded from the weight
        self.assertEqual(self.m["coverage"]["spacing"]["share"], round(4 / 6, 4))
        self.assertEqual(self.m["coverage"]["spacing"]["browserDefault"], 2)
        self.assertEqual(self.rows[("margin", "16px")]["status"], "browser-default")

    def test_no_scale_reported(self):
        self.assertFalse(self.m["coverage"]["shadow"]["targetHasScale"])
        self.assertIsNone(self.m["coverage"]["shadow"]["share"])

    def test_font_weight_exact(self):
        self.assertEqual(self.rows[("font-weight", "700")]["status"], "unmapped")

    def test_font_family(self):
        self.assertEqual(self.rows[("font-family", "Arial")]["status"], "browser-default")
        self.assertEqual(self.rows[("font-family", "Helvetica")]["status"], "unmapped")

    def test_residuals_keep_distinct_widths(self):
        # no border-width scale in target -> not residuals; but 1px and 2px are not merged anywhere
        self.assertFalse([g for g in self.m["residuals"] if g["category"] == "border-width"])

    def test_residual_for_offscale_color(self):
        self.assertIn("rgb(10, 200, 10)", [g["representative"] for g in self.m["residuals"]])

    def test_pairs(self):
        p = {x["pair"]: x for x in self.m["pairs"]}
        self.assertEqual(p["rgb(153, 153, 153) | rgb(255, 255, 255)"]["status"], "fail")
        self.assertEqual(p["rgb(26, 26, 26) | rgb(255, 255, 255)"]["required"], 3.0)
        self.assertEqual(p["rgb(26, 26, 26) | rgb(250, 250, 250)"]["required"], 4.5)
        tp = {(x["fg"], x["bg"]): x["status"] for x in self.m["targetPairs"]}
        self.assertEqual(tp[("text-muted", "bg-default")], "pass")
        self.assertEqual(tp[("text-primary", "missing")], "missing-token")


class Shadows(unittest.TestCase):
    def test_shadow_parse_and_match(self):
        from map import nearest
        tok = [("elev-1", "0 4px 12px rgba(0,0,0,.2)"), ("elev-2", "0 8px 24px rgba(0,0,0,.2)")]
        self.assertEqual(nearest("shadow", "rgba(0, 0, 0, 0.2) 0px 4px 12px 0px", tok)[:1], ("elev-1",))
        self.assertEqual(nearest("shadow", "rgba(0, 0, 0, 0.2) 0px 4px 13px 0px", tok)[3], "near")


class Check(unittest.TestCase):
    def test_sub_schemas(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "routes.json")
            with open(p, "w") as f:
                json.dump({"meta": {"schema": "ds-inventory-routes/1", "commit": "x"},
                           "routes": [{"name": "home", "path": "/", "foundIn": ["nav"]}]}, f)
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "map.py"), "check", p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


class MapManifest(unittest.TestCase):
    def test_token_translation(self):
        src = read(TARGET)
        src["meta"]["name"] = "Self"
        m = run_map(src)
        self.assertEqual(m["meta"]["source"]["kind"], "manifest")
        self.assertTrue(all(r["status"] == "mapped" for r in m["rows"] if r["category"] in ("color", "spacing")))


if __name__ == "__main__":
    unittest.main()
