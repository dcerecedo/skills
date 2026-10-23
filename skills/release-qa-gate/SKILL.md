---
name: release-qa-gate
description: Pre-prod QA gate for an epic's deliverable. Reviews the spec and ranks risks, proves the test suite (changed-line coverage, mutation testing, flakiness, migration round-trip on prod-shaped data), then plans and runs a Playwright E2E pass against staging and ends in a go/no-go with named residual risk. Use when the user wants an epic thoroughly tested before deploying to prod, or asks for a release QA review.
argument-hint: "<EPIC_KEY> [RELEASE_REF]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Agent, WebFetch, Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git show:*), Bash(git blame:*), Bash(git rev-parse:*), Bash(git merge-base:*), Bash(git worktree:*), Bash(twg:*), Bash(python3:*), Bash(python:*), Bash(pytest:*), Bash(uv run:*), Bash(diff-cover:*), Bash(coverage:*), Bash(mutmut:*), Bash(cosmic-ray:*), Bash(semgrep:*), Bash(bandit:*), Bash(npx:*), Bash(npm:*), Bash(mkdir:*), Bash(ls:*)
---

Act as the release QA gate for an epic before it ships to prod. Depth over breadth: go deep on the highest risks, smoke-check the rest. Evidence over assertion: every claim links to a runner output, mutation report, trace, or line of code.

## Inputs

Resolve these before Phase 1. Ask only for what you cannot find yourself.

- `EPIC_KEY`: epic ticket key (first argument)
- `MAIN` and `RELEASE_REF`: diff range is merge-base(MAIN)..RELEASE_REF, covering every PR in the epic. Default `RELEASE_REF` to the current branch.
- `DATA_SNAPSHOT`: prod-shaped anonymized data snapshot. One exists; ask for its location if it is not obvious from the repo.
- `STAGING_URL`: running staging build

Use raw material, not summaries:
- The full diff, not PR descriptions
- Epic and child tickets including comment history and linked designs (Jira via the TWG CLI, or the Atlassian connector if present)
- Migrations and the resulting schema
- Git history and past incidents/bugs for the touched files

## Phase 1: Spec and risk (read-only)

1. List spec defects: ambiguous, contradictory or missing ACs, and behaviour in the diff that no AC asks for. Phrase each as a question for the spec owner.
2. Build a traceability matrix: AC -> code locations -> existing tests. Flag ACs with no test and tests with no AC.
3. Rank risks by likelihood x impact. Consider: data integrity, authz, money or irreversible actions, migrations, the rolling-deploy window where old and new versions serve traffic together, callers outside the epic affected by the diff, missing observability. Keep the top 5-8 only.

Report Phase 1 and stop. Wait for confirmation before Phase 2.

## Phase 2: Prove the tests

This phase installs tools and runs state-changing commands. State the plan, tool installs and success criteria in 2-3 lines and wait for confirmation first.

4. Run diff-cover for branch coverage of changed lines only.
5. Run mutation testing scoped to changed files (mutmut or cosmic-ray for Python, Stryker for JS/TS). Classify each surviving mutant: missing test, useless test, or equivalent mutant.
6. Flag tautological, over-mocked, or out-of-scope tests with the reason.
7. Run the suite 10x (`pytest --count`, Playwright `--repeat-each`); report flaky tests.
8. On `DATA_SNAPSHOT`: migrate forward and back; run the previous app version against the new schema.

## Phase 3: E2E plan and execution

9. Write a manual/E2E plan only for the top risks, using boundary values, decision tables and state transitions. Include setup: seed data from `DATA_SNAPSHOT`, roles (Playwright storageState), feature-flag states.
10. Add 2-3 time-boxed exploratory charters aimed at the top risks.
11. Implement in Playwright against `STAGING_URL`: per-role contexts, concurrent contexts where relevant, `page.route` for backend failure and latency injection, axe-core on new screens. Capture trace, video and HAR.
12. Propose fault seeding: list 3-5 realistic faults you would inject on a scratch branch (git worktree), mapped to the top risks, with estimated cost. Always propose, never run unasked. Wait for the user's decision. If approved, run them and report any the suite misses.

## Output

- Go / no-go, with residual risks named and who should accept each
- Blocking issues with repro steps and trace links
- Spec questions for the owner
- Post-deploy checks: metrics/alerts to watch and the threshold that triggers rollback
