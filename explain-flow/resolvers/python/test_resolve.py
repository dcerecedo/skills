"""Run: python3 -m unittest discover -s resolvers/python  (from the skill folder)."""

import os
import unittest

import resolve

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "django_locks")


def verify(*checks):
    req = {"root": FIXTURE, "checks": [dict(c, key=str(i)) for i, c in enumerate(checks)]}
    out = resolve.verify(req)["results"]
    return [out[str(i)] for i in range(len(checks))]


class Verify(unittest.TestCase):
    def test_definition_found(self):
        [r] = verify({"path": "locks/service.py", "line": 11, "role": "def", "code": "LockService.issue_code"})
        self.assertEqual(r["status"], "ok")

    def test_definition_on_wrong_line_says_where(self):
        [r] = verify({"path": "locks/service.py", "line": 3, "role": "def", "code": "LockService.issue_code"})
        self.assertEqual(r["status"], "error")
        self.assertIn("line 11", r["reason"])

    def test_definition_in_wrong_file_points_to_real_one(self):
        [r] = verify({"path": "bookings/views.py", "line": 9, "role": "def", "code": "issue_code"})
        self.assertEqual(r["status"], "error")
        self.assertIn("locks/service.py:11", r["reason"])

    def test_direct_call_verified(self):
        [r] = verify({"path": "bookings/services.py", "line": 11, "role": "call", "code": "LockService.issue_code"})
        self.assertEqual(r["status"], "verified")

    def test_celery_task_hop_verified(self):
        [r] = verify({"path": "bookings/services.py", "line": 12, "role": "call", "code": "sync_pms", "via": "task"})
        self.assertEqual(r["status"], "verified")
        self.assertIn("bookings/tasks.py:7", r["reason"])

    def test_signal_hop_verified_from_save(self):
        [r] = verify({"path": "bookings/services.py", "line": 10, "role": "call", "code": "on_booking_saved", "via": "signal"})
        self.assertEqual(r["status"], "verified")
        self.assertIn("post_save", r["reason"])

    def test_url_hop_verified_for_view_method(self):
        [r] = verify({"path": "bookings/urls.py", "line": 6, "role": "call", "code": "RebookView.post", "via": "url"})
        self.assertEqual(r["status"], "verified")

    def test_invented_call_rejected(self):
        [r] = verify({"path": "bookings/services.py", "line": 11, "role": "call", "code": "revoke_code"})
        self.assertEqual(r["status"], "error")

    def test_name_present_but_not_called_is_unverified(self):
        # line 1 imports LockService but does not call issue_code; the class name is there
        [r] = verify({"path": "bookings/services.py", "line": 1, "role": "call", "code": "LockService"})
        self.assertEqual(r["status"], "unverified")

    def test_missing_file_and_line(self):
        a, b = verify({"path": "nope.py", "line": 1, "role": "any"},
                      {"path": "bookings/services.py", "line": 400, "role": "any"})
        self.assertEqual(a["status"], "error")
        self.assertEqual(b["status"], "error")


class Seed(unittest.TestCase):
    def test_seed_finds_both_code_paths(self):
        out = resolve.seed({"root": FIXTURE, "entry": "bookings/views.py:10", "depth": 4})
        edges = {(e["from"], e.get("to"), e["via"]) for e in out["edges"]}
        # the explicit call and the signal receiver both reach issue_code
        self.assertIn(("bookings/services.py:6", "locks/service.py:11", "call"), edges)
        self.assertIn(("bookings/services.py:6", "bookings/signals.py:10", "signal"), edges)
        self.assertIn(("bookings/signals.py:10", "locks/service.py:11", "call"), edges)
        self.assertIn(("bookings/services.py:6", "bookings/tasks.py:7", "task"), edges)

    def test_seed_ignores_library_calls(self):
        out = resolve.seed({"root": FIXTURE, "entry": "locks/client.py:8", "depth": 2})
        self.assertFalse(any(e["name"] == "requests.post" for e in out["edges"]))

    def test_seed_skips_signal_for_other_sender(self):
        out = resolve.seed({"root": FIXTURE, "entry": "locks/service.py:12", "depth": 1})
        self.assertFalse(any(e["via"] == "signal" for e in out["edges"]))


if __name__ == "__main__":
    unittest.main()
