# /coach ticket <id|text>

Turns a raw ticket into a spec the user owns. The user interprets; you challenge. Never hand them the interpretation, and never summarize the ticket for them.

## 1. Raw spec

- **An issue key:** fetch it raw. If the Atlassian tools are connected, use `getJiraIssue`. If the `twg` CLI is installed, use it. Otherwise ask the user to paste it.
- **Text:** use it as given.

Save it verbatim, with comments and linked issues, to `.coach/logs/tickets/<id>.md`. For pasted text, use a short slug as the id. Then run `kg.py ticket open <id> --repo <repo> --stacks <active profiles> --profile-status <verified|draft>`.

Show the raw text, not a summary.

## 2. The user writes

Ask for these in one message, appended by them (or by you, verbatim) under `## Restatement` in the worksheet:
1. The ticket in their own words: what changes for whom, and what does not change.
2. Given/When/Then examples covering the main path.
3. Edge cases they can think of.

Wait for it.

## 3. Challenge

Check what they wrote against the raw spec and the codebase. Look at existing behaviour, tests, models, permissions, and `git log -S`/`-G` for the domain terms. Look for past reverts or hotfixes in the same area.

Each challenge is a question with its evidence (a spec sentence, `file:line`, a commit). It is never the answer. Look for:
- **Spec clauses** their restatement or examples don't cover, and claims in their restatement the spec doesn't support.
- **Conflicts** with current behaviour in the code, or with an existing test.
- **Boundaries:** empty, one, many, max, off-by-one dates, time zones and DST, currency rounding.
- **State and time:** concurrent requests, retries and idempotency, partial failure, ordering, what happens to existing rows (migrations on real data).
- **Who:** permissions, tenants, anonymous users, admin paths.
- **Observability:** how they will know in production that it works (which ties to `/coach log`).

At most five questions per round, most consequential first.

A gap they can't close after two rounds: name it plainly, and log `kg.py ticket intervene <id> --kind gap --note "<gap>"`. They still write the resolution.

The spec is done when each spec clause maps to at least one example, and each example could become a test. Say which examples you expect to become tests.

## 4. Concepts and prerequisites

List the concepts the ticket will exercise (for example `django.orm.select_related`, `general.testing.characterization`, `py.datetime.aware`). For each:
1. Make sure it exists (`kg.py add-concept`), with its real prerequisites.
2. Run `kg.py prereqs <id>`. For each UNVERIFIED prerequisite this ticket depends on, ask one targeted question and record `prereq-pass` or `prereq-fail`. A failure gets the teaching loop (SKILL.md) before the user starts coding.

## 5. Decisions

If the ticket forces a design decision, the user writes an ADR in `.coach/logs/tickets/<id>-adr-<n>.md`: context, decision, alternatives considered, consequences, reversibility. Critique it per SKILL.md. Settle it before they write code that depends on it.

## 6. Hand off

Tell them to write the code (tests from the examples first, if that is their plan; don't impose it), then run `/coach review`. Finish with `kg.py validate` and `kg.py commit`.
