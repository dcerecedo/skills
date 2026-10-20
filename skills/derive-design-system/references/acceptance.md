# Acceptance criteria

Five criteria, each computed by a script kept under `.claude/design-system/measure/` so it can be rerun. Targets are defaults; if the user sets others, record theirs in the report. Never mark a criterion passed by inspection.

| # | Criterion | Default target |
| --- | --- | --- |
| 1 | Token coverage of rendered values | ≥ 95% of instances per category |
| 2 | Contrast of declared pairs | 100% pass |
| 3 | Migration visual diff | ≤ 0.5% changed pixels per state, intentional changes listed |
| 4 | Codegen eval | 0 off-system values, lint passes |
| 5 | Drift baseline | recorded, with the command that recomputes it |

## 1. Coverage

From the phase 1 inventory: for each category (color, font size, line height, spacing, radius, shadow), the share of rendered instances whose value maps to a token within tolerance. Tolerances: ΔE OK ≤ 0.02 for color, exact px for sizes and spacing (after rem → px at 16px), exact match for shadows after parsing. Report the share per category and list every value outside tolerance with its count and samples, most frequent first. Those lists are the honest part of the result.

## 2. Contrast

For every foreground/background pair the semantic tokens declare as allowed (text on surface, text on accent, border on surface, focus ring on surface), compute the WCAG 2.2 ratio, plus APCA Lc if the user chose it, with the size and weight the pair is meant for. 100% must pass. Separately, rerun the check over `pairs` from a post-migration crawl: failures there are uses of an undeclared pair and go in the report.

## 3. Migration visual diff

Pick a sample of real screens with the user (at least one per major layout, including one form with error states). Migrate them onto the tokens on a branch, then:

1. Run the saved `inventory/crawl.js` against the pre-migration build and the migrated build, same viewports, same data.
2. Diff each state's screenshot pair (pixelmatch, threshold 0.1) and report the share of changed pixels.
3. For every state over target, show the diff image and say whether the change is intentional (a near-duplicate merged, a contrast fix) or a regression.

The run needs the same data on both sides; if the environment's data moves between runs, say so and diff only the stable regions or use a seeded environment.

## 4. Codegen eval

Measures whether a coding agent can build with the system, which is the point of making it AI-readable.

1. Choose N held-out screens (default 5) that were not used to write the usage rules: existing screens the user names, or specs written from them.
2. In a clean worktree, give an agent only the spec, the token build, the component library and the usage rules, and ask it to build each screen.
3. Score each result: off-system values introduced (the phase 1 hardcoded-value scan over the new code; target 0), lint pass, and visual diff against the reference screen using the same crawl.
4. Report per screen and in total. Failures point at gaps in the usage rules or missing tokens; list which.

## 5. Drift baseline

The count of hardcoded style values in source (the phase 1 scan) and the share of rendered instances off-token (criterion 1's complement), recorded with the date and commit. Hand over the exact commands that recompute both, so the user can track them in CI. A baseline is a pass once recorded; the trend is what matters afterwards.
