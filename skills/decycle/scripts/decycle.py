#!/usr/bin/env python3
"""Deterministic helpers for the decycle skill.

Commands (all take --root, the repository root, and --package, the root
Python package to analyse):

  scan      list open problems with every ranking metric, diffed against the
            last saved scan (.decycle/state.json); --write-state saves it
  detail    every import behind one problem, with file, line and code
  simulate  check a refactoring plan (graph operations per step) against the
            whole graph: no step may add a cyclic sibling dependency or break a
            recorded decision, and the problem must be gone at the end
  record    store an approved decision (which side is lower) and mark the
            problem active
  guard     print the import-linter contracts that lock in the current state

A "problem" is one sibling dependency (importer package -> imported package,
both children of the same ancestor package) that grimp nominates for removal
to make that ancestor's children acyclic. Its id uses import-linter's arrow
syntax: "shop.billing -> shop.orders".

Needs grimp, which ships with import-linter. The package is parsed, never
imported, so the interpreter only has to have grimp installed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from collections import defaultdict

STATE_DIR = ".decycle"
STATE_FILE = "state.json"
DECISIONS_JSON = "decisions.json"
DECISIONS_MD = "decisions.md"

Import = tuple[str, str]


# --------------------------------------------------------------------------
# Graph building (grimp) and pure graph logic (used by scan and simulate)
# --------------------------------------------------------------------------


def _grimp():
    try:
        import grimp  # noqa: PLC0415
    except ImportError:
        sys.stderr.write(
            "decycle: grimp is not installed for this interpreter.\n"
            "Install import-linter (it brings grimp), or run through uv:\n"
            "  uv run --no-project --with import-linter python <this script> ...\n"
        )
        sys.exit(3)
    return grimp


def build(root: str, package: str, exclude_type_checking: bool = False):
    grimp = _grimp()
    for path in (root, os.path.join(root, "src")):
        if os.path.isdir(path):
            if path in sys.path:
                sys.path.remove(path)
            sys.path.insert(0, path)
    return grimp.build_graph(package, exclude_type_checking_imports=exclude_type_checking, cache_dir=None)


def graph_imports(graph) -> set[Import]:
    return {(m, imp) for m in graph.modules for imp in graph.find_modules_directly_imported_by(m)}


def sibling_of(importer: str, imported: str) -> tuple[str, str, str] | None:
    """(ancestor, importer child, imported child) for the one level at which
    this import is a dependency between siblings, or None when one module
    contains the other."""
    a, b = importer.split("."), imported.split(".")
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    if k == 0 or k == len(a) or k == len(b):
        return None
    return ".".join(a[:k]), ".".join(a[: k + 1]), ".".join(b[: k + 1])


def sibling_deps(imports: set[Import]) -> dict[str, dict[tuple[str, str], list[Import]]]:
    deps: dict[str, dict[tuple[str, str], list[Import]]] = defaultdict(lambda: defaultdict(list))
    for imp in sorted(imports):
        s = sibling_of(*imp)
        if s:
            deps[s[0]][(s[1], s[2])].append(imp)
    return deps


def sccs(edges: set[tuple[str, str]]) -> list[set[str]]:
    """Strongly connected components (iterative Tarjan); singletons omitted."""
    adj: dict[str, list[str]] = defaultdict(list)
    nodes: set[str] = set()
    for x, y in edges:
        adj[x].append(y)
        nodes.update((x, y))
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[set[str]] = []
    counter = 0
    for start in sorted(nodes):
        if start in index:
            continue
        work = [(start, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
            children = adj[v]
            if i < len(children):
                work.append((v, i + 1))
                w = children[i]
                if w not in index:
                    work.append((w, 0))
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
                continue
            for w in children:
                if w in on_stack:
                    low[v] = min(low[v], low[w])
            if low[v] == index[v]:
                comp = set()
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.add(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    out.append(comp)
    return out


def cyclic_deps(imports: set[Import]) -> set[tuple[str, str, str]]:
    """Every sibling dependency (ancestor, x, y) that lies on a cycle."""
    result = set()
    for ancestor, pairs in sibling_deps(imports).items():
        for comp in sccs(set(pairs)):
            result.update((ancestor, x, y) for (x, y) in pairs if x in comp and y in comp)
    return result


def dep_id(x: str, y: str) -> str:
    return f"{x} -> {y}"


def parse_id(problem_id: str) -> tuple[str, str]:
    x, _, y = problem_id.partition(" -> ")
    if not x or not y:
        raise SystemExit(f"decycle: bad problem id {problem_id!r}; expected 'pkg.a -> pkg.b'")
    return x.strip(), y.strip()


def within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


# --------------------------------------------------------------------------
# State and decisions
# --------------------------------------------------------------------------


def state_path(root: str, name: str) -> str:
    return os.path.join(root, STATE_DIR, name)


def load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def decision_violations(imports: set[Import], decisions: list[dict]) -> set[tuple[str, Import]]:
    """(decision id, import) for every import from a decision's lower side into its higher side."""
    return {
        (d["id"], imp)
        for d in decisions
        for imp in imports
        if within(imp[0], d["lower"]) and within(imp[1], d["higher"])
    }


def guard_present(root: str) -> bool:
    if os.path.exists(os.path.join(root, ".importlinter")):
        return True
    for name, marker in (("setup.cfg", "[importlinter"), ("pyproject.toml", "[tool.importlinter")):
        try:
            with open(os.path.join(root, name)) as f:
                if marker in f.read():
                    return True
        except FileNotFoundError:
            pass
    return False


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def module_paths(root: str, module: str) -> list[str]:
    rel = module.replace(".", "/")
    out = []
    for base in ("src", ""):
        for cand in (rel, rel + ".py"):
            path = os.path.join(base, cand) if base else cand
            if os.path.exists(os.path.join(root, path)):
                out.append(path)
    return out


def churn(root: str, modules: list[str], days: int = 90) -> int | None:
    paths = [p for m in modules for p in module_paths(root, m)]
    if not paths:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", root, "log", f"--since={days}.days", "--format=%H", "--", *paths],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return len(set(out.split()))


def analyse(root: str, package: str) -> dict:
    graph = build(root, package)
    imports = graph_imports(graph)
    runtime = graph_imports(build(root, package, exclude_type_checking=True))
    type_only = imports - runtime
    deps = sibling_deps(imports)

    breakers: set[tuple[str, str, str]] = set()
    for ancestor in sorted(deps):
        if not graph.find_children(ancestor):
            continue
        for importer, imported in graph.nominate_cycle_breakers(ancestor):
            s = sibling_of(importer, imported)
            if s and s[0] == ancestor:
                breakers.add(s)

    problems = []
    for ancestor, x, y in sorted(breakers):
        pairs = deps[ancestor]
        comp = next((c for c in sccs(set(pairs)) if x in c), {x, y})
        cut = pairs.get((x, y), [])
        problems.append(
            {
                "id": dep_id(x, y),
                "ancestor": ancestor,
                "importer": x,
                "imported": y,
                "cut": len(cut),
                "reverse": len(pairs.get((y, x), [])),
                "scc": len(comp),
                "depth": ancestor.count(".") + 1,
                "churn90": churn(root, [x, y]),
                "type_only": sum(1 for i in cut if i in type_only),
                "imports": [list(i) for i in cut],
            }
        )
    return {
        "graph": graph,
        "imports": imports,
        "type_only": type_only,
        "problems": problems,
        "cyclic": sorted(dep_id(x, y) for (_, x, y) in cyclic_deps(imports)),
    }


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def short(module: str, ancestor: str) -> str:
    return module[len(ancestor) + 1 :] if module.startswith(ancestor + ".") else module


def cmd_scan(args) -> int:
    root = os.path.abspath(args.root)
    result = analyse(root, args.package)
    problems = result["problems"]
    prev = load_json(state_path(root, STATE_FILE), {})
    decisions = load_json(state_path(root, DECISIONS_JSON), [])

    prev_cyclic = set(prev.get("cyclic", []))
    now_cyclic = set(result["cyclic"])
    diff = {
        "first_scan": not prev,
        "resolved_problems": sorted(set(prev.get("problems", [])) - {p["id"] for p in problems}),
        "new_cyclic_deps": sorted(now_cyclic - prev_cyclic) if prev else [],
    }

    active = prev.get("active")
    active_open = False
    if active:
        d = next((d for d in decisions if d["id"] == active), None)
        if d:
            active_open = any(within(i, d["lower"]) and within(j, d["higher"]) for i, j in result["imports"])
    violations = sorted({f"{did}: {i} -> {j}" for did, (i, j) in decision_violations(result["imports"], decisions)})
    if active and active_open:
        violations = [v for v in violations if not v.startswith(active + ":")]

    for n, p in enumerate(problems, 1):
        p["n"] = f"P{n}"

    report = {
        "package": args.package,
        "guard": guard_present(root),
        "active": active if active_open else None,
        "decision_violations": violations,
        "diff": diff,
        "cyclic_deps": len(now_cyclic),
        "problems": problems,
    }

    if args.write_state:
        save_json(
            state_path(root, STATE_FILE),
            {
                "package": args.package,
                "scanned_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "problems": [p["id"] for p in problems],
                "cyclic": result["cyclic"],
                "active": active if active_open else None,
            },
        )

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0

    out = [f"# decycle scan: `{args.package}`", ""]
    out.append(f"- import-linter guard: {'present' if report['guard'] else 'absent'}")
    out.append(f"- cyclic sibling dependencies: {report['cyclic_deps']}; problems to cut: {len(problems)}")
    if diff["first_scan"]:
        out.append("- first scan (no previous state)")
    else:
        out.append(f"- resolved since last scan: {', '.join(diff['resolved_problems']) or 'none'}")
        out.append(f"- NEW cyclic dependencies since last scan: {', '.join(diff['new_cyclic_deps']) or 'none'}")
    if report["active"]:
        out.append(f"- ACTIVE problem still open: {report['active']}")
    if violations:
        out.append("- decisions broken by imports outside the active problem:")
        out.extend(f"  - {v}" for v in violations)
    out.append("")
    if problems:
        out.append("| # | in | dependency to cut | cut | reverse | scc | depth | churn90 | type_only |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for p in problems:
            a = p["ancestor"]
            ch = "-" if p["churn90"] is None else p["churn90"]
            out.append(
                f"| {p['n']} | `{a}` | `{short(p['importer'], a)}` → `{short(p['imported'], a)}` "
                f"| {p['cut']} | {p['reverse']} | {p['scc']} | {p['depth']} | {ch} | {p['type_only']} |"
            )
    else:
        out.append("No cycles between sibling packages. Nothing to untangle.")
    print("\n".join(out))
    return 0


def _resolve_problem(problems: list[dict], ref: str) -> dict:
    for n, p in enumerate(problems, 1):
        if ref in (p["id"], f"P{n}"):
            return p
    raise SystemExit(f"decycle: no open problem {ref!r}; run scan for the current list")


def cmd_detail(args) -> int:
    root = os.path.abspath(args.root)
    result = analyse(root, args.package)
    p = _resolve_problem(result["problems"], args.problem)
    graph, type_only = result["graph"], result["type_only"]
    pairs = sibling_deps(result["imports"])[p["ancestor"]]
    comp = next((c for c in sccs(set(pairs)) if p["importer"] in c), set())

    def lines(x: str, y: str) -> list[str]:
        rows = []
        for importer, imported in pairs.get((x, y), []):
            tag = " [TYPE_CHECKING]" if (importer, imported) in type_only else ""
            for d in graph.get_import_details(importer=importer, imported=imported):
                rows.append(
                    f"- `{importer}` -> `{imported}` line {d['line_number']}{tag}: `{d['line_contents'].strip()}`"
                )
        return rows or ["- none"]

    out = [
        f"# {p['id']}",
        "",
        f"Siblings under `{p['ancestor']}`. Cycle members: {', '.join(f'`{m}`' for m in sorted(comp))}.",
        "",
        f"## {short(p['importer'], p['ancestor'])} → {short(p['imported'], p['ancestor'])} (nominated cut, {p['cut']})",
        *lines(p["importer"], p["imported"]),
        "",
        f"## {short(p['imported'], p['ancestor'])} → {short(p['importer'], p['ancestor'])} (reverse, {p['reverse']})",
        *lines(p["imported"], p["importer"]),
        "",
        "## Other dependencies inside this cycle",
    ]
    others = [
        f"- `{short(x, p['ancestor'])}` → `{short(y, p['ancestor'])}` ({len(v)})"
        for (x, y), v in sorted(pairs.items())
        if x in comp and y in comp and {x, y} != {p["importer"], p["imported"]}
    ]
    out.extend(others or ["- none"])
    print("\n".join(out))
    return 0


def apply_op(modules: set[str], imports: set[Import], op: dict) -> None:
    kind = op.get("op")
    if kind == "add_module":
        m = op["module"]
        if m in modules:
            raise ValueError(f"add_module: {m} already exists")
        parts = m.split(".")
        for k in range(1, len(parts) + 1):
            modules.add(".".join(parts[:k]))
    elif kind == "remove_module":
        m = op["module"]
        if m not in modules:
            raise ValueError(f"remove_module: {m} does not exist")
        modules.discard(m)
        for imp in [i for i in imports if m in i]:
            imports.discard(imp)
    elif kind in ("add_import", "remove_import"):
        imp = (op["importer"], op["imported"])
        for m in imp:
            if m not in modules:
                raise ValueError(f"{kind}: module {m} does not exist (add_module first)")
        if kind == "add_import":
            if imp[0] == imp[1]:
                raise ValueError("add_import: a module cannot import itself")
            imports.add(imp)
        else:
            if imp not in imports:
                raise ValueError(f"remove_import: {imp[0]} does not import {imp[1]}")
            imports.discard(imp)
    elif kind == "merge_module":
        src, dst = op["source"], op["target"]
        for m in (src, dst):
            if m not in modules:
                raise ValueError(f"merge_module: {m} does not exist")
        moved = {(dst if i == src else i, dst if j == src else j) for i, j in imports}
        imports.clear()
        imports.update(i for i in moved if i[0] != i[1])
        modules.discard(src)
    else:
        raise ValueError(f"unknown op {kind!r}")


def simulate(modules: set[str], imports: set[Import], plan: dict, decisions: list[dict]) -> dict:
    """Pure check of a plan; returns {"ok": bool, "steps": [...], "errors": [...]}."""
    modules, imports = set(modules), set(imports)
    target = parse_id(plan["remove"])
    cyclic = cyclic_deps(imports)
    violations = decision_violations(imports, decisions)
    start_cyclic = len(cyclic)
    report = {"ok": True, "steps": [], "errors": []}

    for step in plan["steps"]:
        sid = step.get("id", "?")
        errors = []
        try:
            for op in step["ops"]:
                apply_op(modules, imports, op)
        except (ValueError, KeyError) as e:
            errors.append(f"step {sid}: {e}")
        now_cyclic = cyclic_deps(imports)
        for a, x, y in sorted(now_cyclic - cyclic):
            errors.append(f"step {sid}: adds cyclic dependency {dep_id(x, y)} under {a}")
        now_viol = decision_violations(imports, decisions)
        for did, (i, j) in sorted(now_viol - violations):
            errors.append(f"step {sid}: {i} -> {j} breaks decision {did}")
        report["steps"].append({"id": sid, "cyclic_deps": len(now_cyclic), "errors": errors})
        report["errors"].extend(errors)
        cyclic, violations = now_cyclic, now_viol

    left = sorted(f"{i} -> {j}" for i, j in imports if within(i, target[0]) and within(j, target[1]))
    if left:
        report["errors"].append(f"end: {plan['remove']} still has imports: {', '.join(left)}")
    report["ok"] = not report["errors"]
    report["cyclic_deps_before"] = start_cyclic
    report["cyclic_deps_after"] = len(cyclic)
    report["imports"] = imports
    return report


def mermaid(imports: set[Import], ancestor: str) -> str:
    pairs = sibling_deps(imports).get(ancestor, {})
    cyc = {(x, y) for (a, x, y) in cyclic_deps(imports) if a == ancestor}
    lines = ["graph TD"]
    for (x, y), v in sorted(pairs.items()):
        arrow = "-. cycle .->" if (x, y) in cyc else "-->"
        lines.append(f"  {short(x, ancestor)} {arrow}|{len(v)}| {short(y, ancestor)}")
    return "\n".join(lines)


def cmd_simulate(args) -> int:
    root = os.path.abspath(args.root)
    graph = build(root, args.package)
    with open(args.plan) as f:
        plan = json.load(f)
    decisions = load_json(state_path(root, DECISIONS_JSON), [])
    rep = simulate(set(graph.modules), graph_imports(graph), plan, decisions)
    x, _ = parse_id(plan["remove"])
    ancestor = x.rpartition(".")[0]
    out = [f"# simulate: remove {plan['remove']}", ""]
    for s in rep["steps"]:
        out.append(f"- step {s['id']}: {'ok' if not s['errors'] else 'FAIL'} (cyclic deps: {s['cyclic_deps']})")
    out.append(f"- cyclic sibling dependencies: {rep['cyclic_deps_before']} → {rep['cyclic_deps_after']}")
    out.append("")
    if rep["errors"]:
        out.append("## Errors")
        out.extend(f"- {e}" for e in rep["errors"])
    else:
        out.append(f"PASS. Sibling graph of `{ancestor or x}` after the plan:")
        out.extend(["", "```mermaid", mermaid(rep["imports"], ancestor or x), "```"])
    print("\n".join(out))
    return 0 if rep["ok"] else 1


def cmd_record(args) -> int:
    root = os.path.abspath(args.root)
    lower, higher = args.lower, args.higher
    pid = dep_id(lower, higher)
    decisions = load_json(state_path(root, DECISIONS_JSON), [])
    if any(within(lower, d["higher"]) and within(higher, d["lower"]) for d in decisions):
        raise SystemExit(f"decycle: {pid} contradicts an earlier decision")
    if not any(d["id"] == pid for d in decisions):
        today = dt.date.today().isoformat()
        decisions.append(
            {"id": pid, "lower": lower, "higher": higher, "strategy": args.strategy, "rationale": args.rationale, "date": today}
        )
        save_json(state_path(root, DECISIONS_JSON), decisions)
        md = state_path(root, DECISIONS_MD)
        new = not os.path.exists(md)
        with open(md, "a") as f:
            if new:
                f.write("# Dependency direction decisions\n\nEach line: the lower package must not import the higher one.\n\n")
            f.write(f"- {today} `{lower}` must not import `{higher}` ({args.strategy}): {args.rationale}\n")
    state = load_json(state_path(root, STATE_FILE), {})
    state["active"] = pid
    save_json(state_path(root, STATE_FILE), state)
    print(f"recorded: {lower} must not import {higher}; active problem: {pid}")
    return 0


def cmd_guard(args) -> int:
    root = os.path.abspath(args.root)
    result = analyse(root, args.package)
    decisions = load_json(state_path(root, DECISIONS_JSON), [])
    ignores = sorted({f"{i} -> {j}" for p in result["problems"] for i, j in p["imports"]})
    contracts = [
        {
            "id": "decycle-acyclic",
            "name": f"No cycles between sibling packages in {args.package} (decycle baseline)",
            "type": "acyclic_siblings",
            "ancestors": [args.package],
            "ignore_imports": ignores,
        }
    ]
    for d in decisions:
        viol = sorted(f"{i} -> {j}" for _, (i, j) in decision_violations(result["imports"], [d]))
        c = {
            "id": "decycle-" + d["lower"].replace(".", "-") + "-below-" + d["higher"].rsplit(".", 1)[-1],
            "name": f"{d['lower']} must not import {d['higher']} (decycle decision {d['date']})",
            "type": "forbidden",
            "source_modules": [d["lower"]],
            "forbidden_modules": [d["higher"]],
        }
        if viol:
            c["ignore_imports"] = viol
        contracts.append(c)

    if args.format == "toml":
        out = ["[tool.importlinter]", f'root_package = "{args.package}"', ""]
        for c in contracts:
            out.append("[[tool.importlinter.contracts]]")
            for k, v in c.items():
                if isinstance(v, list):
                    out.append(f"{k} = [" + "".join(f'\n    "{x}",' for x in v) + ("\n]" if v else "]"))
                else:
                    out.append(f'{k} = "{v}"')
            out.append("")
    else:
        out = ["[importlinter]", f"root_package = {args.package}", ""]
        for c in contracts:
            out.append(f"[importlinter:contract:{c['id']}]")
            for k, v in c.items():
                if k == "id":
                    continue
                if isinstance(v, list):
                    out.append(f"{k} =" + "".join(f"\n    {x}" for x in v))
                else:
                    out.append(f"{k} = {v}")
            out.append("")
    print("\n".join(out).rstrip() + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="decycle", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--root", default=".", help="repository root (default: .)")
        p.add_argument("--package", required=True, help="root Python package, e.g. myapp")
        return p

    p = common(sub.add_parser("scan"))
    p.add_argument("--write-state", action="store_true")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.set_defaults(fn=cmd_scan)

    p = common(sub.add_parser("detail"))
    p.add_argument("--problem", required=True, help="problem id or its P-number from the last scan")
    p.set_defaults(fn=cmd_detail)

    p = common(sub.add_parser("simulate"))
    p.add_argument("--plan", required=True, help="plan JSON (see references/simulate.md)")
    p.set_defaults(fn=cmd_simulate)

    p = sub.add_parser("record")
    p.add_argument("--root", default=".")
    p.add_argument("--lower", required=True)
    p.add_argument("--higher", required=True)
    p.add_argument("--strategy", required=True)
    p.add_argument("--rationale", required=True)
    p.set_defaults(fn=cmd_record)

    p = common(sub.add_parser("guard"))
    p.add_argument("--format", choices=["ini", "toml"], default="ini")
    p.set_defaults(fn=cmd_guard)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
