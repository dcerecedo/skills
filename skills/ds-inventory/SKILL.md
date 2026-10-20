---
name: ds-inventory
description: Inventories what a running product actually renders and what its source contains (every computed style value per route and UI state, text/background pairs, screenshots, hardcoded style values, component usage) into a schema-checked inventory, or diffs two inventories' screenshots. Use when the user wants a UI style audit, a design-system baseline, a pre-migration inventory, or a visual comparison between two crawls of the same product.
argument-hint: "[app URL] [compare <before> <after>]"
allowed-tools: Read, Grep, Glob, Write, Edit, Skill, AskUserQuestion, Bash(playwright-cli:*), Bash(python3:*), Bash(node:*), Bash(npm install:*), Bash(npx:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*), Bash(cp:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first: it fixes the workspace layout, the artifact schemas, the browser session and the honesty rules this skill follows. Shared files live in `${CLAUDE_PLUGIN_ROOT}/design-system/`.

The inventory is the raw evidence every later decision rests on, so it has to be complete and untidied: every value as rendered, with counts and the states it appears in. Do not merge, round, or interpret values here. That happens in ds-derive and ds-map.

## Mode

- **Crawl** (default): build a new inventory of the product.
- **Compare**: the user asks how the UI changed between two crawls (before/after a migration, two releases). Skip to "Compare" below.

## Inputs

The product repository is the working directory: routes, components and hardcoded values come from its source. From the conversation or the argument, take the app's base URL (preferably staging) and anything the user said about scope (areas to skip, priority flows, themes, viewports) and about the data (whether it is disposable). Ask once, in a single question, for the base URL if it is missing. Do not ask for credentials.

Create `.claude/design-system/inventory/<YYYY-MM-DD>-<short-sha>/` (short SHA from `git rev-parse --short HEAD`).

## Setup and authentication

Run `playwright-cli --version`. If it is missing, give the user these commands and stop:

```
npm install -g @playwright/cli@0.1.22
/plugin marketplace add microsoft/playwright-cli
/plugin install playwright-cli
```

Default: saved storage state. If `.claude/design-system/.auth/state.json` exists, `playwright-cli -s=dds open <base-url>` then `playwright-cli -s=dds state-load .claude/design-system/.auth/state.json`, and check with `snapshot` that you are signed in. If there is no saved state, or it has expired, open a headed persistent browser on the login page and let the user sign in themselves; never type credentials:

```
playwright-cli -s=dds open <login-url> --headed --persistent
```

When they say they are in, run `playwright-cli -s=dds state-save .claude/design-system/.auth/state.json`. Never read that file into the conversation, print it, or commit it.

Fallback, when saved state does not survive (short-lived tokens, device-bound SSO, MFA on every session): attach to the user's own browser with `playwright-cli -s=dds attach --cdp=chrome`, and if that cannot connect, `attach --extension=chrome` (needs the Playwright MCP Bridge extension). Say which one worked, and that an attached crawl cannot be rerun unattended in CI.

## Routes

Build the route list from the router source (Grep for the framework's route definitions), the sitemap if there is one, and the navigation as `snapshot` shows it. Parameterised routes need one real example each, taken from links the app shows, not invented IDs. Drop what the user put out of scope. Write `routes.json` with each route's path and where it was found.

## States

A route's default render shows a fraction of its UI. For each route with distinct UI, reach the states that exist: empty, loading (when it can be held, for example by delaying API calls with `page.route` inside a state's `steps`), validation error, server error or offline (`page.context().setOffline(true)` in `steps`), long or overflowing content, open menus, modals and toasts, disabled and selected controls, and each theme the product offers (`page.emulateMedia({ colorScheme: 'dark' })` or the app's own toggle).

Reach a state interactively with `snapshot` and `click`/`fill`, wrapped in `recording-start` and `recording-stop`. The printed Playwright code, trimmed to the actions that reach the state, becomes that state's `steps`. Do not submit forms that create, change or delete real data unless the user said the environment is disposable; list states skipped for that reason.

## Crawl

Copy `${CLAUDE_PLUGIN_ROOT}/design-system/crawl.template.js` to the inventory folder as `crawl.js` and fill its CONFIG block (base URL, `outDir` = the absolute path of the inventory's `screenshots/`, `commit` = full HEAD SHA, viewports: at least desktop and one narrow width, plus any the user named) and its ROUTES list (routes, and per route its states with their `steps`). Nothing secret goes in it. Then:

```
playwright-cli -s=dds --raw run-code --filename=<inventory>/crawl.js > <inventory>/inventory.json
python3 ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/map.py check <inventory>/inventory.json
```

Read `errors`: an unexpected HTTP status or a failed `steps` means a state was not captured. Fix the steps and rerun, or record the gap.

## Source

- `source.json` (schema `$defs.source`): hardcoded style values per file: hex, `rgb(`/`hsl(`/`oklch(`, raw `px`/`rem` in style code, inline `style=`. Exclude token definition files, vendored code and generated output. Count with Grep; say in `meta` which globs were scanned.
- `components.json` (schema `$defs.components`): component usage with prop-value counts. For React, `npx react-scanner` with the `count-components-and-props` processor; for other stacks, the stack's AST tooling, or Grep with `meta.tool` set to `grep (approximate)`.
- If the user gave a Figma file key and a Figma connector is available, add the count of detached instances and overrides per library component to `summary.md`.

## Summary

Write `summary.md` and show it to the user:

- distinct values per property, with the most frequent values;
- near-duplicates worth a look (colors that differ by a few RGB units, sizes 1px apart), described, not merged;
- text/background pairs that fail WCAG 2.2 contrast, with sample selectors (`map.py` computes contrast when mapping; for the summary, compute it with `python3 -c` importing `${CLAUDE_PLUGIN_ROOT}/design-system/scripts/dslib.py`);
- routes and states not captured, and why;
- the files with the most hardcoded values;
- component props used in code but absent from the component's definition.

## Compare

Given two inventories (default: the two newest), diff their screenshots state by state:

```
npm install --prefix <scratch> pixelmatch@5 pngjs@7
NODE_PATH=<scratch>/node_modules node ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/diff-shots.cjs <before>/inventory.json <after>/inventory.json <after>/diff-vs-<before-folder>/
```

Report the states ordered by changed share, show the diff images of the largest changes, list states present on only one side, and flag a comparison as unreliable when the two crawls used different viewports or the data visibly differs. Whether a change is intended is the user's judgment; present it, do not rule on it.
