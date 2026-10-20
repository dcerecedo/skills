# Coach state

Two layers, both local. The plugin folder is read-only at runtime; nothing is written there.

## User level: the coach home

`$COACH_HOME`, default `~/.claude/coach/`. A local git repository with no remote. Created by `kg.py init`. After every `/coach` run that changed anything here, commit with `kg.py commit -m "<subcommand> <ticket>: <one line>"`. Never add a remote.

```
~/.claude/coach/
  knowledge.md     concept graph (all repos, all stacks): the only place evidence lives
  tickets.jsonl    ticket ledger: one coached ticket per line
  profiles/        stack profiles drafted for stacks the plugin does not ship
  reports/         self-evaluation reports, <YYYY-MM-DD>-selfeval.md
```

Evidence is global. A concept learned in one repo is the same concept in the next; the repo is recorded in each evidence `ref`, never as a separate store.

### knowledge.md

Every write goes through `coach/scripts/kg.py`. Do not edit the file by hand. The script replays evidence to derive `mastery`, `box` and `next_review`, and `kg.py validate` rejects a file whose stored values disagree.

```
## django.orm.select_related
title: select_related and the N+1 pattern
requires: django.orm.queryset, general.sql.join
mastery: practiced
box: 2
next_review: 2026-10-23
evidence:
- 2026-10-20 | probe-pass | repo=eleaopen ticket=ELEA-41 probe=assert-num-queries commit=3f2a1c9 | predicted 2 queries, ran 2
- 2026-10-20 | prereq-pass | repo=eleaopen ticket=ELEA-41 | explained lazy evaluation of a QuerySet correctly
misconceptions:
- 2026-10-19 | repo=eleaopen ticket=ELEA-38 | "select_related also follows reverse foreign keys"
```

Concept IDs are namespaced: `general.*` (stack-free engineering practice: testing, refactoring, design, SQL, HTTP), `py.*`, `django.*`, `ts.*`, and so on. The first segment is the namespace; a profile declares which namespaces it owns. Prerequisite edges cross namespaces freely (`django.orm.select_related` requires `general.sql.join`).

A `ref` is a link someone can follow: `repo=<name>` plus whichever of `ticket=`, `commit=<sha>`, `file=<path>:<line>`, `probe=<type>`, `ci=<run url>` apply. The repo name is the basename of `git remote get-url origin`, without `.git`.

Misconceptions are verbatim: the user's own words, in quotes, never paraphrased.

### Evidence kinds and what they do

| Kind | Recorded when | Effect |
| --- | --- | --- |
| `explained` | You showed an explanation or example for the concept | unseen → exposed |
| `probe-pass` | An execution-graded probe from the active profile passed | box +1; unseen/exposed → practiced; a delayed pass counts toward retained |
| `probe-fail` | An execution-graded probe failed | box → 1, review tomorrow; retained → practiced |
| `diff-correct` | The user's own diff uses the concept correctly and the gates are green | unseen/exposed → practiced; box at least 1 |
| `diff-incorrect` | The user's own diff misuses the concept | as probe-fail |
| `prereq-pass`, `prereq-fail` | One targeted question about a prerequisite | none; shows in `kg.py prereqs` as the last check |

Leitner intervals by box: 1 → 1 day, 2 → 3, 3 → 7, 4 → 21, 5 → 60. A probe is delayed when at least 7 days have passed since the concept's previous evidence. Two delayed passes move practiced → retained.

Pass `--unverified` when the evidence comes from a stack whose profile is a draft, or a gate that could not run. Unverified evidence is kept and counted in the self-evaluation, but it never moves mastery or the box.

What is not evidence: the user saying they know something; skill in an advanced concept (it says nothing about its prerequisites); a verbal answer to a probe question (that is a `prereq-*` check, not mastery); code you wrote.

### tickets.jsonl

Written by `kg.py ticket ...`. Per ticket:

- `id`, `repo`, `stacks`, and `profile_status` (verified or draft)
- `opened` and `closed`
- `interventions`: each time you supplied something the user did not produce. Kinds are `gap` (a spec gap they could not close after your challenge, so you named it), `hint`, `correction`, and `example`.
- `gate_regressions`: a gate that was green on the base and red or worse on the user's branch
- `commits`: the user's commits for the ticket, each marked behavior, refactor or test
- `reverts`: reverts or hotfixes that later landed on those commits
- `post_deploy`: pending, verified, unverified or regression, with a ref

A session is one ticket: from `/coach ticket` to close. The self-evaluation runs every 10 closed tickets.

## Project level: `.coach/` in the repository

```
.coach/
  project.md          committed: active profiles, conventions, gate commands as run here, baselines
  baselines/          committed: log aggregates (JSON, no raw lines) and gate baselines
  logs/               gitignored: ticket worksheets, raw gate output, anything transient
```

`project.md` holds no evidence about the user. It is safe to commit to a shared repository.

```
# Coach: <repo>

profiles: python, django            # from the plugin, or ~/.claude/coach/profiles/
profile_status: verified            # draft until every gate command has run green once here
django_version: 5.1                 # docs links use this version

## Gates (as run in this repo)
| Gate | Command | Baseline (<date>, <sha>) |
| --- | --- | --- |
| tests | pytest -q | 412 passed |
| coverage | pytest --cov --cov-report=term | 78.4% |
| ...

## Conventions
- <one line each, with the file or commit that shows it>

## Logging
fields: request_id, path, route, status, duration_ms, db_queries, db_ms, view
baseline: baselines/<date>-logs.json (<n> lines, window <first>..<last>)
```

Add `.coach/logs/` to the repository's `.gitignore` during setup, after asking.
