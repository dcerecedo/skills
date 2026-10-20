# /coach setup

Prepares a repository for coaching. Nothing is written until the user approves the write plan in step 7. Re-running it on a set-up repo updates `project.md` and the baselines. It never resets evidence.

## 1. Coach home

If `~/.claude/coach/` (or `$COACH_HOME`) does not exist, put `kg.py init` in the write plan. It creates the folder, `knowledge.md`, `tickets.jsonl`, `profiles/`, `reports/` and a local git repo with no remote.

## 2. Detect the stack

Check the detection markers of every profile: the plugin's `coach/profiles/*.md`, plus `~/.claude/coach/profiles/*.md`. Report each detected stack with the file that proves it (`manage.py`, `pyproject.toml` dependency line, ...). Profiles can stack: Django implies Python.

Read the project's toolchain:
- CI config (`.github/workflows/*`, `.gitlab-ci.yml`, ...). CI is authoritative for how tests and checks run here.
- `pyproject.toml` / `setup.cfg` / `tox.ini` / `pytest.ini`
- `Makefile`, `justfile`, `package.json` scripts, lockfiles, the `Dockerfile`
- Deploy config (for example Kamal's `config/deploy.yml`)

## 3. Unknown stack

A language or framework is in use and no profile covers it: draft one from the toolchain you read. Follow the section layout of `coach/profiles/python.md`, with `status: draft`. Every gate command must come from something in the repo, not from memory of how that stack is usually run. Show the draft and ask before writing it to `~/.claude/coach/profiles/<stack>.md`.

A draft stays a draft until each of its gate commands has run green once in a repo. Then change `status:` to `verified`, after telling the user. Until then, everything on that stack is unverified (SKILL.md, "Every run starts with").

## 4. Gates and baselines

For each gate in the active profiles, resolve the command as this repo runs it. Then run it once on HEAD, with a clean working tree. Record the result as the baseline.
- Test, lint, type-check and framework checks are read-only: run them.
- Mutation testing is expensive. Propose a scope (one or two apps the user is likely to touch) and an estimate, then ask before running it.
- A gate that can't run here (tool missing, needs services) goes into `project.md` as `not available: <reason>`. Results that depend on it are unverified. Don't install tools without asking.

Record the Python and framework versions; docs citations use them.

## 5. Structured logging

Read how the app logs today: `LOGGING` settings, middleware, log formatters, and a sample if the user has one. Propose JSON lines with:
- `request_id` (propagated from a header if a proxy sets one, else generated)
- `path`, `route` (templated, so endpoints aggregate)
- `status`, `duration_ms`
- the active profiles' logging fields

No user identifiers, emails, IPs or tokens.

Recommend the user implements it as their first coached ticket (`/coach ticket`), since it touches middleware, settings and tests. Only write it yourself if they say so, and then as a normal reviewed change.

## 6. Log baseline

Ask for a redacted production log excerpt covering a normal period. If one comes:
1. Run `logstats.py scan`. On any hit, list the line numbers and kinds and stop. Store nothing.
2. Run `logstats.py summarize <file> --fields <profile logging fields> --out .coach/baselines/<date>-logs.json`.

No excerpt: record `log baseline: none` in `project.md`. Post-deploy checks for this repo will be unverified until one exists.

## 7. Write plan

Show, then ask once for approval:
- the coach home init, if needed
- `.coach/project.md` (format in STATE.md), with profiles, gates and baselines, conventions found, and logging fields
- `.coach/baselines/*`
- the `.coach/logs/` line for `.gitignore`
- a drafted profile, if any

Write only what was approved. Don't commit to the product repo; tell the user which files to commit. End with `kg.py validate` and `kg.py commit -m "setup <repo>"`.

## Conventions worth recording

Find these from the code and history, each with the file or commit that shows it:
- test layout and naming
- fixtures or factories
- how settings are split
- how migrations are named and reviewed
- error-handling and logging style
- commit message style
- anything a revert in `git log -i --grep=revert` shows the team learned the hard way
