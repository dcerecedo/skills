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
| [`derive-design-system`](skills/derive-design-system/SKILL.md) | Derives a design system from what the product ships: crawls the running app with [playwright-cli](https://playwright.dev/agent-cli/skills), compresses rendered values into DTCG tokens and component contracts, and measures coverage, contrast, visual diff and a codegen eval. Needs `@playwright/cli`; smoke test in `derive-design-system/tests/run.sh`. |

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
```
