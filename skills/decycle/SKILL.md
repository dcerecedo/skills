---
name: decycle
description: Untangles circular imports in a Python codebase one problem at a time. Scans the package import graph, ranks every cycle-breaking problem on several metrics so the user picks one, settles with the user which way that dependency should point and how to remove it, proves by simulation that no step adds a cycle anywhere, and writes test-first tickets for /implement. Runs only when the user invokes it.
argument-hint: "[problem: P-number or 'pkg.a -> pkg.b']"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Bash(python:*), Bash(python3:*), Bash(uv run:*), Bash(lint-imports:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git status:*)
---

The user wants the package structure of a Python codebase to become a directed acyclic graph, with each package owning one responsibility, and wants to get there one problem at a time rather than through a plan for the whole codebase. One run of this skill takes one problem from scan to approved, simulated, test-first tickets. It never edits source code: the user implements the tickets later with `/implement`, which drives `/tdd`.

A **problem** is one dependency between two sibling packages (children of the same package) that lies on a cycle and that grimp nominates for removal. Its id uses import-linter's arrow syntax, `shop.billing -> shop.orders`, and the scan also numbers problems `P1`, `P2`, ... for that scan only.

## Setup

- **Script**: `scripts/decycle.py` in this skill's folder. Run it with the interpreter in the `python` key of `.claude/dcerecedo-skills.json` when present, else `python3`. It needs grimp, which import-linter installs. If it exits with code 3 (grimp missing) and `uv` is on PATH, rerun it as `uv run --no-project --with import-linter python <script> ...`; otherwise tell the user to add import-linter as a dev dependency and stop.
- **Package**: the `decycle.package` key in `.claude/dcerecedo-skills.json`, else `package` in `.decycle/state.json`, else the single top-level package of the project (look at `pyproject.toml` and a `src/` layout). If more than one is plausible, ask once.
- **Tracker**: `decycle.tracker` in the same file, `"local"` (default) or `"jira"`, with `decycle.jiraProject` for Jira.
- **Working folder**: the script keeps its state in `.decycle/` at the repository root (`state.json`, `decisions.json`, `decisions.md`, `plans/`). These files are meant to be committed with the tickets.

## One run

Keep these steps in the task list and work through them in order. The run is complete when the tickets are written and the decision recorded, or earlier when step 1 finds nothing to do or something that blocks a new problem, or when the user stops it.

1. Scan
2. Choose the problem (stop A)
3. Investigate
4. Decide direction and strategy, as a plan
5. Simulate until the plan passes
6. Approve (stop B)
7. Record, write tickets, publish if asked, finish

There are exactly two places where you wait for the user: stop A and stop B. Between them, carry on without checking in.

### 1. Scan

Run `scan --root <repo root> --package <pkg> --write-state`. Then, before anything else:

- **Active problem still open**: the previous problem's decision still has imports in the forbidden direction. Report it with the folder of its tickets and end the run: a new problem waits until that one is implemented, because overlapping refactors invalidate each other's simulations. If the user explicitly says to abandon it, set `active` to `null` in `.decycle/state.json` and scan again.
- **New cyclic dependencies since the last scan**: report them first and prominently. They mean the import-linter guard is absent or was bypassed.
- **Decisions broken by other imports**: report them; the guard should have prevented them.
- **No problems**: say the package graph is acyclic and end the run.

### 2. Choose (stop A)

If the user passed a problem as the argument, use it and skip this stop. Otherwise show the scan table exactly as printed, with this legend in one short line per metric, and ask which problem to tackle. Do not recommend one unless asked: the user chooses the criterion each time.

- `cut`: imports to remove in the nominated direction
- `reverse`: imports in the opposite direction; near `cut` means the direction is a real decision, far from it means it is probably obvious
- `scc`: packages in this cycle
- `depth`: package level of the pair (1 = top-level packages)
- `churn90`: commits touching either package in the last 90 days
- `type_only`: how many of the `cut` imports exist only under `TYPE_CHECKING` (they still count)

### 3. Investigate

Run `detail --problem <id>`. Then read the code at both ends of every import it lists, in both directions, and Grep for the other users of each symbol that crosses the boundary. Also read `.decycle/decisions.md`, and the project's glossary or CLAUDE.md if present, so names follow the domain language. The decision rests on what each crossing symbol is and who else depends on it, so do this reading before forming a view.

### 4. Decide

**Direction.** Decide which package is lower: more general, more stable, closer to the domain core, depended on by more of the codebase. grimp's nominated direction is only the cheapest cut by import count, not a judgment about responsibilities; overturn it when the code says otherwise. A direction that reverses an entry in `.decycle/decisions.md` is not available.

**Strategy.** Pick one from `references/strategies.md` for each symbol that crosses the wrong way. Function-local imports, `importlib`, and a `TYPE_CHECKING` guard are not fixes: they hide the dependency, and type-only imports count as dependencies here.

**Steps.** Write the plan as JSON in `.decycle/plans/<NN>-<slug>.json`, in the format of `references/simulate.md`, where `NN` is this problem's sequence number (decisions recorded so far plus one, two digits). Each step becomes one ticket, so size it to leave the full test suite green and to be reviewable in one sitting. Put prefactoring first. When a moved symbol has many callers, sequence it expand-contract: new home plus a re-export from the old one, then callers in batches, then delete the re-export.

### 5. Simulate

Run `simulate --plan <file>`. It applies each step's graph operations to the whole package graph and fails if any step adds a cyclic sibling dependency anywhere, if any step adds an import that breaks a recorded decision, or if the chosen dependency still exists at the end. On failure, revise the plan and rerun; only a passing plan goes to the user. If three revisions still fail, take the failure itself to stop B as the blocker.

### 6. Approve (stop B)

Present, in this order:

1. The problem and the direction, with the reason in two or three sentences grounded in the code you read.
2. The strategy per crossing symbol, one line each.
3. The steps as a table: id, title, blocked by, what the red test is.
4. The simulation result (cyclic dependencies before → after) and the mermaid sibling graph it printed.
5. When the tracker is `jira`: that the tickets would also be created as Jira issues in `<jiraProject>`.

Then ask with AskUserQuestion: approve; approve without publishing to Jira (only when the tracker is `jira`); change the direction; change the strategy or steps. On a change, go back to step 4 or 5 and return here.

### 7. Record, write tickets, finish

1. `record --lower <importer package> --higher <imported package> --strategy <name> --rationale "<one line>"`. The dependency being removed goes from lower to higher.
2. `guard --root <repo root> --package <pkg>` (`--format toml` when the project configures tools in `pyproject.toml`). Its output gives the exact import-linter contracts and `ignore_imports` lines the tickets refer to.
3. Write the tickets as described in `references/tickets.md`, under `.scratch/decycle-<NN>-<slug>/issues/`.
4. When the user approved publishing to Jira, create one issue per ticket in dependency order with the project's TWG skill or CLI, following that skill's own instructions, link each to the issues that block it, and add the issue key to the local ticket file. If no TWG skill or CLI is available, say so in one line and keep the local tickets.
5. Finish in a few lines: the folder of the tickets, that `/implement <folder>` builds them in order, and that the next `/decycle` run will confirm the problem is closed before offering another.
