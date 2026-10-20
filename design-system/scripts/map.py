#!/usr/bin/env python3
"""ds-map: fit a source (inventory or manifest) to a target manifest, and compare fits.

  map.py map --source inventory.json|manifest.json --target manifest.json --out mapping.json
             [--theme T] [--source-theme T]
  map.py compare mapping-a.json mapping-b.json ...      # markdown table on stdout
  map.py check <artifact.json>                          # schema check for any ds-* artifact

Standard library only. Thresholds are in THRESHOLDS and recorded in every mapping.
"""
import argparse
import datetime
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dslib import (contrast, delta_e, font_stack, ms, norm, parse_color,  # noqa: E402
                   parse_shadow, px, shadow_distance)

THRESHOLDS = {
    "color": {"mapped": 0.02, "near": 0.05, "unit": "ΔE OK, composited over white; alpha difference counts at least as much"},
    "px": {"mapped": 0.5, "near": 2.0, "nearRatio": 0.10, "unit": "px"},
    "letterSpacing": {"mapped": 0.1, "near": 0.3, "unit": "px"},
    "duration": {"mapped": 10, "near": 50, "unit": "ms"},
    "shadow": {"mappedPx": 0.5, "nearPx": 2.0, "mappedColor": 0.02, "nearColor": 0.05},
    "fontWeight": {"mapped": 0, "unit": "exact"},
    "fontFamily": {"mapped": "same first family", "near": "rendered family is in the target's stack"},
    "tie": {"color": 0.001, "px": 0.0},
    "residualCluster": {"color": 0.02, "px": 0.5},
}

# Which token roles a rendered property may be filed under, in order of preference.
COLOR_ROLES = {
    "color": ("text", "icon"),
    "background-color": ("background", "accent"),
    "border-color": ("border", "focus"),
    "outline-color": ("focus", "border"),
    "fill": ("icon", "text"),
    "stroke": ("icon", "border"),
}

# rendered logical property -> mapping category
CATEGORY = {**{p: "color" for p in COLOR_ROLES},
            "margin": "spacing", "padding": "spacing", "gap": "spacing",
            "border-radius": "radius", "border-width": "border-width",
            "font-size": "fontSize", "line-height": "lineHeight", "font-weight": "fontWeight",
            "font-family": "fontFamily", "letter-spacing": "letterSpacing",
            "box-shadow": "shadow", "transition-duration": "duration",
            "transition-timing-function": "easing"}

DIM_ROLE = {"spacing": "spacing", "radius": "radius", "border-width": "border-width"}
PX_CATEGORIES = ("spacing", "radius", "border-width", "fontSize", "lineHeight", "letterSpacing")

SCHEMAS = {
    "ds-inventory/1": ("inventory", None),
    "ds-inventory-routes/1": ("inventory", "routes"),
    "ds-inventory-source/1": ("inventory", "source"),
    "ds-inventory-components/1": ("inventory", "components"),
    "ds-manifest/1": ("manifest", None),
    "ds-mapping/1": ("mapping", None),
}


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
        for key in (self.theme, "*"):
            if key in vals:
                return vals[key]
        return next(iter(vals.values()), None) if vals else None

    def has_scale(self, category):
        """Does the target offer anything at all for this category?"""
        return bool(self.candidates(category, None))

    def candidates(self, category, roles):
        """Ordered (name, value) candidates for a mapping category; earlier wins ties."""
        if category == "color":
            return self._by_role([t for t in self.tokens if t["category"] == "color"], roles)
        if category in DIM_ROLE:
            return self._by_role([t for t in self.tokens if t["category"] == "dimension"], (DIM_ROLE[category],))
        simple = {"shadow": "shadow", "duration": "duration", "easing": "cubicBezier"}
        if category in simple:
            return [(t["name"], self.value(t)) for t in self.tokens if t["category"] == simple[category]]
        out = [(t["name"], self.value(t)) for t in self.tokens if t["category"] == category]
        for ts in self.m.get("textStyles", []):
            v = ts.get(category)
            if v is None:
                continue
            if category == "lineHeight":
                v = self._line_height_px(ts, v)
                if v is None:
                    continue
            out.append((f"{ts['name']}.{category}", v))
        return out

    @staticmethod
    def _line_height_px(ts, v):
        if isinstance(v, str) and v.strip().endswith(("px", "rem")):
            return v
        fs = px(ts.get("fontSize"))
        try:
            return f"{round(float(v) * fs, 2)}px" if fs is not None else None
        except (TypeError, ValueError):
            return None

    def _by_role(self, toks, roles):
        """Tokens with a compatible role. Untagged tokens count only when the target tags no roles
        at all: once it does, untagged ones are usually component or domain colors (avatars, syntax)
        that a rendered value should not be filed under. They surface as `otherRole` instead."""
        rows = [(t["name"], self.value(t), t.get("role"), t.get("tier")) for t in toks]
        if roles and any(r for _, _, r, _ in rows):
            rows = [r for r in rows if r[2] in roles]
        order = list(roles or [])
        tier_rank = {"semantic": 0, "primitive": 1, None: 1, "component": 2}
        rows.sort(key=lambda r: (order.index(r[2]) if r[2] in order else len(order), tier_rank.get(r[3], 1)))
        return [(n, v) for n, v, _, _ in rows]

    def all_colors(self):
        return [(t["name"], self.value(t)) for t in self.tokens if t["category"] == "color"]


# ------------------------------------------------------------- matching

RANK = {"mapped": 0, "near": 1, "unmapped": 2, "no-target-scale": 3, "unparsed": 4}


def _pick(scored, mapped, near, tie):
    """scored: [(distance, name, value)] in preference order -> (name, value, d, status, alternatives)."""
    if not scored:
        return None, None, None, "no-target-scale", []
    best = min(d for d, _, _ in scored)
    tied = [(n, v) for d, n, v in scored if d - best <= tie]
    n, v = tied[0]
    status = "mapped" if best <= mapped else "near" if best <= near else "unmapped"
    return n, v, round(best, 4), status, [x for x, _ in tied[1:]]


def nearest(category, value, cands):
    """-> (token, tokenValue, distance, status, alternatives)"""
    if not cands:
        return None, None, None, "no-target-scale", []
    if category == "color":
        c = parse_color(value)
        if c is None:
            return None, None, None, "unparsed", []
        t = THRESHOLDS["color"]
        scored = [(delta_e(c, pc), n, v) for n, v in cands if (pc := parse_color(v)) is not None]
        return _pick(scored, t["mapped"], t["near"], THRESHOLDS["tie"]["color"])
    if category in PX_CATEGORIES:
        x = px(value)
        if x is None:
            return None, None, None, "unparsed", []
        x = abs(x)
        scored = [(abs(x - abs(p)), n, v) for n, v in cands if (p := px(v)) is not None]
        if category == "letterSpacing":
            t = THRESHOLDS["letterSpacing"]
            near = t["near"]
        else:
            t = THRESHOLDS["px"]
            near = max(t["near"], t["nearRatio"] * x)
        return _pick(scored, t["mapped"], near, THRESHOLDS["tie"]["px"])
    if category == "fontWeight":
        try:
            x = float(value)
        except ValueError:
            return None, None, None, "unparsed", []
        scored = []
        for n, v in cands:
            try:
                scored.append((abs(x - float(v)), n, v))
            except (TypeError, ValueError):
                pass
        return _pick(scored, 0, 0, 0)
    if category == "fontFamily":
        first = font_stack(value)[:1]
        if not first:
            return None, None, None, "unparsed", []
        for n, v in cands:
            if font_stack(v)[:1] == first:
                return n, v, 0, "mapped", []
        for n, v in cands:
            if first[0] in font_stack(v):
                return n, v, 1, "near", []
        return None, None, None, "unmapped", []
    if category == "shadow":
        a = parse_shadow(value)
        if a is None:
            return None, None, None, "unparsed", []
        t = THRESHOLDS["shadow"]
        scored = []
        for n, v in cands:
            dpx, de = shadow_distance(a, parse_shadow(v))
            if math.isfinite(dpx):
                status_d = 0 if dpx <= t["mappedPx"] and de <= t["mappedColor"] else \
                    1 if dpx <= t["nearPx"] and de <= t["nearColor"] else 2
                scored.append((status_d + dpx / 1000, n, v))
        if not scored:
            return None, None, None, "unmapped", []
        n, v, key, _, alts = _pick(scored, 0.5, 1.5, 0)
        # key = status band + px/1000; report the px difference itself as the distance
        return n, v, round((key - int(key)) * 1000, 3), ("mapped" if key < 1 else "near" if key < 2 else "unmapped"), alts
    if category == "duration":
        x = ms(value)
        if x is None:
            return None, None, None, "unparsed", []
        t = THRESHOLDS["duration"]
        scored = [(abs(x - p), n, v) for n, v in cands if (p := ms(v)) is not None]
        return _pick(scored, t["mapped"], t["near"], 0)
    # easing and anything else: exact after whitespace/case normalization
    for n, v in cands:
        if norm(v) == norm(value):
            return n, v, 0, "mapped", []
    return None, None, None, "unmapped", []


# ----------------------------------------------------------- residuals

def residuals(rows):
    """Group unmapped values (where the target has a scale) into extension candidates."""
    out, by_cat = [], {}
    for r in rows:
        if r["status"] == "unmapped" and r["weight"] > 0:
            by_cat.setdefault(r["category"], []).append(r)
    for cat, rs in by_cat.items():
        groups = []
        for r in sorted(rs, key=lambda r: -r["weight"]):
            for g in groups:
                if cat == "color":
                    a, b = parse_color(g["representative"]), parse_color(r["value"])
                    same = a is not None and b is not None and delta_e(a, b) <= THRESHOLDS["residualCluster"]["color"]
                elif cat in PX_CATEGORIES:
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


def coverage(rows, has_scale):
    """Per category, weights of authored instances. `share` is null where the target has no scale."""
    cov = {}
    for r in rows:
        c = cov.setdefault(r["category"], {"weight": 0, "mapped": 0, "near": 0, "unmapped": 0,
                                            "unparsed": 0, "browserDefault": 0})
        c["browserDefault"] += r.get("ua", 0)
        if r["status"] == "unparsed":
            c["unparsed"] += r["weight"]
            continue
        c["weight"] += r["weight"]
        if r["status"] in ("mapped", "near", "unmapped"):
            c[r["status"]] += r["weight"]
        elif r["status"] == "no-target-scale":
            c["unmapped"] += r["weight"]
    for cat, c in cov.items():
        c["targetHasScale"] = has_scale.get(cat, True)
        c["share"] = round(c["mapped"] / c["weight"], 4) if c["weight"] and c["targetHasScale"] else None
    return cov


# --------------------------------------------------------------- modes

def _color_row(row, value, tgt):
    """Flag a role mismatch: a token outside the allowed roles fits better than any allowed one."""
    t2, _, _, s2, _ = nearest("color", value, tgt.all_colors())
    if t2 and t2 != row["token"] and RANK[s2] < RANK[row["status"]]:
        row["otherRole"] = t2


def map_inventory(inv, tgt):
    rows = []
    for group in inv["values"].values():
        for prop, vals in group.items():
            cat = CATEGORY.get(prop)
            if not cat:
                continue
            cands = tgt.candidates(cat, COLOR_ROLES.get(prop))
            for value, occ in vals.items():
                ua = occ.get("ua", 0)
                authored = occ["count"] - ua
                tok, tv, d, status, alts = nearest(cat, value, cands)
                if authored == 0:
                    status = "browser-default"
                row = {"property": prop, "category": cat, "value": value, "weight": authored, "ua": ua,
                       "states": occ["states"], "token": tok, "tokenValue": None if tv is None else str(tv),
                       "distance": d, "status": status, "alternatives": alts, "otherRole": None}
                if cat == "color" and status in ("near", "unmapped", "no-target-scale"):
                    _color_row(row, value, tgt)
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
        texts = occ.get("texts") or [{"fontSize": "0px", "fontWeight": 400}]

        def large(t):
            s = px(t["fontSize"]) or 0
            return s >= 24 or (t["fontWeight"] >= 700 and s >= 18.66)
        need = 3.0 if all(large(t) for t in texts) else 4.5
        ratio = contrast(fg, bg)
        pairs.append({"pair": key, "weight": occ["count"], "states": occ["states"], "samples": occ["samples"],
                      "texts": texts, "ratio": round(ratio, 2), "required": need,
                      "status": "pass" if ratio >= need else "fail",
                      "fgToken": nearest("color", fg_s, text_c)[0], "bgToken": nearest("color", bg_s, bg_c)[0]})
    pairs.sort(key=lambda p: (p["status"] != "fail", -p["weight"]))
    return rows, pairs


def map_manifest(src, tgt, src_theme):
    rows = []
    for t in src.get("tokens", []):
        vals = t.get("values", {})
        value = vals.get(src_theme, vals.get("*", next(iter(vals.values()), None) if vals else None))
        if value is None:
            continue
        if t["category"] == "color":
            cat, roles = "color", ((t["role"],) if t.get("role") else None)
        elif t["category"] == "dimension":
            cat = DIM_ROLE.get(t.get("role"))
            if not cat:
                continue
            roles = None
        elif t["category"] == "cubicBezier":
            cat, roles = "easing", None
        else:
            cat, roles = t["category"], None
        weight = (t.get("evidence") or {}).get("instances", 1)
        tok, tv, d, status, alts = nearest(cat, str(value), tgt.candidates(cat, roles))
        row = {"sourceToken": t["name"], "category": cat, "value": str(value), "weight": weight,
               "token": tok, "tokenValue": None if tv is None else str(tv), "distance": d, "status": status,
               "alternatives": alts, "otherRole": None}
        if cat == "color" and status in ("near", "unmapped", "no-target-scale"):
            _color_row(row, str(value), tgt)
        rows.append(row)
    return rows


def target_pairs(tgt):
    out, names = [], {t["name"]: t for t in tgt.tokens}
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
        src_name = os.path.basename(os.path.dirname(os.path.abspath(a.source)))
    else:
        st = a.source_theme or src.get("defaultTheme") or src["themes"][0]
        rows, pairs = map_manifest(src, tgt, st), None
        src_name = src.get("meta", {}).get("name", "")
    has_scale = {c: tgt.has_scale(c) for c in {r["category"] for r in rows}}
    sm, tmeta = src.get("meta", {}), tm["meta"]
    out = {
        "meta": {"schema": "ds-mapping/1", "generatedAt": now(),
                 "source": {"kind": kind, "path": os.path.abspath(a.source), "name": src_name,
                            "commit": sm.get("commit", ""), "theme": sm.get("theme", ""),
                            "generatedAt": sm.get("generatedAt", "")},
                 "target": {"name": tmeta["name"], "version": tmeta["version"], "path": os.path.abspath(a.target),
                            "generatedAt": tmeta.get("generatedAt", "")},
                 "theme": theme, "thresholds": THRESHOLDS},
        "coverage": coverage(rows, has_scale),
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


def fmt_share(v):
    if not v.get("targetHasScale", True):
        return "no scale"
    if not v.get("weight") and v.get("unparsed"):
        return "unparsed"
    return f"{v['share']:.0%}" if v.get("share") is not None else "n/a"


def summary_line(m):
    parts = [f"{c} {fmt_share(v)}" for c, v in sorted(m["coverage"].items())]
    return f"{m['meta']['target']['name']} ({m['meta']['theme']}): " + ", ".join(parts)


def cmd_compare(a):
    maps = [load(p) for p in a.mappings]
    cats = sorted({c for m in maps for c in m["coverage"]})
    head = ["Target", "Theme"] + cats + [
        "Unmapped (target has a scale)", "No target scale", "Browser defaults (excluded)",
        "Residual groups", "Rendered pairs failing", "Target pairs failing / unchecked",
        "Component instances w/o equivalent"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for m in maps:
        row = [f"{m['meta']['target']['name']} {m['meta']['target']['version']}", m["meta"]["theme"]]
        row += [fmt_share(m["coverage"][c]) if c in m["coverage"] else "–" for c in cats]
        rows = m["rows"]
        row.append(str(sum(r["weight"] for r in rows if r["status"] == "unmapped")))
        row.append(str(sum(r["weight"] for r in rows if r["status"] == "no-target-scale")))
        row.append(str(sum(r.get("ua", 0) for r in rows)))
        row.append(str(len(m["residuals"])))
        rp = m.get("pairs")
        row.append(str(sum(1 for p in rp if p["status"] == "fail")) if rp is not None else "–")
        tp = m.get("targetPairs", [])
        row.append(f"{sum(1 for p in tp if p['status'] == 'fail')} / "
                   f"{sum(1 for p in tp if p['status'] in ('missing-token', 'unparsed'))}")
        comps = m.get("components")
        row.append(str(sum(c.get("instances", 1) for c in comps if c["target"] is None))
                   if comps is not None else "not mapped")
        lines.append("| " + " | ".join(row) + " |")
    print("\n".join(lines))


def cmd_check(a):
    d = load(a.artifact)
    schema_id = d.get("meta", {}).get("schema", "")
    if schema_id not in SCHEMAS:
        sys.exit(f"unknown or missing meta.schema: {schema_id!r} (known: {', '.join(SCHEMAS)})")
    fname, sub = SCHEMAS[schema_id]
    here = os.path.dirname(os.path.abspath(__file__))
    root = load(os.path.join(here, "..", "schemas", f"{fname}.schema.json"))
    schema = root if sub is None else {**root["$defs"][sub], "$defs": root["$defs"]}
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
        meta_req = schema.get("properties", {}).get("meta", {}).get("required", [])
        missing += [f"meta.{k}" for k in meta_req if k not in d.get("meta", {})]
        if missing:
            sys.exit(f"{a.artifact}: missing {missing}")
        how = "required keys only (pip install jsonschema for full validation)"
    if fname == "manifest" and sub is None:
        bad = [t["name"] for t in d["tokens"] if not set(t["values"]) <= set(d["themes"]) | {"*"}]
        if bad:
            sys.exit(f"tokens with values for undeclared themes: {bad[:10]}")
        names = {t["name"] for t in d["tokens"]}
        missing_pair_tokens = sorted({x for p in d.get("pairs", []) for x in (p["fg"], p["bg"]) if x not in names})
        if missing_pair_tokens:
            sys.exit(f"pairs reference tokens that do not exist: {missing_pair_tokens[:10]}")
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
