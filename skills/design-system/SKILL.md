---
name: design-system
description: End-to-end design-system work on an existing product, grounded in what it actually ships. Routes between inventorying the running product, deriving its own system or resolving a third-party one (IBM Carbon, Primer, Material, a company library), mapping the product onto one or several candidates, and enforcing the chosen system in the codebase, stopping for the user's decision between steps. Use when the user asks to define, extract, adopt, compare, migrate to or enforce a design system for their product.
argument-hint: "[app URL] [target system(s)]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Agent, WebFetch, WebSearch, Bash(playwright-cli:*), Bash(python3:*), Bash(node:*), Bash(npm:*), Bash(npx:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git worktree:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*), Bash(cp:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first.

This skill composes five steps that can each run alone. To run a step, read its instructions and follow them in full:

| Step | Instructions | Produces |
| --- | --- | --- |
| Inventory | `${CLAUDE_PLUGIN_ROOT}/skills/ds-inventory/SKILL.md` | inventory |
| Resolve | `${CLAUDE_PLUGIN_ROOT}/skills/ds-resolve/SKILL.md` | manifest of a third-party system |
| Derive | `${CLAUDE_PLUGIN_ROOT}/skills/ds-derive/SKILL.md` | manifest of the product's own system |
| Map | `${CLAUDE_PLUGIN_ROOT}/skills/ds-map/SKILL.md` | mapping, comparison |
| Enforce | `${CLAUDE_PLUGIN_ROOT}/skills/ds-enforce/SKILL.md` | codebase changes |

## Route

Decide from the request which route applies, say it in one line, and reuse artifacts that already exist and are not stale instead of rebuilding them.

- **No target named** (the user wants their own system): inventory → derive (which maps the proposal against the inventory) → stop for decisions → enforce, if the user agrees.
- **One target** (adopt Carbon, Primer, ...): inventory and resolve (independent; either order) → map → stop for decisions on residuals and component gaps → enforce, if the user agrees.
- **Several targets** (which system fits us?): inventory → resolve each → map each → comparison → stop. Add the derived system as a candidate when the user wants "build our own" weighed against adoption.
- **Only part of the work** (an audit, a manifest, a comparison, enforcement for a system already chosen): run just those steps.

If the request does not settle the route (for example "set up a design system" without saying whether to adopt or build), ask that one question before starting.

## Stops

Stop and show the user the step's report at these points, because their answers change what comes next:

1. After the inventory summary, before any derivation or mapping.
2. After each resolved manifest's summary, before mapping against it.
3. After the derivation proposal or the mapping report, before enforcement. Residual decisions (extend the theme or change the UI) and component gaps are settled here.
4. After the enforcement plan, before changing the codebase.

Between stops, carry on without asking unless a step's own instructions say to ask.

## Not covered

Migrating existing code onto the system is not part of this skill. The mapping is precise enough to drive codemods (raw value → token, component → target component with prop changes), and its counts size that work; say so when the user reaches enforcement.
