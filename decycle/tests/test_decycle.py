"""Run from the repository root: python3 -m unittest discover -s decycle/tests

Needs grimp (pip install import-linter). The lint-imports checks also need the
lint-imports command on PATH; they are skipped without it.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "skills", "decycle", "scripts"))

import decycle  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "shop")
LINT = shutil.which("lint-imports") or (
    os.path.join(os.path.dirname(sys.executable), "lint-imports")
    if os.path.exists(os.path.join(os.path.dirname(sys.executable), "lint-imports"))
    else None
)


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = decycle.main(list(argv))
    return code, out.getvalue()


def scan(root, *extra):
    _, out = run("scan", "--root", root, "--package", "shop", "--format", "json", *extra)
    return json.loads(out)


def write(root, rel, body):
    with open(os.path.join(root, rel), "w") as f:
        f.write(textwrap.dedent(body).lstrip())


class Workspace(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def plan(self, remove, *steps):
        path = os.path.join(self.root, "plan.json")
        with open(path, "w") as f:
            json.dump({"remove": remove, "steps": [{"id": f"{i:02}", "ops": ops} for i, ops in enumerate(steps, 1)]}, f)
        return run("simulate", "--root", self.root, "--package", "shop", "--plan", path)

    def lint(self):
        if not LINT:
            self.skipTest("lint-imports not installed")
        return subprocess.run([LINT], cwd=self.root, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": self.root})


class Scan(Workspace):
    def test_lists_every_problem_with_metrics(self):
        report = scan(self.root)
        by_id = {p["id"]: p for p in report["problems"]}
        self.assertEqual(
            set(by_id),
            {"shop.billing -> shop.orders", "shop.catalog -> shop.orders", "shop.orders.service -> shop.orders.models"},
        )
        self.assertEqual(by_id["shop.catalog -> shop.orders"]["type_only"], 1)
        self.assertEqual(by_id["shop.billing -> shop.orders"]["scc"], 4)
        self.assertEqual(by_id["shop.orders.service -> shop.orders.models"]["depth"], 2)
        self.assertTrue(report["diff"]["first_scan"])

    def test_markdown_table_numbers_problems(self):
        _, out = run("scan", "--root", self.root, "--package", "shop")
        self.assertIn("| P1 | `shop` | `billing` → `orders` |", out)

    def test_detail_shows_both_directions_with_lines(self):
        _, out = run("detail", "--root", self.root, "--package", "shop", "--problem", "P2")
        self.assertIn("[TYPE_CHECKING]", out)
        self.assertIn("`shop.orders.models` -> `shop.catalog.product` line 1", out)


class Simulate(Workspace):
    def test_inverting_the_dependency_passes(self):
        code, out = self.plan(
            "shop.billing -> shop.orders",
            [
                {"op": "add_module", "module": "shop.billing.billable"},
                {"op": "add_import", "importer": "shop.billing.invoice", "imported": "shop.billing.billable"},
                {"op": "remove_import", "importer": "shop.billing.invoice", "imported": "shop.orders.models"},
            ],
        )
        self.assertEqual(code, 0, out)
        self.assertIn("PASS", out)

    def test_extracting_into_a_module_that_imports_back_fails(self):
        code, out = self.plan(
            "shop.billing -> shop.orders",
            [
                {"op": "add_module", "module": "shop.common"},
                {"op": "add_import", "importer": "shop.common", "imported": "shop.orders.models"},
                {"op": "add_import", "importer": "shop.billing.invoice", "imported": "shop.common"},
                {"op": "remove_import", "importer": "shop.billing.invoice", "imported": "shop.orders.models"},
            ],
        )
        self.assertEqual(code, 1)
        self.assertIn("adds cyclic dependency shop.common -> shop.orders under shop", out)

    def test_intermediate_step_may_not_add_a_cycle_even_if_the_end_is_fine(self):
        code, out = self.plan(
            "shop.billing -> shop.orders",
            [{"op": "add_import", "importer": "shop.catalog.product", "imported": "shop.notifications.email"}],
            [
                {"op": "remove_import", "importer": "shop.catalog.product", "imported": "shop.notifications.email"},
                {"op": "remove_import", "importer": "shop.billing.invoice", "imported": "shop.orders.models"},
            ],
        )
        self.assertEqual(code, 1)
        self.assertIn("step 01: adds cyclic dependency", out)

    def test_plan_must_remove_the_dependency(self):
        code, out = self.plan("shop.billing -> shop.orders", [])
        self.assertEqual(code, 1)
        self.assertIn("still has imports", out)


class ThreeRuns(Workspace):
    """One problem per run; later runs respect earlier decisions and spot new cycles."""

    def test_consecutive_runs(self):
        # Run 1: scan, decide billing sits below orders, then the tickets get implemented.
        scan(self.root, "--write-state")
        run("record", "--root", self.root, "--lower", "shop.billing", "--higher", "shop.orders",
            "--strategy", "invert", "--rationale", "invoices only need an amount and a reference")
        self.assertEqual(scan(self.root)["active"], "shop.billing -> shop.orders", "active until implemented")
        write(self.root, "shop/billing/invoice.py", """
            from typing import Protocol


            class Billable(Protocol):
                order_id: str

                def total(self) -> int: ...


            class Invoice:
                def __init__(self, number: str, amount: int):
                    self.number = number
                    self.amount = amount


            def issue_invoice(item: Billable) -> Invoice:
                return Invoice(number=f"INV-{item.order_id}", amount=item.total())
        """)
        report = scan(self.root, "--write-state")
        self.assertIsNone(report["active"])
        self.assertIn("shop.billing -> shop.orders", report["diff"]["resolved_problems"])
        self.assertNotIn("shop.billing -> shop.orders", {p["id"] for p in report["problems"]})

        # Run 2: a plan that makes billing depend on orders again is rejected.
        code, out = self.plan(
            "shop.catalog -> shop.orders",
            [
                {"op": "remove_import", "importer": "shop.catalog.product", "imported": "shop.orders.models"},
                {"op": "add_import", "importer": "shop.billing.invoice", "imported": "shop.orders.service"},
            ],
        )
        self.assertEqual(code, 1)
        self.assertIn("breaks decision shop.billing -> shop.orders", out)
        with self.assertRaises(SystemExit):
            run("record", "--root", self.root, "--lower", "shop.orders", "--higher", "shop.billing",
                "--strategy", "move", "--rationale", "reverses run 1")

        # Run 3: someone adds a new cycle between catalog and notifications.
        write(self.root, "shop/notifications/email.py", """
            from shop.billing.invoice import Invoice
            from shop.catalog.product import Product

            SENT: list[str] = []


            def send_receipt(invoice: Invoice) -> None:
                SENT.append(f"receipt {invoice.number} {invoice.amount}")


            def announce(product: Product) -> None:
                SENT.append(product.sku)
        """)
        with open(os.path.join(self.root, "shop/catalog/product.py"), "a") as f:
            f.write("\n\nfrom shop.notifications.email import SENT  # noqa: E402\n")
        report = scan(self.root)
        self.assertIn("shop.catalog -> shop.notifications", report["diff"]["new_cyclic_deps"])


class Guard(Workspace):
    def test_baseline_passes_and_ratchets(self):
        _, ini = run("guard", "--root", self.root, "--package", "shop")
        with open(os.path.join(self.root, ".importlinter"), "w") as f:
            f.write(ini)
        self.assertEqual(self.lint().returncode, 0)

        # The red test of a ticket: delete its ignore line.
        with open(os.path.join(self.root, ".importlinter"), "w") as f:
            f.write(ini.replace("    shop.billing.invoice -> shop.orders.models\n", ""))
        self.assertNotEqual(self.lint().returncode, 0)

    def test_decision_becomes_a_forbidden_contract(self):
        run("record", "--root", self.root, "--lower", "shop.billing", "--higher", "shop.orders",
            "--strategy", "invert", "--rationale", "r")
        _, ini = run("guard", "--root", self.root, "--package", "shop")
        self.assertIn("type = forbidden", ini)
        self.assertIn("source_modules =\n    shop.billing", ini)
        with open(os.path.join(self.root, ".importlinter"), "w") as f:
            f.write(ini)
        self.assertEqual(self.lint().returncode, 0, self.lint().stdout)


if __name__ == "__main__":
    unittest.main()
