# Design-system skills: shared conventions

The `ds-*` skills are functions over three artifacts. Each skill reads artifacts from disk, never from an earlier conversation, so any of them can run alone.

| Artifact | Schema | Written by | Read by |
| --- | --- | --- | --- |
| Inventory: what the product renders and contains | `schemas/inventory.schema.json` | ds-inventory | ds-derive, ds-map |
| Manifest: what a design system offers | `schemas/manifest.schema.json` | ds-resolve (third party), ds-derive (own) | ds-map, ds-enforce |
| Mapping: how a source fits a target | `schemas/mapping.schema.json` | ds-map | ds-enforce |

Paths in this file are relative to the plugin's `design-system/` folder, which each skill names in full.

## Workspace

Everything goes under `.claude/design-system/` in the product repository unless the user names another place:

```
.claude/design-system/
  .auth/state.json                    saved browser session; never read into the conversation, never committed
  inventory/<YYYY-MM-DD>-<short-sha>/ one folder per crawl
    inventory.json  source.json  components.json  routes.json  crawl.js  summary.md  screenshots/
  manifests/<slug>.manifest.json      one per design system (carbon, primer, derived, ...)
  manifests/<slug>.resolve.*          the script that produced a resolved manifest, kept for reruns
  manifests/<slug>.notes.md           normalization decisions, proposal notes
  mappings/<source-slug>--<target-slug>.json and .md
  enforce/                            codegen eval inputs and results
```

When a skill needs "the inventory" and the user has not named one, use the folder with the newest `meta.generatedAt` and say which one in a line.

Before writing anything, check `git check-ignore -q .claude/design-system/.auth`. If the path is not ignored, stop and propose the `.gitignore` line; auth state must not land in a tracked path. Whether the rest of `.claude/design-system/` is committed is the user's call; ask once if it matters for the task.

## Checking artifacts

Every artifact has `meta.schema`. Validate what you read and what you write:

```
python3 <design-system>/scripts/map.py check <artifact.json>
```

It uses the `jsonschema` package when installed and falls back to required-key checks otherwise. A failing check on input means the producing skill should be rerun, not that the consumer should work around it.

## Staleness

- Inventory: compare `meta.commit` with `git rev-parse HEAD`. If they differ, report `git rev-list --count <commit>..HEAD` and whether files that carry styles or components changed (`git diff --stat <commit>..HEAD`). Warn; ask only if the decision at hand depends on the changed area.
- Resolved manifest: compare `meta.version` with the version of that system installed in the product repo, when it is installed. A mismatch means the manifest describes a different release; rerun ds-resolve with the installed version.
- Mapping: it is stale when either input's `meta.generatedAt` is newer than its own `meta.source.generatedAt` or target version.

## Browser

Browser work uses `playwright-cli`, written against `@playwright/cli` 0.1.22 (pre-1.0; commands may change). Use the session name `-s=dds`. `run-code` needs an open session: `open` (with `state-load` after it when there is saved auth) or `attach` comes first. If a `playwright-cli` skill is listed in the session, load it before the first browser command.

## Honesty rules shared by every skill

- Every number reported comes from a script or a file written in this run, and the report says which.
- A value, state or criterion that could not be measured is reported as such; it never counts as covered or passed.
- When evidence does not decide a choice, stop and ask with the evidence for each option instead of choosing quietly.
