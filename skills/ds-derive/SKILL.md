---
name: ds-derive
description: Derives a product's own design system from its inventory, compressing the values it actually renders into a three-tier token set, type, spacing, radius and elevation scales, contrast-safe color ramps and component contracts, written as a schema-checked manifest with the evidence for every token. Use when the user wants their own design system or tokens built from what the product already ships, rather than adopting a third-party system.
argument-hint: "[inventory folder]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Bash(python3:*), Bash(node:*), Bash(npm install:*), Bash(npx:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git diff:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first, then `${CLAUDE_PLUGIN_ROOT}/design-system/methods.md`, which holds the techniques this skill applies.

The output is a proposal for the user to decide on, not a finished system. Every token must trace back to rendered values with counts; a token you cannot justify from the inventory does not go in, however standard it looks elsewhere. Brand guidelines and other companies' systems are context for naming, never a source of values.

## Input

An inventory folder (default: the newest, named in a line). Check it with `map.py check` and apply the staleness rule. If there is no inventory, say that ds-inventory has to run first and stop.

## Derive

Work in a scratch directory with short scripts whose outputs you keep next to the manifest, so the numbers can be rerun:

- **Color:** cluster rendered colors in OKLCH and pick representatives by count; rebuild each hue family as a ramp from contrast targets; map every cluster to its new step and record how far it moved.
- **Type:** families, a fitted size scale (or a named set when no ratio fits), line-height ratios, weights by role.
- **Spacing, radius, border, elevation, motion:** fit to the observed values and report residuals.
- **Tokens:** primitives, then semantic tokens with roles that alias them, component tokens only where a component genuinely deviates. Follow the naming grammar in methods.md and write it down in `derived.notes.md` with examples.
- **Themes:** one semantic set per mode the inventory shows; do not add modes the product does not have.
- **Pairs:** declare the foreground/background pairs the semantic tokens are meant for, each passing WCAG 2.2 (4.5:1 body, 3:1 large and UI). A pair the product renders today that fails stays out of `pairs` and goes in the notes as a finding.
- **Components:** if `components.json` exists, a contract for the most used components: variants and props observed in usage, merged where their styles cluster, with a `notSupported` list carrying usage counts.
- **Scope:** what stays out of the system and why (one-off pages, legacy areas the user named).

Each token's `evidence` records the source values it absorbs and their instance count.

Write `.claude/design-system/manifests/derived.manifest.json` with `meta.source.kind: derived`, `meta.source.ref` set to the inventory path and `meta.version` to the inventory's commit, and check it.

## Measure the proposal

Run ds-map's script with the inventory as source and the derived manifest as target, so the proposal is judged by the same coverage measure as any third-party system:

```
python3 ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/map.py map --source <inventory>/inventory.json --target .claude/design-system/manifests/derived.manifest.json --out .claude/design-system/mappings/<inventory-folder>--derived.json
```

## Decide with the user

When the data does not decide something (two clusters with similar counts, a spacing set that fits 4px and 6px about equally, a value that could be a token or a one-off), stop and ask with the evidence for each option. Then show the proposal: token counts per tier and category, the scales with residuals, coverage from the mapping, values left outside every token with their counts, failing pairs found, and the component contracts. Nothing in the product repo changes in this skill; that is ds-enforce, after the user agrees.
