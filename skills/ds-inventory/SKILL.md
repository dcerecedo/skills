---
name: ds-inventory
description: Inventories what a running product actually renders and what its source contains (every computed style value per route, UI state and theme, text/background pairs, screenshots, hardcoded style values, component usage) into a schema-checked inventory, or diffs two inventories' screenshots. Use when the user wants a UI style audit, a design-system baseline, a pre-migration inventory, or a visual comparison between two crawls of the same product.
argument-hint: "[app URL] [compare <before> <after>]"
allowed-tools: Read, Grep, Glob, Write, Edit, Skill, AskUserQuestion, Bash(playwright-cli:*), Bash(python3:*), Bash(node:*), Bash(npm install:*), Bash(npx:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git cat-file:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*), Bash(cp:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first: it fixes the workspace layout, the artifact schemas, how instances are counted, the browser session and the honesty rules this skill follows. Shared files live in `${CLAUDE_PLUGIN_ROOT}/design-system/`.

The inventory is the raw evidence every later decision rests on, so it has to be complete and untidied: every value as rendered, with counts and the states it appears in. Do not merge, round, or interpret values here. That happens in ds-derive and ds-map.

## Mode

- **Crawl** (default): build a new inventory of the product.
- **Compare**: the user asks how the UI changed between two crawls (before/after a migration, two releases). Skip to "Compare" below.

## Inputs

The product repository is the working directory: routes, components and hardcoded values come from its source. From the conversation or the argument, take the app's URL (preferably staging) and anything the user said about scope (areas to skip, priority flows, themes, viewports) and about the data (whether it is disposable). Ask once, in a single question, for the URL if it is missing. Do not ask for credentials.

If the URL points at a page rather than the app's root (`.../index.html`, `.../app/dashboard`), use its origin plus the app's base path as `baseUrl` and the rest as the first route's path.

Create `.claude/design-system/inventory/<YYYY-MM-DD>-<short-sha>/` (short SHA from `git rev-parse --short HEAD`). For a product with several themes, crawl each theme into its own folder with the theme appended (`...-dark`); mappings are made per theme.

## Setup and authentication

Run `playwright-cli --version`. If it is missing, give the user these commands and stop:

```
npm install -g @playwright/cli@0.1.22
/plugin marketplace add microsoft/playwright-cli
/plugin install playwright-cli
```

Open the session on the app: `playwright-cli -s=dds open <url>` (add `--config=<file>` if the user keeps a playwright-cli config). Take a `snapshot`.

- **No sign-in needed** (public pages, local builds): carry on.
- **Saved state:** if `.claude/design-system/.auth/state.json` exists, run `playwright-cli -s=dds state-load .claude/design-system/.auth/state.json`, reload, and check with `snapshot` that you are signed in.
- **Sign-in needed and no saved state, or it expired:** close the session and open a headed persistent browser on the login page; let the user sign in themselves and never type credentials:

  ```
  playwright-cli -s=dds open <login-url> --headed --persistent
  ```

  When they say they are in, run `playwright-cli -s=dds state-save .claude/design-system/.auth/state.json`. Never read that file into the conversation, print it, or commit it.
- **Saved state does not survive** (short-lived tokens, device-bound SSO, MFA on every session): attach to the user's own browser with `playwright-cli -s=dds attach --cdp=chrome`, and if that cannot connect, `attach --extension=chrome` (needs the Playwright MCP Bridge extension). Say which one worked, and that an attached crawl cannot be rerun unattended in CI.

## Routes

Build the route list from the router source (Grep for the framework's route definitions), the sitemap if there is one, and the navigation as `snapshot` shows it. Parameterised routes need one real example each, taken from links the app shows, not invented IDs. Drop what the user put out of scope. Write `routes.json` (schema `$defs.routes`) with each route's path, where it was found, its states, the state kinds checked and absent (`notApplicable`), and states skipped with the reason.

## States

A route's default render shows a fraction of its UI. For each route with distinct UI, check for each of these kinds and reach the ones that exist:

- interaction: hover (`page.hover`) and keyboard focus (`page.keyboard.press('Tab')` until the control is focused) on the main controls, open menus, modals and toasts, disabled and selected controls;
- data: empty, long or overflowing content;
- feedback: loading (when it can be held, for example by delaying API calls with `page.route` inside `steps`), validation error, server error or offline (`page.context().setOffline(true)` in `steps`).

Reach a state interactively with `snapshot` and `click`/`fill`/`hover`, wrapped in `recording-start` and `recording-stop`. The printed Playwright code, trimmed to the actions that reach the state, becomes that state's `steps`. Do not submit forms that create, change or delete real data unless the user said the environment is disposable; list states skipped for that reason. Kinds that do not exist on a route go in its `notApplicable` list, so a missing state is visibly a decision rather than an omission.

## Crawl

Copy `${CLAUDE_PLUGIN_ROOT}/design-system/crawl.template.js` into the inventory folder as `crawl.js` and fill its CONFIG block and ROUTES list:

- `baseUrl`; `commit` = the full HEAD SHA; `outDir` = the absolute path of the folder's `screenshots/` (create it); `theme` and `colorScheme` for the theme this folder covers;
- viewports: at least desktop and one narrow width, plus any the user named;
- routes, and per route its states with their `steps`.

Nothing secret goes in it. Then:

```
playwright-cli -s=dds --raw run-code --filename=<inventory>/crawl.js > <inventory>/inventory.json
python3 ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/map.py check <inventory>/inventory.json
```

Read `errors`: an unexpected HTTP status or a failed `steps` means a state was not captured. Fix the steps and rerun, or record the gap. Close the session at the end (`playwright-cli -s=dds close`).

## Source

- `source.json` (schema `$defs.source`): hardcoded style values per file, by kind (hex, `rgb(`/`hsl(`/`oklch(`, raw `px`/`rem`, inline `style=`), with per-value counts for colors and sizes in `values`. Style code is anywhere styles are authored: CSS and preprocessor files, `<style>` blocks, CSS-in-JS, utility classes with arbitrary values (`p-[13px]`), inline styles. Exclude token definition files (files that only define custom properties or theme objects), vendored code and generated output. Count with Grep and record the globs scanned and excluded in `meta.globs`.
- `components.json` (schema `$defs.components`): component usage with prop-value counts. For React, `npx react-scanner` with the `count-components-and-props` processor; for other component frameworks, their AST tooling, or Grep with `meta.tool` set to `grep (approximate)`. For a product without components (plain HTML, server templates), write an empty list and note the recurring class names in `meta.notes`.
- If the user gave a Figma file key and a Figma connector is available, add the count of detached instances and overrides per library component to `summary.md`.

Check both files with `map.py check`.

## Summary

Write `summary.md` and show it to the user:

- states captured per route and viewport, and states not captured or not applicable, with reasons;
- distinct values per property, with the most frequent values and how many instances are browser defaults;
- near-duplicates worth a look (colors that differ by a few RGB units, sizes 1px apart), described, not merged;
- text/background pairs that fail WCAG 2.2 contrast, with sample selectors. A pair needs 4.5:1 unless every text drawn in it is large (≥ 24px, or ≥ 18.66px at weight ≥ 700), then 3:1. Compute ratios with `contrast` and `parse_color` from `${CLAUDE_PLUGIN_ROOT}/design-system/scripts/dslib.py`. Non-text contrast (control borders, focus rings) is not measured by the crawl; say so;
- the files with the most hardcoded values;
- component props used in code but absent from the component's definition.

## Compare

Given two inventories (default: the two newest of the same theme), diff their screenshots state by state:

```
npm install --prefix <scratch> pixelmatch@5 pngjs@7
NODE_PATH=<scratch>/node_modules node ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/diff-shots.cjs <before>/inventory.json <after>/inventory.json <after>/diff-vs-<before-folder>/
```

Report the states ordered by changed share, show the diff images of the largest changes, list states present on only one side, and flag a comparison as unreliable when the two crawls used different viewports or the data visibly differs. Whether a change is intended is the user's judgment; present it, do not rule on it.
