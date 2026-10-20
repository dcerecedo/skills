---
name: ds-resolve
description: Captures a third-party or existing design system (an npm package, a published token file, a Figma library, or a documentation site) into a neutral, schema-checked manifest of tokens per theme, text styles, declared color pairs and components, so it can be compared and mapped against a product. Use when the user names a design system to adopt, evaluate or compare (e.g. IBM Carbon, GitHub Primer, Material, their company's library).
argument-hint: "<design system: package name, token file, Figma file key or docs URL>"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, WebFetch, WebSearch, Bash(python3:*), Bash(node:*), Bash(npm install:*), Bash(npm view:*), Bash(npx:*), Bash(git rev-parse:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*), Bash(cp:*), Bash(playwright-cli:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first, and the manifest schema at `${CLAUDE_PLUGIN_ROOT}/design-system/schemas/manifest.schema.json`. The manifest is the only thing later skills know about the target, so a wrong value here becomes a wrong mapping everywhere. Nothing about any particular design system is built into this skill: you work out each one from its own published material, every time.

## Which version

Resolve the version the product will actually use. If the system is already a dependency of the product repo, use the installed version (lockfile). Otherwise use the latest stable release and say so (`npm view <package> version`). The manifest's `meta.version` records it.

## Sources, in order

Use the first source that yields machine-readable values; combine sources only to fill gaps, and record in `meta.source.notes` which part came from where.

1. **A published token file** (DTCG JSON, Style Dictionary output, or similar shipped in the package or the system's repo). Prefer resolved output (values, not aliases) when the system ships both, and keep the alias in `alias`.
2. **The system's npm packages.** Install them into a scratch directory (`npm install --prefix <scratch> --ignore-scripts <packages>@<version>`) and read their exported theme, token, spacing and type objects with a short Node script. Find the right exports by reading the package's `package.json`, its type definitions and its README, not by guessing names.
3. **A Figma library**, when the user gives a file key and a Figma connector is available: its variables and styles.
4. **The documentation site**, as a last resort: crawl the token and component pages with `playwright-cli` and read values from the rendered docs. Say that values from docs pages are lower confidence than packaged ones.

Write the normalizer you used to `.claude/design-system/manifests/<slug>.resolve.<ext>` so the manifest can be regenerated for a new version without rediscovering the sources.

## Normalization

- **Themes:** one key per theme or mode the system ships (light/dark, density, brand variants that change values). `defaultTheme` is the one the system documents as default.
- **Values:** as a browser computes them. Colors as `#rrggbb` or `rgba()`; dimensions in `px` (convert `rem` at 16px and say so in notes); durations in `ms`; font weights as numbers.
- **Names:** the name code uses, in the system's own convention (`$text-primary`, `--fgColor-muted`), so mapping output can be pasted into code.
- **Category:** from the system's own type information when present, otherwise from what the value is.
- **Role:** what the token is for (text, background, border, icon, focus, accent, spacing, radius, border-width, ...), from the system's own grouping or naming scheme. Write in `notes` the rule you applied (for example "prefix `fgColor` → text"). Leave `role` out when the system does not say; do not guess. ds-map only matches rendered values against tokens with a compatible role once a manifest has roles, so tokens for one component or domain (avatars, syntax highlighting, charts) should keep no role or `tier: component`.
- **Tier:** primitive, semantic or component, when the system distinguishes them.
- **Text styles:** the system's typography sets, with line height as the system defines it (a ratio is fine).
- **Pairs:** only foreground/background combinations the system declares as allowed in its documentation or token structure. If it declares none, leave `pairs` empty and say so; do not invent them.
- **Components:** the catalog with variants and props, from the component package's type definitions (`.d.ts`) or its docs. Record `importFrom` as code imports it.

## Check and confirm

```
python3 ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/map.py check .claude/design-system/manifests/<slug>.manifest.json
```

Then show the user a summary before anything uses the manifest: version and sources used, token counts per category and role, themes, text styles, declared pairs, components found, and every gap (a category the system has no scale for, values that could not be resolved, roles left unset). A target with no radius scale, for example, is a real property of that system, and ds-map will report it as such. Write the same summary to `<slug>.notes.md`.
