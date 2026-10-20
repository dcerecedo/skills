---
name: derive-design-system
description: Derives a design system from what a product actually ships rather than inventing one. Crawls the running app with playwright-cli to inventory every rendered style value and state, scans the source for hardcoded values and component usage, compresses the evidence into DTCG tokens and component contracts, makes them enforceable and readable by coding agents, and measures the result against stated acceptance criteria. Use when the user asks to define, extract, audit, consolidate or rebuild a design system, design tokens or a component library for an existing product.
argument-hint: "[app URL or repo area to focus on]"
allowed-tools: Read, Grep, Glob, Write, Edit, Skill, AskUserQuestion, Bash(playwright-cli:*), Bash(python3:*), Bash(node:*), Bash(npx:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*), Bash(cp:*)
---

The reader wants the design system their product already implies, made explicit, smaller and enforceable. They are not asking for a fresh aesthetic. Every token, scale and component variant you propose has to trace back to values the product renders today, with counts, and every claim of success has to be a number someone else can rerun. Brand guidelines, existing Figma libraries and design-system examples from other companies are context, never the source of truth.

Work in four phases. Stop at the end of phase 1 and again before phase 3, because those are the points where the user's judgment changes what you build and where you start writing to their repository.

## Inputs

Take these from the conversation, or from the argument passed to the skill:

- the repository and its frontend stack (read `package.json` or the equivalent to find out);
- the running app's base URL, preferably staging, and how to sign in;
- optionally a Figma file key, used only to count detached instances and overrides.

Ask once, in a single question, for whatever is missing and cannot be found in the repo. Write all output under `.claude/design-system/` in the repository unless the user names another place. Before writing anything there, run `git check-ignore -q .claude/design-system/.auth` and, if it is not ignored, tell the user and propose the `.gitignore` line; do not write auth state into a tracked path.

## Setup

This skill drives the browser with `playwright-cli` (written against `@playwright/cli` 0.1.22, a pre-1.0 tool whose commands may change). Run `playwright-cli --version`. If it is missing, give the user the install commands and stop:

```
npm install -g @playwright/cli@0.1.22
/plugin marketplace add microsoft/playwright-cli
/plugin install playwright-cli
```

If a `playwright-cli` skill is listed in this session, load it with the Skill tool before your first browser command and follow it for command details. If the installed version is newer than 0.1.22 and a command here fails, check `playwright-cli --help` before assuming the app is at fault.

Use a named session for the whole run, `-s=dds`, so it does not collide with other browser work.

## Authentication

Default: saved storage state. Open a headed, persistent browser on the login page and let the user sign in themselves; never type credentials:

```
playwright-cli -s=dds open <login-url> --headed --persistent
```

When they say they are in, run `playwright-cli -s=dds state-save .claude/design-system/.auth/state.json`. On later runs, `state-load` that file before crawling. Never read the file into the conversation, print it, or commit it: it carries live tokens.

Fallback, when state-save does not survive (short-lived tokens, SSO that binds to the device, MFA on every session): attach to the user's own browser instead. Try `playwright-cli -s=dds attach --cdp=chrome`; if that cannot connect, try `attach --extension=chrome`, which needs the Playwright MCP Bridge extension. Tell the user which one worked. Attached runs are not reproducible in CI, so say that the measurements in phase 4 will need a state-save run or a test account to be repeatable.

## Phase 1: Extract

Read-only for the product. The goal is a complete, raw inventory, not a nice one.

1. **Routes.** Build the route list from the router source (Grep for the framework's route definitions), the sitemap if there is one, and the app's navigation as `snapshot` shows it. Write it to `.claude/design-system/routes.json` with the source of each route. Parameterised routes need one real example each; take IDs from what the app links to, not invented ones.

2. **States.** A route's default render shows a fraction of its UI. For each route that carries distinct UI, reach these states when they exist: empty, loading (when it can be held, for example by delaying the app's API calls with `page.route` inside a state's `steps`), validation error, server error or offline (`page.context().setOffline(true)` in `steps`), long or overflowing content, open menus, modals and toasts, disabled and selected controls, and dark mode or other themes. Reach a state interactively with `snapshot` and `click`/`fill`, wrapped in `recording-start` and `recording-stop`; the printed Playwright code, trimmed to the actions that reach the state, becomes that state's `steps`. Do not submit forms that create, change or delete real data unless the user has said the environment is disposable.

3. **Crawl.** Copy `references/crawl.template.js` to a scratch path, fill its CONFIG block and ROUTES list (routes, states with their `steps`, viewports: at least desktop and one narrow width), and run it once:

   ```
   playwright-cli -s=dds --raw run-code --filename=<scratch>/crawl.js > .claude/design-system/inventory/inventory.json
   ```

   with `outDir` set to `.claude/design-system/inventory/screenshots`. Keep the filled crawl script next to the inventory as `crawl.js` (it is rerun in phase 4), with the base URL in it and nothing secret. Read the `errors` list: an unexpected HTTP error or a failed step means a state was not captured, and the inventory must say so.

4. **Source.** In the repository, count hardcoded style values (hex, `rgb(`/`hsl(`/`oklch(`, raw `px`/`rem` in styles, inline `style=`), per file. For component usage, run react-scanner for React (`npx react-scanner` with a config that reports props), or the stack's equivalent; with no tool for the stack, use Grep and say the counts are approximate. If a Figma file was given and a Figma connector is available, count detached instances and overrides of library components.

5. **Report and stop.** Write `.claude/design-system/inventory/summary.md`: distinct values per property, the near-duplicates (colors within a ΔE of each other, sizes 1px apart), text/background pairs that fail contrast, states that could not be reached and why, the files with the most hardcoded values, and component props that appear in usage but in no definition. Show the user that summary and ask whether to compress. Do not start phase 2 until they say so.

## Phase 2: Compress

Use the techniques in `references/methods.md`. Every proposal carries its evidence.

- **Color:** cluster rendered colors in OKLCH, merge within a stated ΔE threshold, then rebuild ramps from contrast targets so every declared foreground/background pair passes by construction. Report how many rendered instances each token absorbs and which values fall outside every cluster.
- **Type, spacing, radius, elevation, motion:** fit scales to the observed values and report residuals (how far each observed value is from its nearest step), not only the scale.
- **Tokens:** a three-tier architecture, primitive → semantic → component, in DTCG format (`tokens.json`), with a naming grammar and the theming axes the product actually uses (modes found in phase 1, not hypothetical ones).
- **Components:** for the most used components, a contract with the variants and props observed in usage, and an explicit list of what is not supported.
- **Scope:** a `scope.md` naming what stays out of the system (one-off marketing pages, legacy screens) and why.

When the data does not decide something (two clusters with similar counts, a spacing set that fits 4px and 6px equally well), stop and ask with the evidence for each option instead of picking quietly. Write everything under `.claude/design-system/proposal/` and show the user the proposal. Phase 3 changes their codebase, so ask before starting it.

## Phase 3: Make it enforceable and AI-readable

Only after the user agrees, and only the parts they agree to:

- a token build with Style Dictionary or Terrazzo to the outputs the stack needs (CSS custom properties, a Tailwind theme, Figma variables);
- usage rules written for a coding agent: which token or component to reach for in which situation, what is forbidden, with one correct and one incorrect example each. Put them where agents in this repo already read instructions (CLAUDE.md, AGENTS.md or a file they reference);
- lint rules that fail on raw values (stylelint-declaration-strict-value or the stack's equivalent) and an axe-core check, wired into the existing CI rather than a new pipeline.

## Phase 4: Measure

Compute every criterion in `references/acceptance.md` and report a table with the measured number, the target and pass or fail. A criterion that could not be measured is reported as not measured, with the reason; it never counts as a pass. Keep the measurement scripts and their outputs under `.claude/design-system/measure/` so the user or CI can rerun them.
