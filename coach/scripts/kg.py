#!/usr/bin/env python3
"""coach state: the knowledge graph and the ticket ledger under the coach home.

The coach home is $COACH_HOME, else ~/.claude/coach. It holds:
  knowledge.md    concept graph: namespaced ids, prerequisite edges, evidence, misconceptions
  tickets.jsonl   one line per coached ticket: interventions, gate regressions, commits, post-deploy
  profiles/       user-drafted stack profiles (see coach/STATE.md)
  reports/        self-evaluation reports

Mastery, Leitner box and next review are DERIVED by replaying a concept's evidence. They are
never set directly: `validate` rejects a file whose stored values disagree with the replay.

  kg.py init
  kg.py validate
  kg.py add-concept ID --title T [--requires A,B]
  kg.py link ID --requires A,B
  kg.py record ID --kind KIND --ref REF [--note N] [--date D] [--unverified]
  kg.py misconception ID --ref REF --quote Q [--date D]
  kg.py show ID
  kg.py prereqs ID                    transitive prerequisites and whether each is verified
  kg.py due [--date D] [--namespace NS]
  kg.py ticket open ID --repo R --stacks a,b [--profile-status verified|draft]
  kg.py ticket intervene ID --kind gap|hint|correction|example --note N
  kg.py ticket gate-regression ID --gate G --note N
  kg.py ticket commit ID --sha SHA [--kind behavior|refactor|test]
  kg.py ticket revert ID --sha SHA --note N     a revert or hotfix landed on one of the ticket's commits
  kg.py ticket close ID
  kg.py ticket postdeploy ID --status verified|unverified|regression --ref REF
  kg.py ticket pending-postdeploy [--repo R]
  kg.py ticket show ID
  kg.py report [--window N]           per-stack metrics over the last N closed tickets (default 10)
  kg.py commit -m MSG                 git commit everything in the coach home

Standard library only.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

MASTERY = ["unseen", "exposed", "practiced", "retained"]
INTERVALS = {1: 1, 2: 3, 3: 7, 4: 21, 5: 60}  # Leitner box -> days until next review
DELAY_DAYS = 7          # a probe at least this long after the previous evidence counts as delayed
RETAIN_PASSES = 2       # delayed probe passes needed for "retained"
KINDS = {
    "explained": "exposure: an explanation or example was shown",
    "probe-pass": "execution-graded probe passed",
    "probe-fail": "execution-graded probe failed",
    "diff-correct": "correct use observed in the user's own diff, gates green",
    "diff-incorrect": "incorrect use observed in the user's own diff",
    "prereq-pass": "targeted prerequisite question answered correctly (no mastery change)",
    "prereq-fail": "targeted prerequisite question answered incorrectly (no mastery change)",
}
INTERVENTIONS = ["gap", "hint", "correction", "example"]
ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
HEADER = """# Coach knowledge graph

<!-- Managed by coach/scripts/kg.py. Edit only through it: mastery, box and next_review are
     replayed from evidence, and `kg.py validate` rejects hand edits that disagree. -->
"""


def home():
    return os.path.expanduser(os.environ.get("COACH_HOME", "~/.claude/coach"))


def today():
    return dt.date.today()


def parse_date(s):
    return dt.date.fromisoformat(s) if s else today()


def clean(s):
    return (s or "").replace("|", "¦").replace("\n", " ").strip()


class Fail(Exception):
    pass


# ---------------------------------------------------------------- knowledge.md

def new_concept(cid, title="", requires=None):
    return {"id": cid, "title": title, "requires": list(requires or []),
            "mastery": "unseen", "box": 0, "next_review": None,
            "evidence": [], "misconceptions": []}


def parse_knowledge(text):
    concepts, cur, section = {}, None, None
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            cid = line[3:].strip()
            if cid in concepts:
                raise Fail(f"line {n}: duplicate concept {cid}")
            cur = concepts[cid] = new_concept(cid)
            section = None
            continue
        if cur is None or not line.strip() or line.lstrip().startswith("<!--"):
            continue
        if line in ("evidence:", "misconceptions:"):
            section = line[:-1]
            continue
        if line.startswith("- ") and section:
            parts = [p.strip() for p in line[2:].split(" | ")]
            if section == "evidence":
                if len(parts) < 3:
                    raise Fail(f"line {n}: evidence needs date | kind | ref [| note] [| unverified]")
                cur["evidence"].append({
                    "date": parts[0], "kind": parts[1], "ref": parts[2],
                    "note": parts[3] if len(parts) > 3 else "",
                    "unverified": len(parts) > 4 and parts[4] == "unverified"})
            else:
                if len(parts) != 3:
                    raise Fail(f"line {n}: misconception needs date | ref | \"quote\"")
                cur["misconceptions"].append({"date": parts[0], "ref": parts[1],
                                              "quote": parts[2].strip('"')})
            continue
        m = re.match(r"^(title|requires|mastery|box|next_review):\s*(.*)$", line)
        if not m:
            raise Fail(f"line {n}: unrecognized line in {cur['id']}: {line!r}")
        key, val = m.groups()
        section = None
        if key == "requires":
            cur["requires"] = [x.strip() for x in val.split(",") if x.strip()]
        elif key == "box":
            cur["box"] = int(val)
        elif key == "next_review":
            cur["next_review"] = None if val.strip() in ("", "-") else val.strip()
        else:
            cur[key] = val.strip()
    return concepts


def render_knowledge(concepts):
    out = [HEADER]
    for cid in sorted(concepts):
        c = concepts[cid]
        out.append(f"## {cid}")
        out.append(f"title: {c['title']}")
        out.append(f"requires: {', '.join(c['requires'])}")
        out.append(f"mastery: {c['mastery']}")
        out.append(f"box: {c['box']}")
        out.append(f"next_review: {c['next_review'] or '-'}")
        if c["evidence"]:
            out.append("evidence:")
            for e in c["evidence"]:
                row = [e["date"], e["kind"], clean(e["ref"]), clean(e["note"])]
                if e["unverified"]:
                    row.append("unverified")
                out.append("- " + " | ".join(row))
        if c["misconceptions"]:
            out.append("misconceptions:")
            for m in c["misconceptions"]:
                out.append(f"- {m['date']} | {clean(m['ref'])} | \"{clean(m['quote'])}\"")
        out.append("")
    return "\n".join(out)


def replay(evidence):
    """Derive mastery, box, next_review and per-probe delay flags from evidence alone."""
    mastery, box, nxt, delayed_passes, last = "unseen", 0, None, 0, None
    probes = []
    for e in sorted(evidence, key=lambda e: e["date"]):
        if e["unverified"] or e["kind"] in ("prereq-pass", "prereq-fail"):
            continue
        d = dt.date.fromisoformat(e["date"])
        k = e["kind"]
        if k == "explained":
            if mastery == "unseen":
                mastery = "exposed"
        elif k == "probe-pass":
            delayed = last is not None and (d - last).days >= DELAY_DAYS
            probes.append((e["date"], True, delayed))
            box = min(box + 1, 5)
            nxt = d + dt.timedelta(days=INTERVALS[box])
            if mastery in ("unseen", "exposed"):
                mastery = "practiced"
            if delayed:
                delayed_passes += 1
            if mastery == "practiced" and delayed_passes >= RETAIN_PASSES:
                mastery = "retained"
        elif k in ("probe-fail", "diff-incorrect"):
            if k == "probe-fail":
                probes.append((e["date"], False, last is not None and (d - last).days >= DELAY_DAYS))
            box, nxt, delayed_passes = 1, d + dt.timedelta(days=1), 0
            if mastery == "retained":
                mastery = "practiced"
        elif k == "diff-correct":
            if mastery in ("unseen", "exposed"):
                mastery = "practiced"
            box = max(box, 1)
            nxt = d + dt.timedelta(days=INTERVALS[box])
        last = d
    return {"mastery": mastery, "box": box,
            "next_review": nxt.isoformat() if nxt else None, "probes": probes}


def problems(concepts):
    errs = []
    for cid, c in concepts.items():
        if not ID_RE.match(cid):
            errs.append(f"{cid}: id must be namespaced lowercase, e.g. django.orm.select_related")
        if c["mastery"] not in MASTERY:
            errs.append(f"{cid}: mastery {c['mastery']!r} not in {MASTERY}")
        for r in c["requires"]:
            if r not in concepts:
                errs.append(f"{cid}: requires unknown concept {r}")
            if r == cid:
                errs.append(f"{cid}: requires itself")
        for e in c["evidence"]:
            if e["kind"] not in KINDS:
                errs.append(f"{cid}: unknown evidence kind {e['kind']!r}")
            if not e["ref"]:
                errs.append(f"{cid}: evidence on {e['date']} has no ref")
            try:
                dt.date.fromisoformat(e["date"])
            except ValueError:
                errs.append(f"{cid}: bad evidence date {e['date']!r}")
        if errs:
            continue
        r = replay(c["evidence"])
        for key in ("mastery", "box", "next_review"):
            if c[key] != r[key]:
                errs.append(f"{cid}: stored {key}={c[key]!r} but evidence gives {r[key]!r}")
    # cycles
    state = {}

    def visit(n, stack):
        state[n] = 1
        for r in concepts[n]["requires"]:
            if r not in concepts:
                continue
            if state.get(r) == 1:
                errs.append("prerequisite cycle: " + " -> ".join(stack + [n, r]))
            elif not state.get(r):
                visit(r, stack + [n])
        state[n] = 2
    for n in concepts:
        if not state.get(n):
            visit(n, [])
    return errs


def kpath():
    return os.path.join(home(), "knowledge.md")


def load():
    p = kpath()
    if not os.path.exists(p):
        raise Fail(f"{p} missing: run `kg.py init`")
    with open(p, encoding="utf-8") as f:
        return parse_knowledge(f.read())


def save(concepts):
    for c in concepts.values():
        r = replay(c["evidence"])
        c["mastery"], c["box"], c["next_review"] = r["mastery"], r["box"], r["next_review"]
    errs = problems(concepts)
    if errs:
        raise Fail("refusing to write knowledge.md:\n  " + "\n  ".join(errs))
    tmp = kpath() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render_knowledge(concepts))
    os.replace(tmp, kpath())


def need(concepts, cid):
    if cid not in concepts:
        raise Fail(f"unknown concept {cid}: add it first with add-concept")
    return concepts[cid]


def ids(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


# ---------------------------------------------------------------- tickets.jsonl

def tpath():
    return os.path.join(home(), "tickets.jsonl")


def load_tickets():
    if not os.path.exists(tpath()):
        return []
    with open(tpath(), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save_tickets(ts):
    tmp = tpath() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for t in ts:
            f.write(json.dumps(t, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, tpath())


def find_ticket(ts, tid, repo=None):
    hits = [t for t in ts if t["id"] == tid and (repo is None or t["repo"] == repo)]
    if not hits:
        raise Fail(f"no ticket {tid}: open it with `ticket open`")
    return hits[-1]


# ---------------------------------------------------------------- commands

def cmd_init(a):
    h = home()
    for sub in ("", "profiles", "reports"):
        os.makedirs(os.path.join(h, sub), exist_ok=True)
    if not os.path.exists(kpath()):
        with open(kpath(), "w", encoding="utf-8") as f:
            f.write(HEADER)
    if not os.path.exists(tpath()):
        open(tpath(), "w").close()
    if not os.path.isdir(os.path.join(h, ".git")):
        subprocess.run(["git", "init", "-q", h], check=True)
    print(h)


def cmd_validate(a):
    errs = problems(load())
    for t in load_tickets():
        for k in ("id", "repo", "stacks", "opened"):
            if k not in t:
                errs.append(f"ticket {t.get('id')}: missing {k}")
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    print("ok")


def cmd_add_concept(a):
    cs = load()
    if a.id in cs:
        raise Fail(f"{a.id} exists")
    reqs = ids(a.requires)
    for r in reqs:
        need(cs, r)
    cs[a.id] = new_concept(a.id, a.title, reqs)
    save(cs)
    print(f"added {a.id} (unseen)")


def cmd_link(a):
    cs = load()
    c = need(cs, a.id)
    for r in ids(a.requires):
        need(cs, r)
        if r not in c["requires"]:
            c["requires"].append(r)
    save(cs)
    print(f"{a.id} requires {', '.join(c['requires'])}")


def cmd_record(a):
    if a.kind not in KINDS:
        raise Fail(f"kind must be one of {', '.join(KINDS)}")
    cs = load()
    c = need(cs, a.id)
    before = c["mastery"]
    c["evidence"].append({"date": parse_date(a.date).isoformat(), "kind": a.kind,
                          "ref": a.ref, "note": a.note or "", "unverified": a.unverified})
    save(cs)
    c = load()[a.id]
    flag = " (unverified: no mastery change)" if a.unverified else ""
    print(f"{a.id}: {before} -> {c['mastery']}, box {c['box']}, next review {c['next_review'] or '-'}{flag}")


def cmd_misconception(a):
    cs = load()
    need(cs, a.id)["misconceptions"].append(
        {"date": parse_date(a.date).isoformat(), "ref": a.ref, "quote": a.quote})
    save(cs)
    print(f"{a.id}: misconception recorded")


def cmd_show(a):
    c = need(load(), a.id)
    print(json.dumps(c, indent=2, ensure_ascii=False))


def cmd_prereqs(a):
    cs = load()
    need(cs, a.id)
    seen, order = set(), []

    def walk(n):
        for r in cs[n]["requires"]:
            if r not in seen:
                seen.add(r)
                walk(r)
                order.append(r)
    walk(a.id)
    for r in order:
        c = cs[r]
        checks = [e for e in c["evidence"] if e["kind"] in ("prereq-pass", "prereq-fail")]
        last_check = f", last check {checks[-1]['kind']} {checks[-1]['date']}" if checks else ""
        ok = c["mastery"] in ("practiced", "retained")
        print(f"{'verified  ' if ok else 'UNVERIFIED'} {r} [{c['mastery']}]{last_check}")


def cmd_due(a):
    cs = load()
    d = parse_date(a.date).isoformat()
    rows = []
    for cid, c in sorted(cs.items()):
        if a.namespace and not cid.startswith(a.namespace + "."):
            continue
        if c["next_review"] and c["next_review"] <= d:
            rows.append((c["next_review"], cid, c))
    for nr, cid, c in sorted(rows):
        refs = sorted({e["ref"] for e in c["evidence"] if e["ref"]})[-3:]
        print(f"{nr} {cid} [{c['mastery']}, box {c['box']}] refs: {'; '.join(refs)}")
        for m in c["misconceptions"]:
            print(f"    misconception {m['date']}: \"{m['quote']}\"")
    if not rows:
        print("nothing due")


def cmd_ticket(a):
    ts = load_tickets()
    now = today().isoformat()
    if a.tcmd == "open":
        if any(t["id"] == a.id and t["repo"] == a.repo and not t.get("closed") for t in ts):
            raise Fail(f"ticket {a.id} already open in {a.repo}")
        ts.append({"id": a.id, "repo": a.repo, "stacks": ids(a.stacks),
                   "profile_status": a.profile_status, "opened": now, "closed": None,
                   "interventions": [], "gate_regressions": [], "commits": [],
                   "reverts": [], "post_deploy": None})
        save_tickets(ts)
        print(f"opened {a.id}")
        return
    if a.tcmd == "pending-postdeploy":
        for t in ts:
            if t.get("closed") and (t.get("post_deploy") or {}).get("status") == "pending" \
                    and (a.repo is None or t["repo"] == a.repo):
                print(f"{t['id']} {t['repo']} closed {t['closed']}")
        return
    t = find_ticket(ts, a.id)
    if a.tcmd == "intervene":
        if a.kind not in INTERVENTIONS:
            raise Fail(f"kind must be one of {INTERVENTIONS}")
        t["interventions"].append({"date": now, "kind": a.kind, "note": a.note})
    elif a.tcmd == "gate-regression":
        t["gate_regressions"].append({"date": now, "gate": a.gate, "note": a.note})
    elif a.tcmd == "commit":
        if a.sha not in [c["sha"] for c in t["commits"]]:
            t["commits"].append({"sha": a.sha, "kind": a.kind})
    elif a.tcmd == "revert":
        t["reverts"].append({"date": now, "sha": a.sha, "note": a.note})
    elif a.tcmd == "close":
        t["closed"] = now
        t["post_deploy"] = {"status": "pending", "ref": None, "date": None}
    elif a.tcmd == "postdeploy":
        if a.status not in ("verified", "unverified", "regression"):
            raise Fail("status must be verified, unverified or regression")
        t["post_deploy"] = {"status": a.status, "ref": a.ref, "date": now}
    elif a.tcmd == "show":
        print(json.dumps(t, indent=2, ensure_ascii=False))
        return
    save_tickets(ts)
    closed = sum(1 for x in ts if x.get("closed"))
    print(f"{a.id}: {a.tcmd} recorded")
    if a.tcmd == "close" and closed % 10 == 0:
        print(f"SELF-EVALUATION DUE: {closed} closed tickets")


def stack_of(cid):
    ns = cid.split(".")[0]
    return {"py": "python"}.get(ns, ns)


def metrics(tickets, concepts, since=None, until=None):
    """Per-stack metrics. A ticket counts toward each stack it lists. Probe and evidence
    counts are limited to dates in [since, until)."""
    out = {}

    def inside(date):
        return (since is None or date >= since) and (until is None or date < until)

    def row(s):
        return out.setdefault(s, {"tickets": 0, "interventions": 0, "gate_regressions": 0,
                                  "reverts": 0, "postdeploy_unverified": 0, "postdeploy_pending": 0,
                                  "draft_profile_tickets": 0, "delayed_probes": 0,
                                  "delayed_passes": 0, "unverified_evidence": 0})
    for t in tickets:
        for s in t["stacks"]:
            r = row(s)
            r["tickets"] += 1
            r["interventions"] += len(t["interventions"])
            r["gate_regressions"] += len(t["gate_regressions"])
            r["reverts"] += len(t["reverts"])
            st = (t.get("post_deploy") or {}).get("status")
            r["postdeploy_unverified"] += st == "unverified"
            r["postdeploy_pending"] += st == "pending"
            r["draft_profile_tickets"] += t.get("profile_status") == "draft"
    for cid, c in concepts.items():
        r = row(stack_of(cid))
        for date, passed, delayed in replay(c["evidence"])["probes"]:
            if delayed and inside(date):
                r["delayed_probes"] += 1
                r["delayed_passes"] += passed
        r["unverified_evidence"] += sum(1 for e in c["evidence"] if e["unverified"] and inside(e["date"]))
    for r in out.values():
        r["interventions_per_ticket"] = round(r["interventions"] / r["tickets"], 2) if r["tickets"] else None
        r["delayed_pass_rate"] = round(r["delayed_passes"] / r["delayed_probes"], 2) if r["delayed_probes"] else None
    return out


def cmd_report(a):
    concepts = load()
    closed = sorted([t for t in load_tickets() if t.get("closed")], key=lambda t: t["closed"])
    cur = closed[-a.window:]
    prev = closed[-2 * a.window:-a.window]
    since_cur = cur[0]["opened"] if cur else None
    since_prev = prev[0]["opened"] if prev else None
    rep = {"closed_tickets": len(closed), "window": a.window,
           "current": metrics(cur, concepts, since_cur),
           "previous": metrics(prev, concepts, since_prev) if prev else None}
    if prev:
        rep["previous"] = metrics(prev, concepts, since_prev, since_cur)
        verdicts = {}
        for s, c in rep["current"].items():
            p = rep["previous"].get(s)
            if not p or c["interventions_per_ticket"] is None or p["interventions_per_ticket"] is None:
                verdicts[s] = "insufficient history"
                continue
            falling = c["interventions_per_ticket"] < p["interventions_per_ticket"]
            cp, pp = c["delayed_pass_rate"], p["delayed_pass_rate"]
            flat = cp is not None and pp is not None and abs(cp - pp) < 0.05
            if not falling and cp is None:
                verdicts[s] = "METHOD FAILING: interventions not falling and no delayed probes run in the window"
            elif not falling and flat:
                verdicts[s] = "METHOD FAILING: interventions not falling and delayed-probe pass rate flat"
            else:
                verdicts[s] = "ok"
        rep["verdicts"] = verdicts
    print(json.dumps(rep, indent=2))


def cmd_commit(a):
    h = home()
    subprocess.run(["git", "-C", h, "add", "-A"], check=True)
    r = subprocess.run(["git", "-C", h, "diff", "--cached", "--quiet"])
    if r.returncode == 0:
        print("nothing to commit")
        return
    subprocess.run(["git", "-C", h, "-c", "user.name=coach", "-c", "user.email=coach@localhost",
                    "commit", "-q", "-m", a.m], check=True)
    print("committed")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("init")
    sp.add_parser("validate")
    x = sp.add_parser("add-concept"); x.add_argument("id"); x.add_argument("--title", required=True); x.add_argument("--requires")
    x = sp.add_parser("link"); x.add_argument("id"); x.add_argument("--requires", required=True)
    x = sp.add_parser("record"); x.add_argument("id"); x.add_argument("--kind", required=True)
    x.add_argument("--ref", required=True); x.add_argument("--note"); x.add_argument("--date")
    x.add_argument("--unverified", action="store_true")
    x = sp.add_parser("misconception"); x.add_argument("id"); x.add_argument("--ref", required=True)
    x.add_argument("--quote", required=True); x.add_argument("--date")
    x = sp.add_parser("show"); x.add_argument("id")
    x = sp.add_parser("prereqs"); x.add_argument("id")
    x = sp.add_parser("due"); x.add_argument("--date"); x.add_argument("--namespace")
    t = sp.add_parser("ticket"); ts = t.add_subparsers(dest="tcmd", required=True)
    x = ts.add_parser("open"); x.add_argument("id"); x.add_argument("--repo", required=True)
    x.add_argument("--stacks", required=True); x.add_argument("--profile-status", default="verified", choices=["verified", "draft"])
    x = ts.add_parser("intervene"); x.add_argument("id"); x.add_argument("--kind", required=True); x.add_argument("--note", required=True)
    x = ts.add_parser("gate-regression"); x.add_argument("id"); x.add_argument("--gate", required=True); x.add_argument("--note", required=True)
    x = ts.add_parser("commit"); x.add_argument("id"); x.add_argument("--sha", required=True)
    x.add_argument("--kind", default="behavior", choices=["behavior", "refactor", "test"])
    x = ts.add_parser("revert"); x.add_argument("id"); x.add_argument("--sha", required=True); x.add_argument("--note", required=True)
    x = ts.add_parser("close"); x.add_argument("id")
    x = ts.add_parser("postdeploy"); x.add_argument("id"); x.add_argument("--status", required=True); x.add_argument("--ref", required=True)
    x = ts.add_parser("pending-postdeploy"); x.add_argument("--repo")
    x = ts.add_parser("show"); x.add_argument("id")
    x = sp.add_parser("report"); x.add_argument("--window", type=int, default=10)
    x = sp.add_parser("commit"); x.add_argument("-m", required=True)
    a = p.parse_args(argv)
    fn = {"init": cmd_init, "validate": cmd_validate, "add-concept": cmd_add_concept, "link": cmd_link,
          "record": cmd_record, "misconception": cmd_misconception, "show": cmd_show,
          "prereqs": cmd_prereqs, "due": cmd_due, "ticket": cmd_ticket, "report": cmd_report,
          "commit": cmd_commit}[a.cmd]
    try:
        fn(a)
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
