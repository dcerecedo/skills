# Methods

Techniques used by ds-derive (and, for parsing and distances, by `scripts/map.py`), in the order they are usually needed. Each one ends in numbers the user can check: what was merged, what it absorbed, what was left over.

## Reading the inventory

`inventory.json` from `crawl.template.js` has:

- `states[]`: every route/state/viewport crawled, with HTTP status, visible element count and screenshot path.
- `values[group][property][value]`: `count` (visible elements carrying it, summed over states; one per element and logical property, so four equal border sides count once), `ua` (how many of those are the browser's default for the tag), `states` (where it appears) and `samples` (selectors to find it).
- `pairs["fg | bg"]`: text color against the nearest opaque ancestor background, with the sizes and weights of the texts drawn in it (`texts`). `canvas` means no opaque ancestor: the browser default.
- `summary`: distinct values per property.

Work with authored instances, `count - ua`: a button's system font or default border was never a design decision and must not become a token. A value whose instances are all browser defaults is a finding (the product forgot to style that control), not a scale step.

Counts are element-weighted, so a value used by one large table dominates one used in a single button. Report both counts and the number of states a value appears in; a value present in many states is more structural than a frequent one in one state.

The crawl sees rendered styles only. Values defined but never rendered (dead CSS, unreachable states) are not in it; the source scan (`source.json`) is where those show up.

## Color

1. Parse every color to OKLab/OKLCH: `scripts/dslib.py` has `parse_color`, `to_oklab`, `to_oklch`, `oklch_to_srgb`, `hex_of`, `delta_e` and `contrast` (standard library only); culori is the JavaScript alternative. Composite colors with alpha over the background they appear on (from `pairs`) before comparing; an `rgba(0,0,0,.6)` text and a `#666` text are the same color to the reader.
2. Cluster with a perceptual distance: ΔE OK (Euclidean in OKLab) ≤ 0.02 merges values nobody can tell apart; 0.02–0.05 are near-duplicates that need a decision. State the threshold used.
3. For each cluster report the members, total count and states, and pick the representative by authored count, not by the centroid, so the token is a value that already ships. On a tie, prefer the member that appears in more states; then the one already defined as a variable or constant in the source (`source.json` samples); if still tied, ask.
4. Group clusters into hue families (OKLCH hue within about 15°, plus a neutral family for chroma below ~0.02). For each cluster, set a contrast target against the background it is used on: its current ratio, raised to the minimum its pair level needs (4.5:1 for body text, 3:1 for large text and UI). Solve OKLCH lightness for that target at the cluster's hue and chroma (Adobe Leonardo's approach), and keep only the steps the product uses: do not pad a family to ten steps. Name steps by lightness on a 0–1000 scale (L × 1000, rounded to the nearest 50; higher is darker: `100` light, `900` dark) so later additions fit between them. Map each old cluster to its new step and report the ΔE moved.
5. Check every `pairs` entry against WCAG 2.2 (4.5:1 body, 3:1 for ≥ 24px or ≥ 18.66px bold, 3:1 for UI component boundaries) and, if the user prefers, APCA Lc targets. Failing pairs in the current product are findings to report, not to reproduce.

## Typography

- Font families: list them with counts; more than two or three is itself a finding.
- Sizes: a modular scale `base × ratio^n` only counts as a fit if it explains the sizes without inventing steps. Search base (the most used body size ± 2px) and ratio from 1.125 to 1.5; a candidate qualifies only if every authored size with more than a handful of instances is within 1px of a step, and no more than one unused step lies between two adjacent used sizes (a tiny ratio fits anything by having steps everywhere). Among qualifying candidates take the lowest count-weighted log-error; the runner-up is the best candidate with a different ratio. Report both and each size's residual in px. If nothing qualifies, the product has an ad-hoc scale: propose a named set (`xs`, `sm`, `md`, ...) of the sizes in use instead of forcing a ratio.
- Line-height: express each as a ratio of its font size and cluster the ratios. `normal` means the font's own default (about 1.2): report it as unset rather than as a value, since the design never chose it.
- Weights: the set actually used, mapped to semantic roles (body, emphasis, heading).

## Spacing, radius, border, elevation, motion

- Spacing: for each candidate base unit (2, 4, 6, 8px), compute the share of authored spacing instances that are exact multiples and the count-weighted mean distance to the nearest multiple. A finer unit can never score worse than a coarser one it divides, so choose the coarsest unit whose exact-multiple share is within 2 percentage points of the best. Report the table and the rule applied.
- Radius: usually few values; cluster to the nearest px and name them by role (control, card, pill), with `9999px`/`50%` as the pill token.
- Border widths: count; anything other than 1px and 2px needs a reason.
- Elevation: parse `box-shadow` with `parse_shadow` from dslib into offset, blur, spread and color per layer, group by visual weight, and map to a short elevation scale.
- Motion: durations and easings, clustered; only propose motion tokens if motion appears in more than a handful of states.

## Tokens

- Two outputs carry the same tokens: the manifest (resolved values per theme, for ds-map, with `alias` naming the primitive) and `derived.tokens.json` in W3C Design Tokens Community Group (DTCG) format (`$value` / `$type` / `$description`, aliases as `{color.blue.500}`), for the token build in ds-enforce.
- Tiers: primitives (raw scales, no meaning), semantic tokens (`color.text.muted`, `space.inset.md`) that alias primitives, component tokens only where a component genuinely deviates.
- Naming grammar: `category.role.variant.state`, written down in the proposal with examples, so new tokens follow it.
- Themes: one semantic set per mode the inventory shows (light, dark, high contrast); primitives stay shared.
- Each semantic token's `$description` states the evidence: how many rendered instances it replaces.

## Components

- Usage: react-scanner with `processors: ['count-components-and-props']` gives component counts and prop-value frequencies. For other stacks, use the framework's AST tooling, or Grep with stated approximation.
- Contract per component: allowed variants and sizes (the observed ones, merged where the styles cluster together), required props, states (hover, focus, disabled, loading, error), and a "not supported" list for observed variants being retired, each with its usage count so the migration cost is visible.
- Detached Figma instances on the same component point at a missing variant; list them next to the contract.

## Builds and enforcement

- Token builds: Style Dictionary (v4 reads DTCG) or Terrazzo, outputting CSS custom properties, a Tailwind theme or the stack's config, and Figma variables.
- Lint: stylelint-declaration-strict-value for CSS, an ESLint rule against literal colors and sizes in JS styles; allow-list the token files themselves.
- Accessibility: axe-core through the existing test runner (`@axe-core/playwright` for Playwright suites).
- Visual regression: rerun the inventory crawl and use ds-inventory's compare mode (`scripts/diff-shots.cjs`); Chromatic if the repo already uses Storybook.
