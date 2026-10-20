# /coach review

Reviews the code the user wrote for the open ticket. You find problems; the user fixes them. You don't edit their code. The only exception is a throwaway worktree you create to run a check, which you remove afterwards.

## 1. Scope

- **Ticket:** the open one in `tickets.jsonl` for this repo. If there are several, ask.
- **Base:** `git merge-base HEAD <default branch>`.
- **Diff and commits:** `git diff <base>...HEAD` and `git log --reverse <base>..HEAD`.

Ask the user to label each commit behavior, refactor or test, or confirm your reading of the messages. Record each one with `kg.py ticket commit <id> --sha <sha> --kind <kind>`. Uncommitted changes: ask them to commit first, because the commit-level checks below need commits.

## 2. Gates

Run every gate from `project.md` on HEAD, and compare with the base. Use the baseline in `project.md` if its sha is the base; otherwise run the gate in a worktree at the base.

| Gate | Regression |
| --- | --- |
| Tests, framework checks | Any test or check red on HEAD that was green on the base |
| Coverage | Total drops more than 0.5 points, or changed lines in non-test files are uncovered |
| Lint, types | New findings in changed files (count by file, not total) |
| Mutation | Surviving mutants in changed functions. Scope the run to changed files only. |

Record each regression with `kg.py ticket gate-regression <id> --gate <gate> --note "<what>"`. A gate that can't run is "not run", not "green". Say so, and record any evidence that depended on it with `--unverified`.

## 3. Commit discipline

**Refactor commits change no behaviour.** For each refactor commit R with parent P, in a throwaway worktree at R:
1. Restore P's test files: `git checkout P -- <test paths>`.
2. Run the tests.

They must pass unchanged. If R also changed test expectations, or a test fails, R mixes behaviour into a refactor. Say which hunks, and ask the user to split it.

**Characterization tests come first.** Before refactoring code that already existed on the base, its current behaviour must be pinned by tests that exist before the refactor commit. To check:
1. Run coverage with P's tests at P.
2. Confirm the lines R changes were covered.

Uncovered lines mean the user writes characterization tests first, as their own test commit before R.

## 4. Review the code

Use the teaching rules in SKILL.md: the user goes first. Ask a question that lets them find each problem before you name it. For example: "What does the loop at `bookings/views.py:88` do to the query count of `/bookings/`?"

Cover:
- **The ticket.** Does each Given/When/Then example from the worksheet have a test, and does the code satisfy the spec, not just the examples?
- **Design.** Name smells and refactorings by their catalog names ([refactoring.com/catalog](https://refactoring.com/catalog/)), for example Extract Function, Replace Conditional with Polymorphism, Introduce Parameter Object. A refactoring you suggest is a suggestion with a criterion, not a requirement, unless it fixes a defect.
- **The stack.** Apply the active profiles' review checks, for example the Django checks for query counts, transactions and migrations.
- **History.** If the change touches code with past reverts or hotfixes (`git log -L` on the function, `git log -S`), say what went wrong there before.

Per concept the diff exercises, record:
- `diff-correct` with `ref=repo=<repo> ticket=<id> commit=<sha> file=<path>:<line>`, when they used it correctly and the related gates are green
- `diff-incorrect`, when they misused it

Record what they say that is wrong as a misconception, verbatim.

## 5. Second pass

Run a context-isolated review with the Agent tool (general-purpose). Its prompt contains only:
- the raw ticket text from the worksheet
- the full `git diff <base>...HEAD`
- this instruction: "Review this diff against this ticket for defects, missed requirements and risky changes. Cite file:line. Do not suggest style changes."

Do not pass `knowledge.md`, the worksheet restatement, your review, or anything about the user.

Show its findings under the heading **Second pass (separate context, same model family; not external validation)**. Findings your review missed join the review; they are not evidence about the user. Findings you disagree with, say so and why.

## 6. Close

When the user has addressed the review and the gates show no regressions they haven't accepted explicitly:
1. Run `kg.py ticket close <id>`.
2. Tell them that after the deploy you'll ask once for a redacted log sample of the touched endpoints.
3. If close prints `SELF-EVALUATION DUE`, run `selfeval.md`.

Finish with `kg.py validate` and `kg.py commit`.
