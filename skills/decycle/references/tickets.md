# Tickets

Tickets follow the local ticket format of the mattpocock `to-tickets` skill, so `/implement` reads them like any other set. Write them directly; do not run `/to-tickets` on them.

- Folder: `.scratch/decycle-<NN>-<slug>/issues/`, where `<slug>` names the problem, for example `billing-below-orders`.
- One file per ticket: `<NN>-<slug>.md`, numbered from `01` in dependency order, blockers first.
- Language: the one the repository's docs use; English if unsure.
- Name modules by their dotted names: here the modules are the spec. Leave out line numbers and code snippets; they go stale.

## Which tickets

1. **Guard or lock** (`01`, blocked by none).
   - No import-linter config in the repo yet (scan reported `guard: absent`): add import-linter as a dev dependency, add the whole `guard` output to the project's config, and make `lint-imports` run wherever the tests run (CI, pre-commit, Makefile or tox, whichever the project uses).
   - Guard already present: add only this decision's `forbidden` contract block from the `guard` output.
   - Either way the code does not change and `lint-imports` passes with the ignore lines in place. From this ticket on, no new cycle and no new import against this decision can land.
2. **One ticket per plan step**, blocked by `01` and by the steps before it that it needs.

## Step ticket template

```markdown
# <NN> — <Step title in domain language>

**What to build:** <What changes in the structure and why, from the point of view of someone reading the code: which responsibility moves where, or which package stops knowing about which. One short paragraph.>

**Strategy:** <move | split | extract | invert | inject | merge>: <one line>

**Blocked by:** <numbers and titles, or "None — can start immediately">

**Status:** ready-for-agent

**Red test:** delete these lines from `ignore_imports` in the import-linter config, then `lint-imports` fails until this ticket is done:
- `<importer> -> <imported>` (contract `<contract name>`)

- [ ] Characterization tests pin the current behaviour of <crossing symbols> through <public entry points>; they pass before any change (existing tests that already do this: <names, or "none">)
- [ ] The `ignore_imports` lines above are deleted and `lint-imports` passes
- [ ] No `ignore_imports` line was added anywhere
- [ ] No function-local import, `importlib` import or `TYPE_CHECKING` guard was introduced to get there
- [ ] The full test suite and the type checker pass
```

When a step removes none of the listed `ignore_imports` lines (for example, the expand half of expand-contract), its red test is a characterization test for the symbol at its new home, and the first acceptance criterion says so.

The last step ticket also checks that this decision's `forbidden` contract has no `ignore_imports` left and that the acyclic contract has no line for this pair of packages.

## Jira

When publishing, each issue gets the ticket's title as summary and its body as description, the issue for each blocker as a blocking link, and its key added to the local file under the title as `**Tracker:** <KEY>`. The local files stay the source `/implement` reads.
