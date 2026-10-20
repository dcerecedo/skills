# dcerecedo-skills

My Claude Code skills, packaged as one plugin. Skills are namespaced `/dcerecedo-skills:<skill>`.

## Install

At the Claude Code prompt:

```
/plugin install dcerecedo-skills --marketplace dcerecedo/skills
```

Answer `y` to add the marketplace, then pick the user scope to have it in every project. From a shell: `claude plugin install dcerecedo-skills --marketplace dcerecedo/skills`. Update with `claude plugin update dcerecedo-skills`, then `/reload-plugins`.

## Skills

| Skill | What it does |
| --- | --- |
| [`explain-flow`](explain-flow/README.md) | Explains the control flow behind the current issue with linked UML diagrams and domain-language prose, in a terminal pane and an offline browser view. |
| [`design-system`](skills/design-system/SKILL.md) | Design-system work grounded in what the product ships. Routes between the five steps below and stops for your decisions between them. Start here. |
| [`ds-inventory`](skills/ds-inventory/SKILL.md) | Crawls the running app with [playwright-cli](https://playwright.dev/agent-cli/skills) (routes × states × viewports) and scans the source: every rendered style value with counts, contrast pairs, screenshots, hardcoded values, component usage. Compare mode diffs two crawls. |
| [`ds-resolve`](skills/ds-resolve/SKILL.md) | Captures a third-party design system (package, token file, Figma library or docs site) into a neutral manifest. Nothing system-specific is built in. |
| [`ds-derive`](skills/ds-derive/SKILL.md) | Derives the product's own system from its inventory: DTCG-style tokens, scales with residuals, contrast-safe ramps, component contracts, each token with its evidence. |
| [`ds-map`](skills/ds-map/SKILL.md) | Fits an inventory or a manifest onto one or more target manifests: coverage in rendered instances, residuals, role mismatches, contrast, component gaps, side-by-side comparison. |
| [`ds-enforce`](skills/ds-enforce/SKILL.md) | Sets the codebase up to stay on the chosen system: tokens or target theme, rules for coding agents, lint with a legacy baseline, axe, drift job, and a codegen eval. |
| [`coach`](skills/coach/SKILL.md) | Coaches you in a language, framework or practice (testing, refactoring, design decisions) while you work real tickets: `setup`, `ticket`, `review`, `probe`, `log`. You write the spec, code and rationale; it challenges, reviews, runs execution-graded spaced-repetition probes and records mastery only from observed evidence, in a local git repo at `~/.claude/coach/`. Stack knowledge lives in `coach/profiles/` (python, django). |

## Configure

Settings live in `/config` under `dcerecedo-skills`. Keys a skill owns carry its name (`explainFlowOutputDir`); the rest (`editorUrl`, `browserCommand`, `python`) are shared. A repo overrides them in `.claude/dcerecedo-skills.json`: shared keys at the top level, a skill's own in a section named after it. Each skill's README lists its keys.

## Develop

```bash
claude plugin validate .
claude plugin test .
claude --plugin-dir .    # load this working copy for one session; edits hot-reload
```

## Layout

```
.claude-plugin/plugin.json       manifest: name, skills, settings
.claude-plugin/marketplace.json  makes this repo the `dcerecedo` marketplace
skills/<skill>/SKILL.md          one folder per skill
hooks/hooks.json                 the plugin's hooks modules, one per skill that has a mod
<skill>/                         a skill's mod code, assets and tests
design-system/                   shared by the ds-* skills: CONVENTIONS.md, schemas/, scripts/, crawl template, tests
coach/                           coach steps, STATE.md, profiles/<stack>.md, scripts/ (kg.py, logstats.py), tests
```

The design-system skills need `@playwright/cli` (written against 0.1.22) for crawling. Tests: `design-system/tests/run.sh` (end to end, needs a browser; `PW_CONFIG=<playwright-cli.json>` to point at a custom Chromium) and `python3 -m unittest design-system/tests/test_map.py` (no browser).

Coach tests: `python3 -m unittest coach/tests/test_coach_scripts.py`. Plugin skills are namespaced, so the command is `/dcerecedo-skills:coach <subcommand>`.
