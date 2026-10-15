# decycle

Untangles circular imports in a Python codebase one problem at a time. Each run scans the package import graph, shows every open problem with its metrics, and lets you pick one. It then settles with you which way that dependency should point and how to remove it, proves by simulation that no step adds a cycle anywhere, and writes test-first tickets that `/implement` (mattpocock/skills) builds with `/tdd`.

```
/dcerecedo-skills:decycle            scan and choose
/dcerecedo-skills:decycle P2         go straight to problem P2 of the scan
```

The skill only runs when invoked; Claude never picks it on its own.

## How a run goes

1. **Scan.** The run stops early in three cases. It stops if the previous problem is not implemented yet. It reports first any cycle that appeared since the last scan. It ends if the graph is already acyclic.
2. **You choose** a problem from the table:

   | Metric | Meaning |
   |---|---|
   | `cut` | Imports to remove in the nominated direction |
   | `reverse` | Imports in the other direction |
   | `scc` | Packages in the cycle |
   | `depth` | Package level of the pair |
   | `churn90` | Commits touching either side in the last 90 days |
   | `type_only` | `cut` imports that exist only under `TYPE_CHECKING` |

3. **Claude reads the code** at both ends of every crossing import. It decides which package is lower and picks a strategy per symbol: move, split, extract, invert, inject or merge. The strategies are listed in [`references/strategies.md`](../skills/decycle/references/strategies.md).
4. **Simulation.** The plan is a list of graph operations per step. It is checked against the whole package: no step may add a cyclic sibling dependency or break an earlier decision.
5. **You approve** the direction, strategy and steps.
6. **Tickets.** The decision is recorded and the tickets are written to `.scratch/decycle-NN-<slug>/issues/`. If the tracker is `jira` and you approved it, they are also created as Jira issues through your TWG skill or CLI.

## What keeps the codebase acyclic

[import-linter](https://import-linter.readthedocs.io/). The first problem's first ticket adds the guard:

- **`acyclic_siblings` contract** on the root package. Every remaining cycle-breaking import is listed in `ignore_imports`. New cycles fail `lint-imports` from then on.
- **`forbidden` contract** for each decision: the lower package must not import the higher one. Later problems cannot reverse it.

Each step ticket's red test deletes its lines from `ignore_imports`. Since import-linter fails on ignore lines that no longer match anything, the baseline can only shrink.

Definitions: a cycle is a cycle between sibling packages at any depth, as `acyclic_siblings` defines it. `TYPE_CHECKING` imports count. Function-local imports count, and grimp sees them.

## Requirements

- An interpreter with grimp installed (`pip install import-linter`), or `uv` on PATH, in which case the skill runs the script with `uv run --with import-linter`. The code under analysis is parsed, never imported.
- Optional: git, for `churn90`.
- Out of scope, because static import analysis cannot see them: `importlib` string imports, plugin entry points, and Django string model references such as `ForeignKey("app.Model")`.

## Settings

These keys go in `.claude/dcerecedo-skills.json` in the repo:

```json
{
  "python": ".venv/bin/python",
  "decycle": { "package": "myapp", "tracker": "jira", "jiraProject": "ABC" }
}
```

| Key | Default | Meaning |
|---|---|---|
| `python` (shared) | `python3` | Interpreter for the script |
| `decycle.package` | Detected | Root package to analyse |
| `decycle.tracker` | `local` | `local` or `jira` |
| `decycle.jiraProject` | None | Jira project key when `tracker` is `jira` |

## Files it writes in your repo

- `.decycle/state.json`: last scan and the active problem.
- `.decycle/decisions.json` and `.decycle/decisions.md`: the ledger of approved directions.
- `.decycle/plans/NN-<slug>.json`: the simulated plans.
- `.scratch/decycle-NN-<slug>/issues/*.md`: the tickets.

Commit them with the tickets. Source code is changed only later, by `/implement`.

## Develop

```bash
pip install import-linter
python3 -m unittest discover -s decycle/tests     # from the repo root
python3 skills/decycle/scripts/decycle.py scan --root decycle/tests/fixtures/shop --package shop
```

The fixture `tests/fixtures/shop` has three problems:
- a cycle across four top-level packages;
- a type-only import;
- a cycle inside `orders` that goes through a function-local import.
