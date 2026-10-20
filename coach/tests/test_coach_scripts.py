"""Tests for coach/scripts. Run: python3 -m unittest coach/tests/test_coach_scripts.py"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import kg  # noqa: E402
import logstats  # noqa: E402


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            kg.main(argv)
        except SystemExit as e:
            code = e.code or 0
    return code, out.getvalue(), err.getvalue()


class KG(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["COACH_HOME"] = self.tmp.name
        self.assertEqual(run(["init"])[0], 0)
        run(["add-concept", "py.basics.iteration", "--title", "iteration"])
        run(["add-concept", "django.orm.queryset", "--title", "QuerySet laziness", "--requires", "py.basics.iteration"])
        run(["add-concept", "django.orm.select_related", "--title", "select_related",
             "--requires", "django.orm.queryset"])

    def tearDown(self):
        self.tmp.cleanup()

    def rec(self, cid, kind, date, unverified=False):
        argv = ["record", cid, "--kind", kind, "--ref", "repo=eleaopen ticket=T-1", "--date", date]
        if unverified:
            argv.append("--unverified")
        return run(argv)

    def concept(self, cid):
        return kg.load()[cid]

    def test_unknown_prerequisite_rejected(self):
        code, _, err = run(["add-concept", "django.x.y", "--title", "t", "--requires", "django.nope"])
        self.assertEqual(code, 2)
        self.assertIn("unknown concept", err)

    def test_bad_id_rejected(self):
        code, _, err = run(["add-concept", "SelectRelated", "--title", "t"])
        self.assertEqual(code, 2)
        self.assertIn("namespaced", err)

    def test_cycle_rejected(self):
        code, _, err = run(["link", "py.basics.iteration", "--requires", "django.orm.select_related"])
        self.assertEqual(code, 2)
        self.assertIn("cycle", err)

    def test_mastery_progression_and_leitner(self):
        cid = "django.orm.select_related"
        self.rec(cid, "explained", "2026-10-01")
        self.assertEqual(self.concept(cid)["mastery"], "exposed")
        self.rec(cid, "probe-pass", "2026-10-02")
        c = self.concept(cid)
        self.assertEqual((c["mastery"], c["box"], c["next_review"]), ("practiced", 1, "2026-10-03"))
        self.rec(cid, "probe-pass", "2026-10-03")       # not delayed
        self.rec(cid, "probe-pass", "2026-10-12")       # delayed 1
        self.assertEqual(self.concept(cid)["mastery"], "practiced")
        self.rec(cid, "probe-pass", "2026-10-25")       # delayed 2
        c = self.concept(cid)
        self.assertEqual(c["mastery"], "retained")
        self.assertEqual(c["box"], 4)
        self.assertEqual(c["next_review"], "2026-11-15")
        self.rec(cid, "probe-fail", "2026-11-15")
        c = self.concept(cid)
        self.assertEqual((c["mastery"], c["box"], c["next_review"]), ("practiced", 1, "2026-11-16"))

    def test_unverified_evidence_does_not_move_mastery(self):
        cid = "django.orm.queryset"
        self.rec(cid, "probe-pass", "2026-10-02", unverified=True)
        c = self.concept(cid)
        self.assertEqual((c["mastery"], c["box"]), ("unseen", 0))
        self.assertTrue(c["evidence"][0]["unverified"])

    def test_prereq_checks_do_not_move_mastery(self):
        cid = "py.basics.iteration"
        self.rec(cid, "prereq-pass", "2026-10-02")
        self.assertEqual(self.concept(cid)["mastery"], "unseen")
        code, out, _ = run(["prereqs", "django.orm.select_related"])
        self.assertIn("UNVERIFIED py.basics.iteration", out)
        self.assertIn("last check prereq-pass", out)

    def test_hand_edit_of_mastery_is_caught(self):
        p = os.path.join(self.tmp.name, "knowledge.md")
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(text.replace("## django.orm.queryset\ntitle: QuerySet laziness\nrequires: py.basics.iteration\nmastery: unseen",
                                 "## django.orm.queryset\ntitle: QuerySet laziness\nrequires: py.basics.iteration\nmastery: retained"))
        code, out, _ = run(["validate"])
        self.assertEqual(code, 1)
        self.assertIn("evidence gives 'unseen'", out)

    def test_roundtrip_with_misconception(self):
        cid = "django.orm.select_related"
        run(["misconception", cid, "--ref", "ticket=T-1", "--quote", "it follows reverse FKs | too", "--date", "2026-10-02"])
        self.rec(cid, "diff-correct", "2026-10-03")
        cs = kg.load()
        self.assertEqual(cs[cid]["misconceptions"][0]["quote"], "it follows reverse FKs ¦ too")
        self.assertEqual(kg.parse_knowledge(kg.render_knowledge(cs)), cs)
        self.assertEqual(run(["validate"])[0], 0)

    def test_due(self):
        self.rec("django.orm.queryset", "probe-pass", "2026-10-01")
        _, out, _ = run(["due", "--date", "2026-10-02"])
        self.assertIn("django.orm.queryset", out)
        _, out, _ = run(["due", "--date", "2026-10-01"])
        self.assertIn("nothing due", out)

    def test_ticket_ledger_and_report(self):
        for i in range(20):
            tid = f"T-{i}"
            run(["ticket", "open", tid, "--repo", "eleaopen", "--stacks", "python,django"])
            for _ in range(5 if i < 10 else 2):
                run(["ticket", "intervene", tid, "--kind", "hint", "--note", "n"])
            code, out, _ = run(["ticket", "close", tid])
        self.assertIn("SELF-EVALUATION DUE: 20", out)
        _, out, _ = run(["ticket", "pending-postdeploy", "--repo", "eleaopen"])
        self.assertIn("T-0 eleaopen", out)
        run(["ticket", "postdeploy", "T-0", "--status", "unverified", "--ref", "no sample"])
        _, out, _ = run(["report"])
        rep = json.loads(out)
        self.assertEqual(rep["current"]["django"]["interventions_per_ticket"], 2.0)
        self.assertEqual(rep["previous"]["django"]["interventions_per_ticket"], 5.0)
        self.assertEqual(rep["previous"]["django"]["postdeploy_unverified"], 1)
        self.assertEqual(rep["verdicts"]["django"], "ok")

    def test_report_flags_failing_method(self):
        for i in range(20):
            tid = f"T-{i}"
            run(["ticket", "open", tid, "--repo", "r", "--stacks", "python"])
            run(["ticket", "intervene", tid, "--kind", "hint", "--note", "n"])
            run(["ticket", "close", tid])
        _, out, _ = run(["report"])
        self.assertIn("METHOD FAILING", json.loads(out)["verdicts"]["python"])


class Logs(unittest.TestCase):
    CLEAN = [
        '{"ts":"2026-10-20T10:00:00Z","request_id":"9f1c2e4a-1b2c-4d5e-8f90-1234567890ab","path":"/api/bookings/123?x=1","status":200,"duration_ms":40,"db_queries":3}',
        'ts=2026-10-20T10:00:01Z request_id=abc path=/api/bookings/456 status=500 duration_ms=900 db_queries=12',
        '{"ts":"2026-10-20T10:00:02Z","route":"/health","status":200,"duration_ms":2}',
    ]

    def test_clean_lines_pass_scan(self):
        self.assertEqual(logstats.scan_lines(self.CLEAN), [])

    def test_pii_is_detected_without_values(self):
        dirty = [
            '{"path":"/x","user":"ana@example.com"}',
            '{"path":"/x","remote_addr":"83.45.12.9"}',
            'path=/x authorization="Bearer abcdefghijklmnopqrstuvwxyz"',
            '{"path":"/x","dni":"12345678Z"}',
            '{"path":"/x","card":"4111 1111 1111 1111"}',
            '{"path":"/x","phone":"+34 612 345 678"}',
        ]
        hits = dict(logstats.scan_lines(dirty))
        self.assertEqual(set(hits), {1, 2, 3, 4, 5, 6})
        self.assertIn("email", hits[1])
        self.assertIn("ipv4", hits[2])
        self.assertIn("card-number", hits[5])
        self.assertIn("phone", hits[6])

    def test_summarize_templates_paths(self):
        s = logstats.summarize(self.CLEAN, fields=["db_queries"])
        ep = s["endpoints"]["/api/bookings/{id}"]
        self.assertEqual(ep["n"], 2)
        self.assertEqual(ep["status"], {"2xx": 1, "5xx": 1})
        self.assertEqual(ep["extra"]["db_queries"]["mean"], 7.5)
        self.assertIn("/health", s["endpoints"])

    def test_compare_verdicts(self):
        def mk(p95, n, err=0.0, q=3.0):
            return {"endpoints": {"/a": {"n": n, "p95_ms": p95, "error_rate": err,
                                         "extra": {"db_queries": {"n": n, "mean": q, "p95": q}}}}}
        self.assertEqual(logstats.compare(mk(100, 50), mk(110, 50))[0]["verdict"], "ok")
        self.assertIn("p95 +50%", logstats.compare(mk(100, 50), mk(150, 50))[0]["verdict"])
        self.assertIn("db_queries", logstats.compare(mk(100, 50), mk(100, 50, q=9.0))[0]["verdict"])
        self.assertIn("insufficient", logstats.compare(mk(100, 50), mk(300, 5))[0]["verdict"])


if __name__ == "__main__":
    unittest.main()
