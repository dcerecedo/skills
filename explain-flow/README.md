# explain-flow

A Claude Code skill and mod. Ask Claude to explain the flow you are working on and it traces the code, then renders:

- a terminal pane with the explanation's paragraphs, the diagram elements each one covers, and editor links to the code;
- an offline HTML page with the UML diagrams in tabs (component, sequence, and state or activity when they help), the prose always visible beside them, and two-way highlighting between paragraphs and diagram elements.

Part of the [`dcerecedo-skills`](../README.md) plugin; install it from there.

Requirements: `git`; `python3` for Python repositories (standard library only); `xdg-open` or another opener for the browser page.

## Use

- `/dcerecedo-skills:explain-flow [focus]`, or just ask "explain how the rebooking flow issues door codes".
- `/flow-view` reopens the pane; `/flow-view list` lists saved explanations; `/flow-view <slug>` reopens one and rebuilds its page.
- Pane keys (once the pane has focus): `1`–`9` tabs, `j` / `k` next and previous paragraph, `o` open the browser page at the current tab and paragraph.
- Browser page: click a paragraph or use `j` / `k`; click a diagram element to jump to the paragraphs that explain it (click again to cycle); double-click an element to open its code; `1`–`9` tabs, `+` / `-` / `0` zoom, `l` legend, `t` theme, Esc clears.

Explanations are saved as `<slug>.json` and `<slug>.html` under `explainFlowOutputDir`, `.claude/explanations/` in the repo by default (add it to `.gitignore` if you don't want them committed). To have them expire instead, set it to `/tmp/explain-flow/{repo}`.

## Configure

Plugin settings (in `/config`, under `dcerecedo-skills`):

| Setting | Default | |
| --- | --- | --- |
| `editorUrl` | `vscode://file/{abs}:{line}` | shared by the plugin's skills. `{abs}`, `{path}`, `{line}` placeholders. Cursor: `cursor://file/{abs}:{line}` |
| `browserCommand` | `xdg-open` | shared. macOS: `open` |
| `python` | `python3` | shared. e.g. `.venv/bin/python` |
| `explainFlowOutputDir` | `.claude/explanations` | relative to the repo root, or absolute; `{repo}` is the repo folder's name, e.g. `/tmp/explain-flow/{repo}` |
| `explainFlowOpenBrowser` | `true` | open the page after every render |

A repo can override them in `.claude/dcerecedo-skills.json`: shared keys at the top level, this skill's in its `explain-flow` section (`outputDir`, `openBrowser`, and any shared key), which is also where resolvers for other languages go:

```json
{
  "editorUrl": "cursor://file/{abs}:{line}",
  "explain-flow": {
    "outputDir": "docs/flows",
    "resolvers": [
      { "name": "ruby", "extensions": [".rb"], "command": ["ruby", "/path/to/resolve.rb"] }
    ]
  }
}
```

The skill's section wins over the top level, which wins over plugin settings.

A resolver speaks the JSON protocol in `resolvers/PROTOCOL.md`. Files no resolver claims get the stack-agnostic text check.

Issues are read through the issue-tracker skill or CLI the project already has (TWG, for example), as its own instructions say; the mod has no tracker configuration.

## What is checked

The render tool refuses an explanation until every id, highlight and code reference holds:

- structure: unique ids, edges and messages between known nodes and participants, highlights that exist in their diagram, a component and a sequence diagram, at most 25 messages per sequence diagram;
- references: the file exists and holds the line; for a definition, the symbol is defined there; for a call, the callee is reached from that call site.

The Python resolver uses `ast` and follows the Django hops a plain call graph misses (URL routing, signal receivers, Celery `.delay`). A call it proves is drawn solid; a call it can only place by name (dynamic dispatch) is drawn dotted with a `?` and its tooltip says why. Without a resolver, calls are never marked verified.

## Layout

```
../skills/explain-flow/SKILL.md   the prompt
../hooks/hooks.json               loads hooks/register.tsx below as the plugin's module
hooks/                            the mod: tools, /flow-view, pane, validation, page builder
types/index.d.ts                  the explanation model and the mod's state
viewer/                           the page template and vendored ELK (EPL-2.0)
resolvers/                        protocol and the Python/Django resolver
tests/                            plugin tests and a small Django fixture
```

Tests, from the repository root: `claude plugin test .` and `python3 -m unittest discover -s explain-flow/resolvers/python`.
