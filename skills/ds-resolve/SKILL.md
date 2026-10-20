---
name: ds-resolve
description: Captures a third-party or existing design system (npm packages, a published token file, a Figma library, or a documentation site) into a neutral, schema-checked manifest of tokens per theme, text styles, declared color pairs and components, so it can be compared and mapped against a product. Use when the user names a design system to adopt, evaluate or compare (e.g. IBM Carbon, GitHub Primer, Material, their company's library).
argument-hint: "<design system: name, package(s), token file, Figma file key or docs URL>"
allowed-tools: Read, Grep, Glob, Write, Edit, AskUserQuestion, WebFetch, WebSearch, Bash(python3:*), Bash(node:*), Bash(npm install:*), Bash(npm view:*), Bash(npx:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git diff:*), Bash(git check-ignore:*), Bash(mkdir:*), Bash(ls:*), Bash(cp:*), Bash(playwright-cli:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/design-system/CONVENTIONS.md` first, and the manifest schema at `${CLAUDE_PLUGIN_ROOT}/design-system/schemas/manifest.schema.json`. The manifest is the only thing later skills know about the target, so a wrong value here becomes a wrong mapping everywhere. Nothing about any particular design system is built into this skill: you work out each one from its own published material, every time.

The manifest's slug is the short lowercase name of the system (`carbon`, `primer`).

## Which packages and version

Find which packages make up the system (tokens, themes, components, icons) from its documentation or its main package's dependencies. Resolve the version the product will actually use: the installed one if the system is already a dependency (lockfile), otherwise the latest stable release (`npm view <package> dist-tags`), and say which. Record every package read in `meta.packages` (name → version) and a readable summary in `meta.version`.

## Sources, in order

Use the first source that yields machine-readable values; combine sources only to fill gaps, set `meta.source.kind` to `mixed` when you do, and record in `meta.source.notes` which part came from where.

1. **A published token file**: DTCG JSON, Style Dictionary output, or similar, shipped in the packages or the system's repository. For npm-shipped systems this usually means installing the packages and looking in their `dist` for JSON before reading JavaScript exports. Prefer resolved output (values, not aliases) when both are shipped, and keep the alias in `alias`.
2. **The packages' JavaScript exports**: the exported theme, token, spacing and type objects. Find the right exports from `package.json`, the type definitions and the README, not by guessing names.
3. **A Figma library**, when the user gives a file key and a Figma connector is available: its variables and styles.
4. **The documentation site**, as a last resort: crawl the token and component pages with `playwright-cli` and read values from the rendered docs. Say that values from docs pages are lower confidence than packaged ones.

Install into a scratch directory (`npm install --prefix <scratch> --ignore-scripts <packages>`), keep the normalizer outside it, and follow the downloaded-code rule in CONVENTIONS. Save the normalizer as `.claude/design-system/manifests/<slug>.resolve.<ext>` so the manifest can be regenerated for a new version without rediscovering the sources.

## Normalization

- **Scope:** public tokens and components only, the ones product code can reference. Leave out internal or private sets, and deprecated tokens and components unless the product uses them today (then keep them with `deprecated: true`). List what was left out in the notes.
- **Themes:** one key per theme the system ships for color scheme or brand (light/dark, high contrast, brand variants). Other value variants (density, pointer type, platform) are not themes: take the default variant, and record the others in the notes. A value that is the same in every theme goes under the key `"*"`. `defaultTheme` is the one the system documents as default.
- **Values:** as a browser computes them. Colors as `#rrggbb` or `rgba()`; dimensions in `px` (convert `rem` at 16px and say so in notes); durations in `ms`; font weights as numbers. Values relative to context (`em`, percentages) stay as authored; ds-map reports them as unparsed. Composite tokens (border, typography and transition shorthands) go in category `other` with the role they serve; shadows go in `shadow` with role `elevation`.
- **Names:** the name code uses, in the system's own convention (`$text-primary`, `--fgColor-muted`), so mapping output can be pasted into code.
- **Category:** from the system's own type information when present, otherwise from what the value is.
- **Role:** what the token is for, from the system's own grouping or naming scheme. Write in the notes the rule you applied (for example "prefix `fgColor` → text"). Leave `role` out when the system does not say; do not guess. ds-map only matches rendered values against tokens with a compatible role once a manifest has roles, so tokens for one component or domain (avatars, syntax highlighting, charts) keep no role or `tier: component`. Where the system's grouping hides a general-purpose token (a focus color filed under one component), assign the general role and note the override.
- **Tier:** primitive, semantic or component, when the system distinguishes them.
- **Text styles:** the system's typography sets, with line height as the system defines it (a ratio is fine).
- **Pairs:** only foreground/background combinations the system declares as allowed, by token name. If a declared pair has no level, use `body` (the strictest) and say so. If the system declares none, leave `pairs` empty and say so; do not invent them.
- **Components:** the catalog with variants and props. When sources disagree, the type definitions (`.d.ts`) of the installed version win over generated metadata, which wins over docs pages; note what each lacked. Record `importFrom` as code imports it.

## Check and confirm

```
python3 ${CLAUDE_PLUGIN_ROOT}/design-system/scripts/map.py check .claude/design-system/manifests/<slug>.manifest.json
```

Write `<slug>.notes.md` with: packages and versions, sources used, token counts per category and role, themes, text styles, declared pairs, components found, everything left out, and every gap (a category the system has no scale for, values that could not be resolved, roles left unset). A target with no radius scale, for example, is a real property of that system, and ds-map will report it as such.

Then show the user that summary and ask whether the manifest is right before anything uses it.
