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
  inventory/<YYYY-MM-DD>-<short-sha>[-<theme>]/   one folder per crawl (and per theme)
    inventory.json  routes.json  source.json  components.json  crawl.js  summary.md  screenshots/
  manifests/<slug>.manifest.json      one per design system
  manifests/<slug>.resolve.*          the script that produced a resolved manifest, kept for reruns
  manifests/<slug>.notes.md           normalization decisions, proposal notes
  manifests/derived.tokens.json       DTCG export of a derived system, for ds-enforce
  mappings/<source-slug>--<target-slug>.json and .md
  mappings/<source-slug>--comparison.md
  enforce/                            codegen eval inputs and results
```

Slugs: an inventory's slug is its folder name; a manifest's slug is the short lowercase name of the system (`carbon`, `primer`, `material`, `derived`).

When a skill needs "the inventory" and the user has not named one, use the folder with the newest `meta.generatedAt` and say which one in a line. A folder with only `inventory.json` is usable; say which of the other files are missing and what that leaves out (no `components.json`: no component mapping).

Before writing anything, check `git check-ignore -q .claude/design-system/.auth/state.json` (a path inside the folder: a pattern like `.auth/` only matches once the folder exists). If it is not ignored, stop and propose these `.gitignore` lines, which also cover the snapshots `playwright-cli` writes into the working directory:

```
.claude/design-system/.auth/
.playwright-cli/
```

## Checking artifacts

Every artifact has `meta.schema`. Validate what you read and what you write, including `routes.json`, `source.json` and `components.json`:

```
python3 <design-system>/scripts/map.py check <artifact.json>
```

It uses the `jsonschema` package when installed and falls back to required-key checks otherwise. A failing check on input means the producing skill should be rerun, not that the consumer should work around it.

## Staleness

- Inventory: if `git cat-file -e <meta.commit>^{commit}` fails, the commit is not in this repo's history (a fixture, a rewritten branch): say staleness cannot be computed and carry on. Otherwise, if it differs from `git rev-parse HEAD`, report `git rev-list --count <commit>..HEAD` and whether files that carry styles or components changed (`git diff --stat <commit>..HEAD`). Warn; ask only if the decision at hand depends on the changed area.
- Resolved manifest: when the system is installed in the product repo, compare each entry of `meta.packages` (or `meta.version`) with the installed version from the lockfile; a mismatch means the manifest describes a different release, so rerun ds-resolve with the installed version. When it is not installed, there is nothing to compare; say nothing.
- Mapping: stale when the source's or the target's `meta.generatedAt` is newer than the one recorded in the mapping's `meta.source` or `meta.target`.

## Counting

Inventory counts are per element and logical property: a box with the same border on four sides counts once for `border-color` and once for `border-width`; a box with `padding: 8px 16px` counts once for 8px and once for 16px. Instances equal to the browser's default for that tag (a button's system font and outset border, a paragraph's default margin) are counted in `ua`. They were rendered but not authored, so ds-derive does not turn them into tokens and ds-map leaves them out of coverage and residuals, while reporting how many there are.

## Browser

Browser work uses `playwright-cli`, written against `@playwright/cli` 0.1.22 (pre-1.0; commands may change). Use the session name `-s=dds`. `run-code` needs an open session: `open` (with `state-load` after it when there is saved auth) or `attach` comes first. If the user keeps a `playwright-cli.json` (custom browser path, proxy), pass it with `--config=<file>` on `open`. If a `playwright-cli` skill is listed in the session, load it before the first browser command.

## Downloaded code

Packages installed to read a design system's tokens are untrusted input. Install them into a scratch directory, keep the scripts that read them in a different directory, pass paths as arguments, and run Python with `-I` (`python3 -I <script> <package-dir>`) so nothing in the package directory is imported by accident.

## Honesty rules shared by every skill

- Every number reported comes from a script or a file written in this run, and the report says which.
- A value, state or criterion that could not be measured is reported as such; it never counts as covered or passed.
- When evidence does not decide a choice, ask with the evidence for each option (AskUserQuestion when available) instead of choosing quietly. With nobody to ask (an unattended run), take the most defensible option, write the question and the choice made to `.claude/design-system/QUESTIONS.md`, and say so at the top of the report.
