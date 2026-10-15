"""Python/Django resolver for explain-flow (see ../PROTOCOL.md).

Standard library only. Checks code references with `ast` and follows the
Django hops a plain call graph misses: URL routing, signal receivers and
Celery tasks. Anything it cannot prove statically is reported `unverified`,
never `verified`.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field

SKIP_DIRS = {
    ".git", ".hg", ".venv", "venv", "env", ".env", "node_modules", "__pycache__",
    "site-packages", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache",
    "migrations", "static", "media", ".claude",
}
MAX_FILES = 5000
TASK_DECORATORS = {"shared_task", "task", "periodic_task", "actor", "job"}
TASK_CALLS = {"delay", "apply_async", "s", "si", "signature", "send", "enqueue"}
SIGNAL_TRIGGERS = {
    "send", "send_robust", "save", "create", "delete", "update_or_create",
    "get_or_create", "bulk_create", "add", "remove", "clear", "set",
}
URL_FUNCS = {"path", "re_path", "url", "register"}


# ---------------------------------------------------------------- helpers

def last_segment(code: str) -> str:
    cleaned = re.sub(r"\(.*$", "", code, flags=re.S).strip()
    parts = [p for p in re.split(r"[.#:]+", cleaned) if p]
    return parts[-1] if parts else cleaned


def attr_chain(node: ast.AST) -> list[str]:
    """`self.locks.issue_code` -> ["self", "locks", "issue_code"]."""
    out: list[str] = []
    while True:
        if isinstance(node, ast.Attribute):
            out.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Name):
            out.append(node.id)
            break
        else:
            break
    return list(reversed(out))


def decorator_names(node: ast.AST) -> list[str]:
    names = []
    for d in getattr(node, "decorator_list", []):
        chain = attr_chain(d)
        if chain:
            names.append(chain[-1])
    return names


def first_line(node: ast.AST) -> int:
    decos = getattr(node, "decorator_list", [])
    return min([node.lineno] + [d.lineno for d in decos])


def word_re(name: str) -> re.Pattern[str]:
    return re.compile(r"(^|[^A-Za-z0-9_])" + re.escape(name) + r"([^A-Za-z0-9_]|$)")


# ---------------------------------------------------------------- index

@dataclass
class Def:
    name: str
    qualname: str
    path: str
    line: int
    end: int
    kind: str  # function | method | class | assign
    decorators: list[str] = field(default_factory=list)
    node: ast.AST | None = None


@dataclass
class Parsed:
    path: str
    text: str
    lines: list[str]
    tree: ast.Module | None
    error: str | None


class Project:
    def __init__(self, root: str):
        self.root = root
        self.files: dict[str, Parsed] = {}
        self._indexed = False
        self.defs: dict[str, list[Def]] = {}
        self.receivers: dict[str, list[tuple[str, int, str, str | None]]] = {}  # handler -> (path, line, signal, sender)
        self.imports: dict[str, dict[str, str]] = {}  # path -> local name -> module
        self.top_packages: set[str] = set()
        self.routes: dict[str, list[tuple[str, int]]] = {}  # view name -> (path, line)
        self.notes: list[str] = []

    # -- files
    def parse(self, rel: str) -> Parsed | None:
        if rel in self.files:
            return self.files[rel]
        full = os.path.join(self.root, rel)
        if not os.path.isfile(full):
            return None
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        try:
            tree = ast.parse(text, filename=rel)
            err = None
        except SyntaxError as exc:  # keep going with text only
            tree, err = None, f"syntax error at line {exc.lineno}"
        parsed = Parsed(rel, text, text.split("\n"), tree, err)
        self.files[rel] = parsed
        return parsed

    def all_files(self):
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                if f.endswith(".py"):
                    count += 1
                    if count > MAX_FILES:
                        self.notes.append(f"indexed the first {MAX_FILES} Python files only")
                        return
                    yield os.path.relpath(os.path.join(dirpath, f), self.root)

    # -- project-wide index, built on first need
    def index(self):
        if self._indexed:
            return
        self._indexed = True
        for rel in self.all_files():
            self.top_packages.add(rel.split(os.sep)[0].removesuffix(".py"))
            p = self.parse(rel)
            if p and p.tree:
                self._index_tree(p)

    def _add_def(self, d: Def):
        self.defs.setdefault(d.name, []).append(d)

    def _index_tree(self, p: Parsed):
        project = self

        class V(ast.NodeVisitor):
            def __init__(self):
                self.stack: list[str] = []

            def _def(self, node, kind):
                qual = ".".join(self.stack + [node.name])
                project._add_def(Def(node.name, qual, p.path, node.lineno,
                                     getattr(node, "end_lineno", node.lineno), kind,
                                     decorator_names(node), node))
                for d in node.decorator_list:
                    if isinstance(d, ast.Call) and attr_chain(d.func)[-1:] == ["receiver"] and d.args:
                        sig = ".".join(attr_chain(d.args[0])) or "signal"
                        sender = next((".".join(attr_chain(k.value)) for k in d.keywords if k.arg == "sender"), None)
                        project.receivers.setdefault(node.name, []).append((p.path, node.lineno, sig, sender))
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_FunctionDef(self, node):
                self._def(node, "method" if self.stack else "function")

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node):
                self._def(node, "class")

            def visit_Import(self, node):
                for a in node.names:
                    project.imports.setdefault(p.path, {})[(a.asname or a.name).split(".")[0]] = a.name

            def visit_ImportFrom(self, node):
                mod = ("." * node.level) + (node.module or "")
                for a in node.names:
                    project.imports.setdefault(p.path, {})[a.asname or a.name] = mod

            def visit_Assign(self, node):
                if not self.stack:
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            project._add_def(Def(t.id, t.id, p.path, node.lineno,
                                                 getattr(node, "end_lineno", node.lineno), "assign"))
                self.generic_visit(node)

            def visit_Call(self, node):
                chain = attr_chain(node.func)
                if chain and chain[-1] == "connect" and node.args:
                    handler = attr_chain(node.args[0])
                    if handler:
                        sig = ".".join(chain[:-1]) or "signal"
                        sender = next((".".join(attr_chain(k.value)) for k in node.keywords if k.arg == "sender"), None)
                        project.receivers.setdefault(handler[-1], []).append((p.path, node.lineno, sig, sender))
                if chain and chain[-1] in URL_FUNCS:
                    for arg in list(node.args[1:]) + [kw.value for kw in node.keywords]:
                        target = attr_chain(arg)
                        target = [t for t in target if t not in ("as_view", "views")]
                        if target:
                            project.routes.setdefault(target[-1], []).append((p.path, node.lineno))
                self.generic_visit(node)

        V().visit(p.tree)

    def defs_named(self, name: str) -> list[Def]:
        self.index()
        return self.defs.get(name, [])


# ---------------------------------------------------------------- verify

def calls_near(p: Parsed, line: int, end: int, slack: int = 2) -> list[tuple[ast.Call, list[str]]]:
    out = []
    if not p.tree:
        return out
    lo, hi = line - slack, end + slack
    for node in ast.walk(p.tree):
        if isinstance(node, ast.Call):
            s, e = node.lineno, getattr(node, "end_lineno", node.lineno)
            if s <= hi and e >= lo:
                out.append((node, attr_chain(node.func)))
    out.sort(key=lambda c: abs(c[0].lineno - line))
    return out


def where(defs: list[Def], limit: int = 3) -> str:
    shown = ", ".join(f"{d.qualname} at {d.path}:{d.line}" for d in defs[:limit])
    more = f" (+{len(defs) - limit} more)" if len(defs) > limit else ""
    return shown + more


def check_def(proj: Project, p: Parsed, c: dict) -> dict:
    name = last_segment(c["code"])
    line, end = c["line"], c.get("end", c["line"])
    if not p.tree:
        return text_fallback(p, c, name, p.error or "unparsable")
    local: list[ast.AST] = []
    for node in ast.walk(p.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            local.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            local.append(node)
    for node in local:
        start = first_line(node) if hasattr(node, "decorator_list") else node.lineno
        if start - 1 <= line <= node.lineno + 3 or (start <= line and end <= getattr(node, "end_lineno", node.lineno)):
            return {"status": "ok", "reason": f"{name} defined at line {node.lineno}"}
    if local:
        lines = ", ".join(str(n.lineno) for n in local)
        return {"status": "error", "reason": f"{name} is defined at line {lines} of {c['path']}, not at {line}"}
    elsewhere = proj.defs_named(name)
    if elsewhere:
        return {"status": "error", "reason": f"{name} is not defined in {c['path']}; found {where(elsewhere)}"}
    return {"status": "error", "reason": f"no definition of {name} in the project"}


def check_call(proj: Project, p: Parsed, c: dict) -> dict:
    code = c.get("code")
    if not code:
        return {"status": "ok"}
    name = last_segment(code)
    line, end = c["line"], c.get("end", c["line"])
    via = c.get("via") or "call"
    if not p.tree:
        return text_fallback(p, c, name, p.error or "unparsable")

    near = calls_near(p, line, end)

    # direct call: foo(...), obj.foo(...), Foo(...)
    for node, chain in near:
        if chain and chain[-1] == name:
            defs = proj.defs_named(name)
            target = f"; defined as {where(defs)}" if defs else "; defined outside the project"
            amb = " (name is ambiguous)" if len(defs) > 1 else ""
            return {"status": "verified", "reason": f"call to {'.'.join(chain)} at line {node.lineno}{target}{amb}"}

    # task: foo.delay(...), foo.apply_async(...)
    for node, chain in near:
        if len(chain) >= 2 and chain[-1] in TASK_CALLS and chain[-2] == name:
            defs = [d for d in proj.defs_named(name) if set(d.decorators) & TASK_DECORATORS]
            if defs:
                return {"status": "verified", "reason": f"{chain[-2]}.{chain[-1]} at line {node.lineno} enqueues task {where(defs)}"}
            return {"status": "unverified", "reason": f"{chain[-2]}.{chain[-1]} at line {node.lineno}; no task-decorated {name} found"}

    # signal: the call site sends a signal or saves a model; the callee is a registered receiver
    if via in ("signal", "orm", "event") or any(ch and ch[-1] in SIGNAL_TRIGGERS for _, ch in near):
        proj.index()
        recv = proj.receivers.get(name)
        trigger = next(((n, ch) for n, ch in near if ch and ch[-1] in SIGNAL_TRIGGERS), None)
        if recv and trigger:
            r = ", ".join(f"{path}:{ln} on {sig}" + (f" for sender {snd}" if snd else "")
                          for path, ln, sig, snd in recv[:3])
            return {"status": "verified", "reason": f"{'.'.join(trigger[1])} at line {trigger[0].lineno} reaches receiver {name} registered at {r}"}
        if recv:
            return {"status": "unverified", "reason": f"{name} is a receiver ({recv[0][0]}:{recv[0][1]}) but no send/save near line {line}"}

    # url: the callee view is routed in a urls module
    if via in ("url", "http"):
        proj.index()
        # `RebookView.post` is reached through the route of `RebookView`
        segments = [x for x in re.split(r"[.#:]+", re.sub(r"\(.*$", "", code, flags=re.S)) if x]
        for seg in reversed(segments):
            routes = proj.routes.get(seg)
            if routes:
                r = ", ".join(f"{path}:{ln}" for path, ln in routes[:3])
                return {"status": "verified", "reason": f"{seg} is routed at {r}"}

    return text_fallback(p, c, name, "no static call resolves it (dynamic dispatch or framework hop)")


def text_fallback(p: Parsed, c: dict, name: str, why: str) -> dict:
    line, end = c["line"], c.get("end", c["line"])
    rx = word_re(name)
    lo, hi = max(0, line - 4), min(len(p.lines), end + 3)
    for i in range(lo, hi):
        if rx.search(p.lines[i]):
            return {"status": "unverified", "reason": f"{name} named at line {i + 1}; {why}"}
    for i, l in enumerate(p.lines):
        if rx.search(l):
            return {"status": "error", "reason": f"{name} is not near line {line}; it appears at line {i + 1}"}
    return {"status": "error", "reason": f"{name} does not appear in {c['path']}"}


def verify(req: dict) -> dict:
    proj = Project(req["root"])
    results = {}
    for c in req.get("checks", []):
        key = str(c["key"])
        p = proj.parse(c["path"])
        if p is None:
            results[key] = {"status": "error", "reason": f"{c['path']} does not exist"}
            continue
        end = c.get("end", c["line"])
        if end > len(p.lines):
            results[key] = {"status": "error", "reason": f"{c['path']} has {len(p.lines)} lines; line {end} is past the end"}
            continue
        role = c.get("role", "any")
        try:
            if role == "def" and c.get("code"):
                results[key] = check_def(proj, p, c)
            elif role == "call":
                results[key] = check_call(proj, p, c)
            else:
                results[key] = {"status": "ok"}
        except Exception as exc:  # one bad check must not sink the batch
            results[key] = text_fallback(p, c, last_segment(c.get("code") or ""), f"resolver failed: {exc}") \
                if c.get("code") else {"status": "ok"}
    return {"results": results, "notes": proj.notes}


# ---------------------------------------------------------------- seed

def enclosing_def(p: Parsed, line: int) -> ast.AST | None:
    best = None
    for node in ast.walk(p.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if first_line(node) <= line <= getattr(node, "end_lineno", node.lineno):
                if best is None or node.lineno > best.lineno:
                    best = node
    return best


def owner_class(proj: Project, d: Def) -> str | None:
    parts = d.qualname.split(".")
    return parts[-2] if d.kind == "method" and len(parts) >= 2 else None


def seed(req: dict) -> dict:
    proj = Project(req["root"])
    entry = req["entry"]
    m = re.match(r"^(.*?):(\d+)", entry)
    if not m:
        return {"error": f"entry {entry!r} is not path:line"}
    path, line = m.group(1), int(m.group(2))
    p = proj.parse(path)
    if p is None or p.tree is None:
        return {"error": f"cannot parse {path}"}
    start = enclosing_def(p, line)
    if start is None:
        return {"error": f"no function contains {entry}"}
    proj.index()
    depth = int(req.get("depth", 3))
    max_nodes = int(req.get("maxNodes", 120))

    start_def = next((d for d in proj.defs_named(start.name) if d.path == path and d.line == start.lineno), None)
    if start_def is None:
        return {"error": f"could not index {start.name}"}

    functions: dict[str, dict] = {}
    edges: list[dict] = []

    def fid(d: Def) -> str:
        return f"{d.path}:{d.line}"

    def add_fn(d: Def):
        functions.setdefault(fid(d), {"id": fid(d), "qualname": d.qualname, "path": d.path, "line": d.line,
                                       "decorators": d.decorators})

    ORM_SIGNALS = {"save": ("pre_save", "post_save"), "create": ("pre_save", "post_save"),
                   "update_or_create": ("pre_save", "post_save"), "get_or_create": ("pre_save", "post_save"),
                   "delete": ("pre_delete", "post_delete")}

    def is_external(chain: list[str], caller: Def) -> bool:
        """`requests.post`, `json.dumps`: the receiver is an imported non-project module."""
        if len(chain) < 2 or chain[0] in ("self", "cls"):
            return False
        mod = proj.imports.get(caller.path, {}).get(chain[0])
        if mod is None or mod.startswith("."):
            return False
        return mod.split(".")[0] not in proj.top_packages

    def resolve(chain: list[str], caller: Def) -> tuple[list[Def], str]:
        name = chain[-1]
        if len(chain) >= 2 and name in TASK_CALLS:
            tasks = [d for d in proj.defs_named(chain[-2]) if set(d.decorators) & TASK_DECORATORS]
            if tasks:
                return tasks, "task"
        if is_external(chain, caller):
            return [], "call"
        cands = [d for d in proj.defs_named(name) if d.kind in ("function", "method", "class")]
        if chain[0] in ("self", "cls") and len(chain) == 2:
            own = owner_class(proj, caller)
            same = [d for d in cands if owner_class(proj, d) == own]
            if same:
                cands = same
        elif len(chain) >= 2:
            cands = [d for d in cands if d.kind == "method"] or cands
        # calling a class runs its __init__; never walk the whole class body
        resolved = []
        for d in cands:
            if d.kind == "class":
                init = [x for x in proj.defs_named("__init__") if x.qualname == f"{d.qualname}.__init__" and x.path == d.path]
                resolved.append(init[0] if init else Def(d.name, d.qualname, d.path, d.line, d.end, "class", d.decorators, None))
            else:
                resolved.append(d)
        return resolved, "call"

    def follow(target: Def, lvl: int):
        add_fn(target)
        if fid(target) not in seen:
            seen.add(fid(target))
            frontier.append((target, lvl + 1))

    frontier = [(start_def, 0)]
    add_fn(start_def)
    seen = {fid(start_def)}
    while frontier and len(functions) < max_nodes:
        d, lvl = frontier.pop(0)
        if lvl >= depth or d.node is None:
            continue
        for node in ast.walk(d.node):
            if not isinstance(node, ast.Call):
                continue
            chain = attr_chain(node.func)
            if not chain:
                continue
            base = {"from": fid(d), "name": ".".join(chain), "line": node.lineno}
            if chain[-1] in ("send", "send_robust") and len(chain) >= 2:
                # signal.send(...): every receiver registered on a signal of that name
                for handler, rs in proj.receivers.items():
                    for hpath, hline, sig, sender in rs:
                        if sig.split(".")[-1] != chain[-2]:
                            continue
                        target = next((x for x in proj.defs_named(handler) if x.path == hpath), None)
                        edges.append({**base, "via": "signal", "to": fid(target) if target else None,
                                      "receiver": f"{handler} registered at {hpath}:{hline} on {sig}"})
                        if target:
                            follow(target, lvl)
                continue
            if chain[-1] in ORM_SIGNALS and len(chain) >= 2 and not is_external(chain, d):
                # model.save()/.create()/.delete(): Django sends model signals; list receivers that may fire
                wanted = ORM_SIGNALS[chain[-1]]
                for handler, rs in proj.receivers.items():
                    for hpath, hline, sig, sender in rs:
                        if sig.split(".")[-1] not in wanted:
                            continue
                        if sender and chain[0][:1].isupper() and sender.split(".")[-1] != chain[0]:
                            continue  # AccessCode.objects.create() does not reach a receiver for Booking
                        target = next((x for x in proj.defs_named(handler) if x.path == hpath), None)
                        edges.append({**base, "via": "signal", "to": fid(target) if target else None,
                                      "possible": True,
                                      "receiver": f"{handler} registered at {hpath}:{hline} on {sig}"
                                                  + (f" for sender {sender}" if sender else "")})
                        if target:
                            follow(target, lvl)
            cands, via = resolve(chain, d)
            if not cands:
                continue  # library or builtin call: not part of the map
            edge = {**base, "via": via}
            if len(cands) == 1:
                edge["to"] = fid(cands[0])
                follow(cands[0], lvl)
            else:
                edge["to"] = None
                edge["candidates"] = [f"{c.qualname} {c.path}:{c.line}" for c in cands[:5]]
            edges.append(edge)
    notes = list(proj.notes)
    notes.append("Static map only: dynamic dispatch and URL routing may add hops not listed here; "
                 "signal edges marked possible depend on the sender at run time.")
    return {"functions": list(functions.values()), "edges": edges, "notes": notes}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
    req = json.load(sys.stdin)
    if mode == "verify":
        out = verify(req)
    elif mode == "seed":
        out = seed(req)
    else:
        print(json.dumps({"error": f"unknown mode {mode}"}))
        return 2
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
