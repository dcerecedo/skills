# Self-evaluation (every 10 closed tickets)

Checks whether the coaching works. The test is whether the user needs less help, and still passes delayed probes.

## 1. Reverts and hotfixes

In this repo, for every commit recorded on tickets closed in the window:
- **Revert:** `git log -i --grep=<short sha>` and `git log -i --grep=revert`.
- **Hotfix:** a later commit within 14 days that changes lines `git blame` attributes to that commit, with a fix-type message. Use `git log -L` on the touched functions.

Record each one on its original ticket with `kg.py ticket revert <id> --sha <fixing sha> --note "<what>"`. Tickets in other repos can't be checked from here. List them as "reverts not checked".

## 2. Metrics

Run `kg.py report` (window 10). Per stack, it reports:
- interventions per ticket
- gate regressions
- reverts and hotfixes
- delayed-probe pass rate and count
- unverified and pending post-deploy checks
- tickets on a draft profile
- unverified evidence

It reports this for the current window and the previous one, with a verdict.

## 3. Report

Write `~/.claude/coach/reports/<date>-selfeval.md`. Per stack, include:
- a table of current versus previous window
- the verdict
- what the numbers rest on: how many probes, how many checks were unverified, which repos weren't checked for reverts

Say plainly what the data can't show. Five delayed probes isn't a trend.

## 4. Verdict

If the report says METHOD FAILING for a stack (interventions per ticket not falling while the delayed-probe pass rate is flat, or no delayed probes ran), say "the method is failing on <stack>" in the first line to the user.

Propose one concrete change, tied to what the numbers show. For example:
- interventions are mostly `gap`: harder spec challenges in `ticket`
- probes pass but interventions stay high: probes test the wrong concepts, so build them from intervention notes
- few delayed probes ran: the user isn't running `/coach probe`, so propose probing at the start of `ticket`
- fading too fast: slow the fading table

This is a proposal: the user decides. Don't edit the plugin.

Finish with `kg.py commit -m "selfeval <date>"`.
