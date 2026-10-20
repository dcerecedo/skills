# /coach log <file>

Compares a redacted production log excerpt against the baseline, for the endpoints that coached changes touched. Only aggregates are stored. Don't echo raw log lines back into the conversation, beyond the one or two needed to explain a finding.

## 1. Scan

Run `python3 ${CLAUDE_PLUGIN_ROOT}/coach/scripts/logstats.py scan <file>`. Exit code 3 means it found something that looks like personal data or secrets. Show the line numbers and kinds it printed (it never prints the values), ask the user to redact, and stop. Nothing is stored.

## 2. Summarize

```
python3 ${CLAUDE_PLUGIN_ROOT}/coach/scripts/logstats.py summarize <file> \
  --fields <logging fields from project.md, beyond the core five> \
  --out .coach/baselines/samples/<date>-<ticket or "adhoc">.json
```

Add `--duration-unit s` if the app logs seconds. If `parsed` is far below `lines`, the format doesn't match. Look at one line's keys (not its values) and say which field is missing.

## 3. Which endpoints

Endpoints touched by coached changes are found from the tickets in `tickets.jsonl` for this repo whose post-deploy check is pending, or that the user names:
1. Take the files changed in their commits.
2. Find the URL routes that reach those files. For Django: the `urlpatterns` entries pointing at changed views; views that call changed services or models (`grep` call sites); or `manage.py show_urls` if django-extensions is installed.

Show the mapping. Ask only if a route is ambiguous.

## 4. Compare

```
python3 ${CLAUDE_PLUGIN_ROOT}/coach/scripts/logstats.py compare .coach/baselines/<baseline>.json <sample>.json --paths <routes>
```

The baseline is the one recorded in `project.md`. With no baseline, everything is "no baseline": record the checks as unverified, and offer to make this sample the baseline if it predates the change.

Read the verdicts:
- **ok:** p95 within 20%, 5xx rate within 1 point, and profile fields such as `db_queries` within 20%. Sample at least 30 requests per endpoint.
- **regression:** look at the change with the user. Is it the coached commit? Use the teaching loop: they predict why first. If the commit caused it, it stays on that ticket's record.
- **insufficient** or **absent in sample:** not a pass.

## 5. Record

For each pending ticket whose endpoints were checked, run `kg.py ticket postdeploy <id> --status verified|regression|unverified --ref "<sample path> <verdict>"`. Insufficient data counts as unverified. Finish with `kg.py validate` and `kg.py commit`.
