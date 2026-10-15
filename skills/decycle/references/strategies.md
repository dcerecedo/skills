# Strategies

Each symbol that crosses a dependency in the wrong direction (from the lower package into the higher one) needs exactly one of these. Choose by asking what the symbol is and where its responsibility belongs; the cheapest edit is not the criterion.

| Strategy | Use when | Graph operations (see `simulate.md`) | Watch out for |
|---|---|---|---|
| **move** | The symbol is used by the lower package and belongs to it, or to neither but sits in the higher one by accident | `remove_import` lower → higher; `add_import` higher → lower for each higher-side caller that now needs it | Many callers: expand-contract. The re-export left in the old home is an import from higher to lower, which is the allowed direction; never the reverse |
| **split** | One module of the higher package holds two responsibilities at different levels, and only the lower-level part is imported from below | `add_module` for the new module inside the lower package (or a new sibling below both); `remove_import` lower → old module; `add_import` from the old module and from the lower package to the new one | Name the new module after the responsibility it holds, not after where it came from |
| **extract** | Both packages need a concept that neither owns: a value object, an enum, an error type, a protocol | `add_module` for a new package below both; `remove_import` of the crossing import; `add_import` from both sides to the new package | A `common`, `utils`, `shared` or `helpers` name means the concept is not yet found. The new package must import neither side, or it rejoins the cycle |
| **invert** | The lower package must call behaviour that the higher package implements | `remove_import` lower → higher; `add_module` for a `Protocol` or ABC owned by the lower package if it does not live in an existing module; `add_import` higher → lower (the implementation conforms to the protocol); the wiring happens where both are already imported (composition root, app setup, DI container) | The protocol belongs to the lower package's language and needs only what the lower package calls |
| **inject** | One call site in the lower package needs a value or a callable from the higher one | `remove_import` lower → higher; no new imports: the caller in the higher package passes it as an argument | Fine for one or two call sites; more than that usually means **invert** |
| **merge** | The two packages change together, share one responsibility, and were split by accident | `merge_module` per module of the smaller package into its counterpart, or `add_module` + moves when merging into a new package | Last resort: it removes the boundary instead of fixing it. Say why the split was accidental, and check the merged package still reads as one responsibility |

Not strategies, because they hide the dependency instead of removing it: importing inside a function, `importlib.import_module` or `__import__` with a string, moving the import under `if TYPE_CHECKING:`, and string annotations used to avoid an import. A dependency only used in annotations is still a dependency; remove it with one of the strategies above.

## Characterization tests

A step that only moves code has no new behaviour to test first. Its tests are of two kinds:

- **Characterization**: tests that pin the current behaviour of the crossing symbols through the public entry points that use them, written and passing before the step changes anything. Reuse existing tests when they already cover it; name the ones that do in the ticket.
- **Structural (the red test)**: deleting this step's lines from the import-linter `ignore_imports` lists makes `lint-imports` fail until the step is done.
