# Methods

Techniques for phase 2, in the order they are usually needed. Each one ends in numbers the user can check: what was merged, what it absorbed, what was left over.

## Reading the inventory

`inventory.json` from `crawl.template.js` has:

- `states[]`: every route/state/viewport crawled, with HTTP status, visible element count and screenshot path.
- `values[group][property][value]`: `count` (visible elements carrying it, summed over states), `states` (where it appears) and `samples` (selectors to find it).
- `pairs["fg | bg"]`: text color against the nearest opaque ancestor background, with the font sizes and whether bold text uses it. `canvas` means no opaque ancestor: the browser default.
- `summary`: distinct values per property.

Counts are element-weighted, so a value used by one large table dominates one used in a single button. Report both counts and the number of states a value appears in; a value present in many states is more structural than a frequent one in one state.

The crawl sees rendered styles only. Values defined but never rendered (dead CSS, unreachable states) are not in it; the source scan in phase 1 is where those show up.

## Color

1. Parse every color to OKLCH with culori (`npx` or a scratch `npm install culori`). Composite colors with alpha over the background they appear on (from `pairs`) before comparing; an `rgba(0,0,0,.6)` text and a `#666` text are the same color to the reader.
2. Cluster with a perceptual distance: ΔE OK (Euclidean in OKLab) ≤ 0.02 merges values nobody can tell apart; 0.02–0.05 are near-duplicates that need a decision. State the threshold used.
3. For each cluster report the members, total count and states, and pick the representative by count, not by the centroid, so the token is a value that already ships.
4. Group clusters into hue families, then rebuild each family as a ramp generated from contrast targets (Adobe Leonardo's approach: specify target ratios against the background, solve lightness). Map each old cluster to its nearest new step and report the ΔE moved.
5. Check every `pairs` entry against WCAG 2.2 (4.5:1 body, 3:1 for ≥ 24px or ≥ 18.66px bold, 3:1 for UI component boundaries) and, if the user prefers, APCA Lc targets. Failing pairs in the current product are findings to report, not to reproduce.

## Typography

- Font families: list them with counts; more than two or three is itself a finding.
- Sizes: fit a modular scale `base × ratio^n` by searching base (13–18px) and ratio (1.067–1.5) for the lowest total log-error over observed sizes, weighted by count. Report the best fit, the runner-up and each observed size's residual in px. If no scale fits within ~1px for the high-count sizes, the product uses an ad-hoc scale; propose a named set instead of forcing a ratio.
- Line-height: express each as a ratio of its font size; cluster the ratios.
- Weights: the set actually used, mapped to semantic roles (body, emphasis, heading).

## Spacing, radius, border, elevation, motion

- Spacing: for each candidate base unit (2, 4, 6, 8px), compute the share of spacing instances that are exact multiples and the count-weighted mean distance to the nearest multiple. Report the table and let the evidence choose; 4px usually wins, but not always.
- Radius: usually few values; cluster to the nearest px and name them by role (control, card, pill), with `9999px`/`50%` as the pill token.
- Border widths: count; anything other than 1px and 2px needs a reason.
- Elevation: parse `box-shadow` into offset, blur, spread and color, group by visual weight, and map to a short elevation scale.
- Motion: durations and easings, clustered; only propose motion tokens if motion appears in more than a handful of states.

## Tokens

- Format: W3C Design Tokens Community Group (DTCG) JSON, `$value` / `$type` / `$description`, aliases as `{color.blue.500}`.
- Tiers: primitives (raw scales, no meaning), semantic tokens (`color.text.muted`, `space.inset.md`) that alias primitives, component tokens only where a component genuinely deviates.
- Naming grammar: `category.role.variant.state`, written down in the proposal with examples, so new tokens follow it.
- Themes: one semantic set per mode found in phase 1 (light, dark, high contrast); primitives stay shared.
- Each semantic token's `$description` states the evidence: how many rendered instances it replaces.

## Components

- Usage: react-scanner with `processors: ['count-components-and-props']` gives component counts and prop-value frequencies. For other stacks, use the framework's AST tooling, or Grep with stated approximation.
- Contract per component: allowed variants and sizes (the observed ones, merged where the styles cluster together), required props, states (hover, focus, disabled, loading, error), and a "not supported" list for observed variants being retired, each with its usage count so the migration cost is visible.
- Detached Figma instances on the same component point at a missing variant; list them next to the contract.

## Builds and enforcement

- Token builds: Style Dictionary (v4 reads DTCG) or Terrazzo, outputting CSS custom properties, a Tailwind theme or the stack's config, and Figma variables.
- Lint: stylelint-declaration-strict-value for CSS, an ESLint rule against literal colors and sizes in JS styles; allow-list the token files themselves.
- Accessibility: axe-core through the existing test runner (`@axe-core/playwright` for Playwright suites).
- Visual regression: rerun the phase 1 crawl and diff screenshots per state (pixelmatch or Playwright's `toHaveScreenshot`); Chromatic if the repo already uses Storybook.
