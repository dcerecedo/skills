---
name: ds-map
description: Maps a product (its inventory) or an existing design system (its manifest) onto a target design-system manifest, measuring coverage in rendered instances, residual values that need a theme extension or a UI change, role mismatches, contrast of rendered and declared pairs, and component equivalents; compares several candidate targets side by side. Use when the user wants to know how well a design system fits their product, what migrating to it costs, or which of several systems fits best.
argument-hint: "<source: inventory folder or manifest> <target manifest(s)>"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, Bash(python3:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git diff:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first.

## Inputs

- **Source:** an inventory (value-level fit: every rendered value with its instance count) or a manifest (token-to-token translation, for a product that already has a system). For a product with no design system, the source is the inventory, not a derived manifest: deriving first would compress away the per-instance evidence the migration cost depends on.
- **Target:** one or more manifests from ds-resolve or ds-derive.
- **Theme:** the target theme to map against; default the target's `defaultTheme`. Map each theme the product uses when it has several, as separate mappings.

If a needed artifact is missing, say which skill produces it and stop. Check every input with `map.py check` and apply the staleness rules.

## Map

For each target:

```
python3 ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/map.py map --source <source> --target <manifest> --theme <theme> --out .claude/design-system/mappings/<source-slug>--<target-slug>.json
```

The script fits values only; its thresholds are in the output's `meta.thresholds`. What it cannot judge is yours to add.

**Components.** When the source is an inventory with `components.json` and the target has `components`, add a `components` array to the mapping file: for each product component by usage, the target equivalent or `null`, how props translate (`propMap`), and which observed variants have no target counterpart (`unsupported`), each with instance counts. Base equivalence on what the components do and their props, not on name similarity, and write the reason in `notes` when it is not obvious. Reruns of the script keep this section.

## Report

Write `<source-slug>--<target-slug>.md` next to the mapping and show the user:

- coverage per category, with categories where the target has no scale marked as such rather than as 0%;
- residuals, largest first: each is either a candidate for extending the target's theme or a value the UI should give up. Present both readings with the evidence (instance count, states, samples); the choice is the user's;
- role mismatches (`otherRole`): rendered values that match a target token meant for something else, for example a background color equal to a text token;
- rendered text/background pairs that fail contrast, and the target's declared pairs that fail in this theme;
- components without an equivalent, with instance counts: the size of the custom work.

With several targets, also run

```
python3 ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/map.py compare <mapping> <mapping> ...
```

and put the table at the top of a comparison report, followed by what the numbers do not show (licensing, framework fit, accessibility track record, how much the residuals concentrate in a few screens). Do not recommend a target from the table alone.
