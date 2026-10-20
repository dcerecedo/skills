---
name: ds-enforce
description: Sets up a product codebase so changes comply with a chosen design system (derived or third-party manifest) with a token build or the target package and theme extension, usage rules for coding agents, lint rules against raw values and off-system components, accessibility checks, a scheduled drift rerun, and a codegen eval proving agents follow the rules. Use when the user has settled on a design system and wants it enforced going forward.
argument-hint: "<manifest> [mapping]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Agent, Bash(python3:*), Bash(node:*), Bash(npm:*), Bash(npx:*), Bash(pnpm:*), Bash(yarn:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git worktree:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*), Bash(playwright-cli:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first.

This skill changes the user's codebase and CI. Prevention is its job: it stops new violations. It does not migrate existing code; legacy values stay until someone migrates them, and the setup must let them through (baseline or allow-list) without hiding them.

## Inputs

- The chosen manifest (derived or resolved). Check it and its staleness.
- The mapping from the product's inventory to that manifest, when one exists: its residuals are where the theme needs extending, and its component gaps are where custom components remain. If the user has not decided on each residual (extend the theme, or change the UI), list the undecided ones and ask before planning.

## Plan, then confirm

Read how the repo builds, styles, lints and runs CI (package manager, framework, CSS approach, existing lint configs, CI workflows, where agent instructions live: CLAUDE.md, AGENTS.md, or files they reference). Then write the plan and wait for the user's go. Name each file you will change, what the check is, and how legacy code is let through. Only the parts the user agrees to get built.

The parts, as the repo needs them:

- **Tokens into code.** For a derived manifest: a token build (Style Dictionary v4 or Terrazzo, reading `manifests/derived.tokens.json`) to the outputs the stack uses (CSS custom properties, a Tailwind theme, platform files). For a third-party manifest: install the system's packages at the manifest's version and create the theme extension for the residuals the user chose to keep, in the system's own theming mechanism.
- **Rules for coding agents**, where agents in this repo already read instructions: which token or component to use for which situation, what is forbidden, one correct and one incorrect example each, and the commands that check compliance. Keep it short enough that an agent will apply it; link the full manifest instead of copying it.
- **Lint.** Fail on raw style values (stylelint-declaration-strict-value or the stack's equivalent; an ESLint rule for styles in JS) and on imports of components the system replaces. Allow-list the token files. Let existing violations through with a baseline file or per-file allow-list, and report the baseline count.
- **Accessibility.** axe-core through the test runner the repo already has (`@axe-core/playwright` for Playwright suites).
- **Drift.** A scheduled CI job that reruns the inventory crawl and the mapping and publishes coverage and the hardcoded-value count, so the trend is visible. It needs a way to sign in without a person: say what the repo has (a test account and its secret, a seeded environment without auth) and, if it has nothing, leave the job out and say so.

## Codegen eval

The acceptance test for the rules you wrote: can an agent build UI with the system without leaving it?

1. With the user, choose held-out screens (default 5) that the rules were not written from: existing screens, or specs written from them.
2. For each, in a separate git worktree, start a subagent with only the spec, the repo and the rules, and ask it to build the screen.
3. Score each result: raw values introduced (the hardcoded-value scan from ds-inventory over the diff; target 0), lint pass, off-system components imported, and, when the app can be run, a crawl of the new screen mapped against the manifest.
4. Report per screen, keep inputs and results under `.claude/design-system/enforce/`, and turn each failure into a fix in the rules or a missing token. Remove the worktrees afterwards.

## Report

What was changed, the lint baseline (violations let through, by file), the eval table, and what was left out and why.
