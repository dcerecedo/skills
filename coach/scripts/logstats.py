#!/usr/bin/env python3
"""coach log: scan a production log excerpt for personal data, aggregate it per endpoint, and
compare against a baseline. Only aggregates are ever written; raw lines are never persisted.

  logstats.py scan FILE                         exit 3 if anything looks like personal data
  logstats.py summarize FILE [--paths P,Q] [--fields F,G] [--duration-unit ms|s] [--out OUT.json]
  logstats.py compare BASE.json CURRENT.json [--paths P,Q] [--min-n 30] [--p95-threshold 0.2]

Lines are JSON objects or logfmt (key=value). Recognized fields:
  path   path | route | url | request_path        (route wins when present: it is already templated)
  status status | status_code
  dur    duration_ms | duration | elapsed_ms | response_time
Paths are templated: numeric, UUID and long hex segments become {id}; the query string is dropped.

Standard library only.
"""
import argparse
import hashlib
import json
import re
import shlex
import sys

PII = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("api-key", re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}")),
    ("secret-field", re.compile(r"(?i)[\"']?(?:password|passwd|secret|token|api_key|apikey|authorization|cookie|session(?:id)?)[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{6,}")),
    ("ipv4", re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")),
    ("ipv6", re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){4,7}[0-9A-Fa-f]{1,4}(?![0-9A-Fa-f:])")),
    ("dni-nie", re.compile(r"(?<![A-Za-z0-9])(?:\d{8}|[XYZ]\d{7})[A-HJ-NP-TV-Z](?![A-Za-z0-9])")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")),
    ("phone", re.compile(r"(?<![\w.])(?:\+\d{2,3}[ -]?)?[6789]\d{2}[ -]?\d{3}[ -]?\d{3}(?![\w.])")),
]
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
PATH_KEYS = ("route", "path", "request_path", "url")
STATUS_KEYS = ("status", "status_code")
DUR_KEYS = ("duration_ms", "duration", "elapsed_ms", "response_time")
TS_KEYS = ("ts", "time", "timestamp", "@timestamp", "asctime")


def luhn(digits):
    s, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n > 4 else n * 2
        s += n
        alt = not alt
    return s % 10 == 0


def scan_lines(lines):
    hits = []
    for n, line in enumerate(lines, 1):
        kinds = [k for k, rx in PII if rx.search(line)]
        for m in CARD.finditer(line):
            d = re.sub(r"\D", "", m.group())
            if 13 <= len(d) <= 19 and luhn(d):
                kinds.append("card-number")
                break
        if kinds:
            hits.append((n, sorted(set(kinds))))
    return hits


def parse_line(line):
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None
    try:
        parts = shlex.split(line)
    except ValueError:
        return None
    rec = dict(p.split("=", 1) for p in parts if "=" in p)
    return rec or None


def first(rec, keys):
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return None


def template(path):
    path = str(path).split("?", 1)[0]
    path = re.sub(r"^https?://[^/]+", "", path)
    segs = []
    for s in path.split("/"):
        if s.isdigit() or UUID.match(s) or re.fullmatch(r"[0-9a-fA-F]{12,}", s):
            segs.append("{id}")
        else:
            segs.append(s)
    return "/".join(segs) or "/"


def pct(values, q):
    if not values:
        return None
    v = sorted(values)
    k = max(0, min(len(v) - 1, int(round(q * len(v) + 0.5)) - 1))
    return round(v[k], 2)


def summarize(lines, paths=None, fields=(), unit="ms"):
    eps, parsed, ts = {}, 0, []
    for line in lines:
        rec = parse_line(line)
        if not rec:
            continue
        p, st, du = first(rec, PATH_KEYS), first(rec, STATUS_KEYS), first(rec, DUR_KEYS)
        if p is None or st is None or du is None:
            continue
        try:
            st, du = int(st), float(du) * (1000 if unit == "s" else 1)
        except (TypeError, ValueError):
            continue
        ep = template(p) if "route" not in rec else str(rec["route"])
        if paths and ep not in paths:
            continue
        parsed += 1
        t = first(rec, TS_KEYS)
        if t:
            ts.append(str(t))
        e = eps.setdefault(ep, {"dur": [], "status": {}, "extra": {f: [] for f in fields}})
        e["dur"].append(du)
        b = f"{st // 100}xx"
        e["status"][b] = e["status"].get(b, 0) + 1
        for f in fields:
            try:
                e["extra"][f].append(float(rec[f]))
            except (KeyError, TypeError, ValueError):
                pass
    out = {}
    for ep, e in sorted(eps.items()):
        n = len(e["dur"])
        out[ep] = {"n": n, "status": e["status"],
                   "error_rate": round(e["status"].get("5xx", 0) / n, 4),
                   "p50_ms": pct(e["dur"], 0.5), "p95_ms": pct(e["dur"], 0.95), "max_ms": round(max(e["dur"]), 2),
                   "extra": {f: {"n": len(v), "mean": round(sum(v) / len(v), 2), "p95": pct(v, 0.95)}
                             for f, v in e["extra"].items() if v}}
    return {"lines": len(lines), "parsed": parsed,
            "window": {"first": min(ts), "last": max(ts)} if ts else None, "endpoints": out}


def compare(base, cur, paths=None, min_n=30, p95_threshold=0.2):
    rows = []
    for ep in sorted(set(base["endpoints"]) | set(cur["endpoints"])):
        if paths and ep not in paths:
            continue
        b, c = base["endpoints"].get(ep), cur["endpoints"].get(ep)
        if not b or not c:
            rows.append({"endpoint": ep, "verdict": "no baseline" if not b else "absent in sample"})
            continue
        r = {"endpoint": ep, "n": [b["n"], c["n"]], "p95_ms": [b["p95_ms"], c["p95_ms"]],
             "error_rate": [b["error_rate"], c["error_rate"]]}
        if min(b["n"], c["n"]) < min_n:
            r["verdict"] = f"insufficient (n < {min_n})"
        else:
            reasons = []
            if b["p95_ms"] and (c["p95_ms"] - b["p95_ms"]) / b["p95_ms"] > p95_threshold:
                reasons.append(f"p95 +{round(100 * (c['p95_ms'] - b['p95_ms']) / b['p95_ms'])}%")
            if c["error_rate"] - b["error_rate"] > 0.01:
                reasons.append(f"5xx rate +{round(100 * (c['error_rate'] - b['error_rate']), 1)}pp")
            for f, cv in c.get("extra", {}).items():
                bv = b.get("extra", {}).get(f)
                if bv and bv["mean"] and (cv["mean"] - bv["mean"]) / bv["mean"] > p95_threshold:
                    reasons.append(f"{f} mean {bv['mean']} -> {cv['mean']}")
            r["verdict"] = "regression: " + ", ".join(reasons) if reasons else "ok"
        rows.append(r)
    return rows


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("scan"); x.add_argument("file")
    x = sp.add_parser("summarize"); x.add_argument("file"); x.add_argument("--paths"); x.add_argument("--fields")
    x.add_argument("--duration-unit", default="ms", choices=["ms", "s"]); x.add_argument("--out")
    x = sp.add_parser("compare"); x.add_argument("base"); x.add_argument("current"); x.add_argument("--paths")
    x.add_argument("--min-n", type=int, default=30); x.add_argument("--p95-threshold", type=float, default=0.2)
    a = p.parse_args(argv)
    split = lambda s: [v.strip() for v in (s or "").split(",") if v.strip()]  # noqa: E731

    if a.cmd in ("scan", "summarize"):
        lines = read(a.file)
        hits = scan_lines(lines)
        if hits:
            # Report positions and kinds only; never echo the matched values.
            print(f"REFUSED: {len(hits)} line(s) look like they contain personal data or secrets:", file=sys.stderr)
            for n, kinds in hits[:50]:
                print(f"  line {n}: {', '.join(kinds)}", file=sys.stderr)
            sys.exit(3)
        if a.cmd == "scan":
            print(f"clean: {len(lines)} lines")
            return
        s = summarize(lines, set(split(a.paths)) or None, split(a.fields), a.duration_unit)
        with open(a.file, "rb") as f:
            s["source_sha256"] = hashlib.sha256(f.read()).hexdigest()
        js = json.dumps(s, indent=2, sort_keys=True)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(js + "\n")
        print(js)
    else:
        with open(a.base) as f:
            base = json.load(f)
        with open(a.current) as f:
            cur = json.load(f)
        rows = compare(base, cur, set(split(a.paths)) or None, a.min_n, a.p95_threshold)
        print("| endpoint | n base/now | p95 ms base/now | 5xx base/now | verdict |")
        print("| --- | --- | --- | --- | --- |")
        for r in rows:
            n = "/".join(map(str, r.get("n", ["-", "-"])))
            p95 = "/".join(map(str, r.get("p95_ms", ["-", "-"])))
            er = "/".join(map(str, r.get("error_rate", ["-", "-"])))
            print(f"| `{r['endpoint']}` | {n} | {p95} | {er} | {r['verdict']} |")
        if any(r["verdict"].startswith("regression") for r in rows):
            sys.exit(4)


if __name__ == "__main__":
    main()
