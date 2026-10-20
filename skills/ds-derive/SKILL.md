---
name: ds-derive
description: Derives a product's own design system from its inventory, compressing the values it actually renders into a three-tier token set, type, spacing, radius and elevation scales, contrast-safe color ramps and component contracts, written as a schema-checked manifest with the evidence for every token. Use when the user wants their own design system or tokens built from what the product already ships, rather than adopting a third-party system.
argument-hint: "[inventory folder]"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Bash(python3:*), Bash(node:*), Bash(npm install:*), Bash(npx:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git cat-file:*), Bash(git diff:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first, then `${CLAUDE_PLUGIN_ROOT}/design-system/methods.md`, which holds the techniques and decision rules this skill applies. `${CLAUDE_PLUGIN_ROOT}/design-system/scripts/dslib.py` has the color math (parsing, OKLab/OKLCH both ways, ΔE, contrast) and shadow parsing; import it rather than rewriting it.

The output is a proposal for the user to decide on, not a finished system. Every token must trace back to authored values with counts; a token you cannot justify from the inventory does not go in, however standard it looks elsewhere. Browser defaults (the `ua` counts) are not authored and do not become tokens. Brand guidelines and other companies' systems are context for naming, never a source of values.

## Input

An inventory folder (default and staleness as in CONVENTIONS). Check it with `map.py check`. If there is no inventory, say that ds-inventory has to run first and stop. For a product crawled in several themes, read every theme's inventory: primitives are shared, semantic tokens get one value per theme.

## Derive

Work with short scripts kept next to the manifest (`manifests/derived.*.py` and their JSON outputs), so every number can be rerun:

- **Color:** cluster authored colors in OKLab and pick representatives by the rules in methods.md; group into hue families; build each family's steps from contrast targets, keeping only steps the product needs; record how far each cluster moved.
- **Type:** families, sizes (a fitted scale only when it passes the test in methods.md, otherwise a named set), line-heights, weights by role.
- **Spacing, radius, border, elevation, motion:** fit as methods.md says and report residuals.
- **Tokens:** primitives, then semantic tokens with roles that alias them, component tokens only where a component genuinely deviates. Follow the naming grammar in methods.md and write it down in `derived.notes.md` with examples.
- **Themes:** one value per theme the inventories cover; do not add modes the product does not have.
- **Pairs:** declare, by token name, the foreground/background pairs the semantic tokens are meant for, each passing WCAG 2.2 at its level (`body` 4.5:1, `large` and `ui` 3:1). A pair the product renders today that fails stays out of `pairs` and goes in the notes as a finding.
- **Components:** with a `components.json`, a contract for the most used components (variants and props observed in usage, merged where their styles cluster, a `notSupported` list with usage counts). Without one, say that no component contracts were derived and why.
- **Scope:** what stays out of the system and why (one-off pages, legacy areas the user named).

Each token's `evidence` records `instances` (required: the authored instances it absorbs) and `values` (the source values merged into it).

Write `.claude/design-system/manifests/derived.manifest.json` with `meta.source.kind: derived`, `meta.source.ref` set to the inventory path and `meta.version` to the inventory's commit, check it, and export the same tokens as DTCG JSON to `manifests/derived.tokens.json` (aliases as `{group.token}` references), which is what ds-enforce builds from.

## Measure the proposal

Map the inventory onto the derived manifest, so the proposal is judged by the same coverage measure as any third-party system:

```
python3 ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/map.py map --source <inventory>/inventory.json --target .claude/design-system/manifests/derived.manifest.json --out .claude/design-system/mappings/<inventory-slug>--derived.json
```

## Decide with the user

When the rules in methods.md do not decide something, ask with the evidence for each option. Then show the proposal: token counts per tier and category, the scales with residuals, coverage from the mapping, authored values left outside every token with their counts, failing pairs found, and the component contracts. Nothing in the product repo changes in this skill; that is ds-enforce, after the user agrees.
