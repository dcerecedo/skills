#!/usr/bin/env python3
"""ds-map: fit a source (inventory or manifest) to a target manifest, and compare fits.

  map.py map --source inventory.json|manifest.json --target manifest.json --out mapping.json
             [--theme T] [--source-theme T]
  map.py compare mapping-a.json mapping-b.json ...      # markdown table on stdout
  map.py check <artifact.json>                          # schema/meta check

Standard library only. Thresholds are in THRESHOLDS and recorded in the output.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dslib import (WHITE, composite, contrast, delta_e, family, hex_of, ms, norm,  # noqa: E402
                   parse_color, px)

THRESHOLDS = {
    "color": {"mapped": 0.02, "near": 0.05, "unit": "ΔE OK, composited over white"},
    "px": {"mapped": 0.5, "near": 2.0, "nearRatio": 0.10, "unit": "px"},
    "letterSpacing": {"mapped": 0.1, "near": 0.3, "unit": "px"},
    "duration": {"mapped": 10, "near": 50, "unit": "ms"},
    "residualCluster": {"color": 0.02, "px": 1.0},
}

COLOR_ROLES = {
    "color": ("text", "icon", "accent"),
    "background-color": ("background", "accent"),
    "outline-color": ("focus", "border", "accent"),
    "fill": ("icon", "text", "accent"),
    "stroke": ("icon", "text", "border", "accent"),
}
for side in ("top", "right", "bottom", "left"):
    COLOR_ROLES[f"border-{side}-color"] = ("border", "focus", "accent")

# rendered property -> mapping category
CATEGORY = {**{p: "color" for p in COLOR_ROLES},
            "font-size": "fontSize", "line-height": "lineHeight", "font-weight": "fontWeight",
            "font-family": "fontFamily", "letter-spacing": "letterSpacing",
            "box-shadow": "shadow", "transition-duration": "duration",
            "transition-timing-function": "easing"}
for side in ("top", "right", "bottom", "left"):
    CATEGORY[f"margin-{side}"] = CATEGORY[f"padding-{side}"] = "spacing"
    CATEGORY[f"border-{side}-width"] = "border-width"
CATEGORY["row-gap"] = CATEGORY["column-gap"] = "spacing"
for corner in ("top-left", "top-right", "bottom-right", "bottom-left"):
    CATEGORY[f"border-{corner}-radius"] = "radius"

DIM_ROLE = {"spacing": "spacing", "radius": "radius", "border-width": "border-width"}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def load(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------- target index

class Target:
    def __init__(self, manifest, theme):
        self.m = manifest
        self.theme = theme
        self.tokens = manifest.get("tokens", [])

    def value(self, tok):
        vals = tok.get("values", {})
        if self.theme in vals:
            return vals[self.theme]
        return next(iter(vals.values()), None) if vals else None

    def candidates(self, category, roles=None):
        """(name, raw value) pairs for a mapping category, honoring roles when the target has them."""
        if category == "color":
            toks = [t for t in self.tokens if t["category"] == "color"]
            return self._by_role(toks, roles)
        if category in DIM_ROLE:
            toks = [t for t in self.tokens if t["category"] == "dimension"]
            return self._by_role(toks, (DIM_ROLE[category],))
        if category == "shadow":
            return [(t["name"], self.value(t)) for t in self.tokens if t["category"] == "shadow"]
        if category == "duration":
            return [(t["name"], self.value(t)) for t in self.tokens if t["category"] == "duration"]
        if category == "easing":
            return [(t["name"], self.value(t)) for t in self.tokens if t["category"] == "cubicBezier"]
        out = [(t["name"], self.value(t)) for t in self.tokens if t["category"] == category]
        for ts in self.m.get("textStyles", []):
            key = {"fontSize": "fontSize", "fontWeight": "fontWeight", "fontFamily": "fontFamily",
                   "letterSpacing": "letterSpacing", "lineHeight": "lineHeight"}[category]
            v = ts.get(key)
            if v is None:
                continue
            if category == "lineHeight":
                fs = px(ts.get("fontSize"))
                lh = px(v) if isinstance(v, str) and v.strip().endswith(("px", "rem")) else None
                if lh is None and fs is not None:
                    try:
                        lh = float(v) * fs
                    except (TypeError, ValueError):
                        lh = None
                v = f"{lh}px" if lh is not None else None
                if v is None:
                    continue
            out.append((f"{ts['name']}.{key}", v))
        return out

    def _by_role(self, toks, roles):
        """Tokens with a compatible role. Unroled tokens only count when the target has no roles
        at all: once a target tags roles, untagged tokens are usually component or domain colors
        (avatars, syntax highlighting) that a rendered value should not be filed under. They still
        surface as `otherRole` when they match exactly."""
        pairs = [(t["name"], self.value(t), t.get("role"), t.get("tier")) for t in toks]
        if roles and any(r for _, _, r, _ in pairs):
            pairs = [p for p in pairs if p[2] in roles]
        # Order expresses preference on ties: listed role order, then semantic before primitive
        # before component tokens.
        order = list(roles or [])
        tier_rank = {"semantic": 0, "primitive": 1, None: 1, "component": 2}
        pairs.sort(key=lambda p: (order.index(p[2]) if p[2] in order else len(order),
                                  tier_rank.get(p[3], 1)))
        return [(n, v) for n, v, _, _ in pairs]

    def all_colors(self):
        return [(t["name"], self.value(t)) for t in self.tokens if t["category"] == "color"]


# ------------------------------------------------------------- matching

def nearest(category, value, cands):
    """-> (token, tokenValue, distance, status)"""
    if not cands:
        return None, None, None, "no-target-scale"
    if category == "color":
        c = parse_color(value)
        if c is None:
            return None, None, None, "unparsed"
        best = min(((round(delta_e(c, pc), 3), i, n, v) for i, (n, v) in enumerate(cands)
                    if (pc := parse_color(v)) is not None), default=None)
        if best is None:
            return None, None, None, "no-target-scale"
        d, _, n, v = best
        t = THRESHOLDS["color"]
        return n, v, round(d, 4), "mapped" if d <= t["mapped"] else "near" if d <= t["near"] else "unmapped"
    if category in ("spacing", "radius", "border-width", "fontSize", "lineHeight", "letterSpacing"):
        x = px(value)
        if x is None:
            return None, None, None, "unparsed"
        x = abs(x)
        best = min(((round(abs(x - abs(p)), 3), i, n, v) for i, (n, v) in enumerate(cands)
                    if (p := px(v)) is not None), default=None)
        if best is None:
            return None, None, None, "no-target-scale"
        d, _, n, v = best
        if category == "letterSpacing":
            t = THRESHOLDS["letterSpacing"]
            near = t["near"]
        else:
            t = THRESHOLDS["px"]
            near = max(t["near"], t["nearRatio"] * x)
        return n, v, round(d, 3), "mapped" if d <= t["mapped"] else "near" if d <= near else "unmapped"
    if category == "fontWeight":
        try:
            x = float(value)
        except ValueError:
            return None, None, None, "unparsed"
        best = min(((abs(x - float(v)), n, v) for n, v in cands
                    if str(v).replace(".", "", 1).isdigit()), default=None)
        if best is None:
            return None, None, None, "no-target-scale"
        d, n, v = best
        return n, v, d, "mapped" if d == 0 else "near" if d <= 100 else "unmapped"
    if category == "fontFamily":
        for n, v in cands:
            if family(v) == family(value):
                return n, v, 0, "mapped"
        return None, None, 1, "unmapped"
    if category == "duration":
        x = ms(value)
        if x is None:
            return None, None, None, "unparsed"
        best = min(((abs(x - p), n, v) for n, v in cands if (p := ms(v)) is not None), default=None)
        if best is None:
            return None, None, None, "no-target-scale"
        d, n, v = best
        t = THRESHOLDS["duration"]
        return n, v, d, "mapped" if d <= t["mapped"] else "near" if d <= t["near"] else "unmapped"
    # shadow, easing: exact after whitespace/case normalization
    for n, v in cands:
        if norm(v) == norm(value):
            return n, v, 0, "mapped"
    return None, None, 1, "unmapped"


# ----------------------------------------------------------- residuals

def residuals(rows):
    out = []
    by_cat = {}
    for r in rows:
        if r["status"] in ("unmapped", "near", "no-target-scale"):
            by_cat.setdefault(r["category"], []).append(r)
    for cat, rs in by_cat.items():
        rs = sorted(rs, key=lambda r: -r["weight"])
        groups = []
        for r in rs:
            for g in groups:
                if cat == "color":
                    a, b = parse_color(g["representative"]), parse_color(r["value"])
                    same = a is not None and b is not None and \
                        delta_e(a, b) <= THRESHOLDS["residualCluster"]["color"]
                elif cat in ("spacing", "radius", "border-width", "fontSize", "lineHeight"):
                    a, b = px(g["representative"]), px(r["value"])
                    same = a is not None and b is not None and \
                        abs(abs(a) - abs(b)) <= THRESHOLDS["residualCluster"]["px"]
                else:
                    same = norm(g["representative"]) == norm(r["value"])
                if same:
                    g["weight"] += r["weight"]
                    if r["value"] not in g["members"]:
                        g["members"].append(r["value"])
                    break
            else:
                groups.append({"category": cat, "representative": r["value"], "weight": r["weight"],
                               "members": [r["value"]], "nearestToken": r.get("token"),
                               "distance": r.get("distance")})
        out.extend(groups)
    return sorted(out, key=lambda g: -g["weight"])


def coverage(rows, target_has):
    cov = {}
    for r in rows:
        c = cov.setdefault(r["category"], {"weight": 0, "mapped": 0, "near": 0})
        if r["status"] == "unparsed":
            continue
        c["weight"] += r["weight"]
        if r["status"] == "mapped":
            c["mapped"] += r["weight"]
        elif r["status"] == "near":
            c["near"] += r["weight"]
    for cat, c in cov.items():
        c["share"] = round(c["mapped"] / c["weight"], 4) if c["weight"] else None
        c["targetHasScale"] = target_has.get(cat, True)
    return cov


# --------------------------------------------------------------- modes

def map_inventory(inv, tgt):
    rows = []
    for group in inv["values"].values():
        for prop, vals in group.items():
            cat = CATEGORY.get(prop)
            if not cat:
                continue
            roles = COLOR_ROLES.get(prop)
            cands = tgt.candidates(cat, roles)
            for value, occ in vals.items():
                tok, tv, d, status = nearest(cat, value, cands)
                row = {"property": prop, "category": cat, "value": value, "weight": occ["count"],
                       "states": occ["states"], "token": tok, "tokenValue": None if tv is None else str(tv), "distance": d,
                       "status": status, "otherRole": None}
                if cat == "color" and status in ("near", "unmapped"):
                    t2, _, d2, s2 = nearest(cat, value, tgt.all_colors())
                    if s2 == "mapped" and t2 != tok:
                        row["otherRole"] = t2
                rows.append(row)
    pairs = []
    text_c = tgt.candidates("color", COLOR_ROLES["color"])
    bg_c = tgt.candidates("color", COLOR_ROLES["background-color"])
    for key, occ in inv.get("pairs", {}).items():
        fg_s, bg_s = (x.strip() for x in key.split("|", 1))
        fg, bg = parse_color(fg_s), parse_color(bg_s)
        if fg is None or bg is None:
            pairs.append({"pair": key, "weight": occ["count"], "ratio": None, "status": "unparsed"})
            continue
        sizes = [px(s) or 0 for s in occ.get("fontSizes", [])] or [0]
        large = all(s >= 24 or (occ.get("bold") and s >= 18.66) for s in sizes)
        need = 3.0 if large else 4.5
        ratio = contrast(fg, bg)
        pairs.append({"pair": key, "weight": occ["count"], "states": occ["states"],
                      "samples": occ["samples"], "fontSizes": occ.get("fontSizes", []),
                      "ratio": round(ratio, 2), "required": need,
                      "status": "pass" if ratio >= need else "fail",
                      "fgToken": nearest("color", fg_s, text_c)[0],
                      "bgToken": nearest("color", bg_s, bg_c)[0]})
    pairs.sort(key=lambda p: (p["status"] != "fail", -p["weight"]))
    return rows, pairs


def map_manifest(src, tgt, src_theme):
    rows = []
    for t in src.get("tokens", []):
        vals = t.get("values", {})
        value = vals.get(src_theme, next(iter(vals.values()), None) if vals else None)
        if value is None:
            continue
        if t["category"] == "color":
            cat, roles = "color", ((t["role"],) if t.get("role") else None)
        elif t["category"] == "dimension":
            cat = {"spacing": "spacing", "radius": "radius", "border-width": "border-width"}.get(t.get("role"))
            if not cat:
                continue
            roles = None
        elif t["category"] == "cubicBezier":
            cat, roles = "easing", None
        else:
            cat, roles = t["category"], None
        weight = (t.get("evidence") or {}).get("instances", 1)
        tok, tv, d, status = nearest(cat, str(value), tgt.candidates(cat, roles))
        rows.append({"sourceToken": t["name"], "category": cat, "value": str(value), "weight": weight,
                     "token": tok, "tokenValue": None if tv is None else str(tv), "distance": d, "status": status, "otherRole": None})
    return rows


def target_pairs(tgt):
    out = []
    names = {t["name"]: t for t in tgt.tokens}
    for p in tgt.m.get("pairs", []):
        fg, bg = names.get(p["fg"]), names.get(p["bg"])
        if not fg or not bg:
            out.append({**p, "ratio": None, "status": "missing-token"})
            continue
        f, b = parse_color(tgt.value(fg)), parse_color(tgt.value(bg))
        if f is None or b is None:
            out.append({**p, "ratio": None, "status": "unparsed"})
            continue
        need = {"body": 4.5, "large": 3.0, "ui": 3.0}[p["use"]]
        r = contrast(f, b)
        out.append({**p, "ratio": round(r, 2), "required": need, "status": "pass" if r >= need else "fail"})
    return out


def cmd_map(a):
    src, tm = load(a.source), load(a.target)
    theme = a.theme or tm.get("defaultTheme") or tm["themes"][0]
    if theme not in tm["themes"]:
        sys.exit(f"theme {theme!r} not in target themes {tm['themes']}")
    tgt = Target(tm, theme)
    kind = "inventory" if src.get("meta", {}).get("schema", "").startswith("ds-inventory") else "manifest"
    if kind == "inventory":
        rows, pairs = map_inventory(src, tgt)
    else:
        st = a.source_theme or src.get("defaultTheme") or src["themes"][0]
        rows, pairs = map_manifest(src, tgt, st), None
    cats = {r["category"] for r in rows}
    target_has = {c: bool(tgt.candidates(c, None)) for c in cats}
    sm = src.get("meta", {})
    out = {
        "meta": {"schema": "ds-mapping/1", "generatedAt": now(),
                 "source": {"kind": kind, "path": os.path.abspath(a.source), "name": sm.get("name", ""),
                            "commit": sm.get("commit", ""), "generatedAt": sm.get("generatedAt", "")},
                 "target": {"name": tm["meta"]["name"], "version": tm["meta"]["version"],
                            "path": os.path.abspath(a.target)},
                 "theme": theme, "thresholds": THRESHOLDS},
        "coverage": coverage(rows, target_has),
        "rows": sorted(rows, key=lambda r: (r["category"], -r["weight"])),
        "residuals": residuals(rows),
        "targetPairs": target_pairs(tgt),
    }
    if pairs is not None:
        out["pairs"] = pairs
    if os.path.exists(a.out):  # keep the component mapping ds-map wrote by hand
        prev = load(a.out)
        if "components" in prev:
            out["components"] = prev["components"]
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(summary_line(out))


def summary_line(m):
    cov = m["coverage"]
    parts = [f"{c} {v['share']:.0%}" if v["share"] is not None else f"{c} n/a" for c, v in sorted(cov.items())]
    return f"{m['meta']['target']['name']} ({m['meta']['theme']}): " + ", ".join(parts)


def cmd_compare(a):
    ms_ = [load(p) for p in a.mappings]
    cats = sorted({c for m in ms_ for c in m["coverage"]})
    head = ["Target", "Theme"] + cats + ["Unmapped weight", "Extension candidates", "Rendered pairs failing",
                                         "Target pairs failing", "Components w/o equivalent"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for m in ms_:
        row = [f"{m['meta']['target']['name']} {m['meta']['target']['version']}", m["meta"]["theme"]]
        for c in cats:
            v = m["coverage"].get(c)
            if not v:
                row.append("–")
            elif not v.get("targetHasScale", True):
                row.append("no scale")
            else:
                row.append(f"{v['share']:.0%}" if v["share"] is not None else "n/a")
        unm = sum(r["weight"] for r in m["rows"] if r["status"] in ("unmapped", "no-target-scale"))
        row.append(str(unm))
        row.append(str(len(m["residuals"])))
        rp = m.get("pairs")
        row.append(str(sum(1 for p in rp if p["status"] == "fail")) if rp is not None else "–")
        row.append(str(sum(1 for p in m.get("targetPairs", []) if p["status"] == "fail")))
        comps = m.get("components")
        row.append(str(sum(c.get("instances", 1) for c in comps if c["target"] is None)) + " inst."
                   if comps is not None else "not mapped")
        print("| " + " | ".join(row) + " |")


def cmd_check(a):
    d = load(a.artifact)
    schema_id = d.get("meta", {}).get("schema", "")
    here = os.path.dirname(os.path.abspath(__file__))
    fname = {"ds-inventory/1": "inventory", "ds-manifest/1": "manifest", "ds-mapping/1": "mapping"}.get(schema_id)
    if not fname:
        sys.exit(f"unknown or missing meta.schema: {schema_id!r}")
    schema = load(os.path.join(here, "..", "schemas", f"{fname}.schema.json"))
    try:
        import jsonschema  # optional
        errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(d), key=lambda e: list(e.path))
        if errs:
            for e in errs[:10]:
                print(f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message[:200]}", file=sys.stderr)
            sys.exit(f"{a.artifact}: {len(errs)} schema error(s)")
        how = "jsonschema"
    except ImportError:
        missing = [k for k in schema.get("required", []) if k not in d]
        missing += [f"meta.{k}" for k in schema["properties"]["meta"].get("required", [])
                    if k not in d.get("meta", {})]
        if missing:
            sys.exit(f"{a.artifact}: missing {missing}")
        how = "required keys only (pip install jsonschema for full validation)"
    if fname == "manifest":
        bad = [t["name"] for t in d["tokens"] if not set(t["values"]) <= set(d["themes"])]
        if bad:
            sys.exit(f"tokens with values for undeclared themes: {bad[:10]}")
    print(f"ok: {schema_id} ({how})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map")
    m.add_argument("--source", required=True)
    m.add_argument("--target", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--theme")
    m.add_argument("--source-theme")
    c = sub.add_parser("compare")
    c.add_argument("mappings", nargs="+")
    k = sub.add_parser("check")
    k.add_argument("artifact")
    a = p.parse_args()
    {"map": cmd_map, "compare": cmd_compare, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
