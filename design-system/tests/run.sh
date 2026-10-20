#!/usr/bin/env bash
# Smoke test for design-system/crawl.template.js and scripts/.
# Needs playwright-cli (pinned version in SKILL.md) with a browser it can launch.
# Optional: PW_CONFIG=<playwright-cli.json> to point at a custom executable.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$HERE/../crawl.template.js"
WORK="$(mktemp -d)"; PORT="${PORT:-8765}"
trap 'kill $SERVER 2>/dev/null || true; playwright-cli -s=dds-test close >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
(cd "$HERE/fixture" && python3 -m http.server "$PORT" >/dev/null 2>&1) & SERVER=$!
sleep 1
ROUTES="    { name: 'home', path: '/', states: [ { name: 'default' }, { name: 'modal-open', steps: async (page) => { await page.click('#open'); } } ] },\n    { name: 'missing', path: '/nope-404' },"
sed -e "s|__BASE_URL__|http://localhost:$PORT|" -e "s|__OUT_DIR__|$WORK|" -e "s|__COMMIT__|test|" \
    -e "s|    // __ROUTES__|$ROUTES|" "$TEMPLATE" > "$WORK/crawl.js"
CFG=(); [ -n "${PW_CONFIG:-}" ] && CFG=(--config="$PW_CONFIG")
playwright-cli -s=dds-test "${CFG[@]}" open about:blank >/dev/null
playwright-cli -s=dds-test --raw run-code --filename="$WORK/crawl.js" > "$WORK/inventory.json"
python3 - "$WORK/inventory.json" "$WORK" <<'PY'
import json, os, sys
d = json.load(open(sys.argv[1]))
ids = [s["id"] for s in d["states"]]
assert ids == ["desktop/home/default", "desktop/home/modal-open", "desktop/missing/default"], ids
assert d["errors"] == [{"id": "desktop/missing/default", "error": "HTTP 404"}], d["errors"]
bg = d["values"]["color"]["background-color"]
assert {"rgb(51, 102, 255)", "rgb(52, 103, 254)"} <= set(bg), "near-duplicate blues not both captured"
shadow = d["values"]["elevation"]["box-shadow"]
assert [v["states"] for v in shadow.values()] == [["desktop/home/modal-open"]], "modal state not reached"
assert "rgb(153, 153, 153) | rgb(255, 255, 255)" in d["pairs"], "low-contrast pair missing"
assert all(os.path.exists(s["screenshot"]) for s in d["states"]), "screenshot missing"
print("ok:", d["summary"]["colorPairs"], "color pairs,", len(ids), "states")
PY
MAP="$HERE/../scripts/map.py"
python3 "$MAP" check "$WORK/inventory.json"
python3 "$MAP" map --source "$WORK/inventory.json" --target "$HERE/fixture/target.manifest.json" --out "$WORK/mapping.json"
python3 "$MAP" check "$WORK/mapping.json"
python3 -m unittest -q "$HERE/test_map.py"
