# Profile: python

status: verified
namespaces: py
docs: https://docs.python.org/3.<minor>/ (the project's Python version), the installed package source for third-party libraries

## Detection

Any of these:
- `pyproject.toml`, `setup.cfg`, `setup.py`, or `requirements*.txt` at the root
- `*.py` files under version control (`git ls-files '*.py'`)

Record the version from `.python-version`, `requires-python` in `pyproject.toml`, the CI matrix, or the `Dockerfile` base image. Use that one, not the interpreter that happens to be on PATH.

## Gates

Use the command the repo's CI runs when it differs from the candidates below. A gate whose tool isn't configured in the repo is "not available". Don't introduce one in a coaching session.

| Gate | Candidate commands | Regression rule (review.md) |
| --- | --- | --- |
| tests | `pytest -q` · `python -m pytest -q` · `python -m unittest` | a test green on base is red on HEAD |
| coverage | `pytest --cov --cov-report=json:.coach/logs/coverage.json --cov-report=term` (pytest-cov) · `coverage run -m pytest && coverage json -o .coach/logs/coverage.json` | total −0.5 points, or changed non-test lines uncovered |
| lint | `ruff check <changed files>` · `flake8 <changed files>` | new findings in changed files |
| format | `ruff format --check <changed files>` · `black --check <changed files>` | changed files not formatted |
| types | `mypy <changed files>` · `pyright <changed files>` (only if configured) | new errors in changed files |
| mutation | mutmut ≥ 3: scope with `source_paths` (and `mutate_only_covered_lines = true`) in `[tool.mutmut]`, then `mutmut run "<module>.<function>*"` for each changed function; inspect with `mutmut browse` or `mutmut apply <mutant>` in a throwaway worktree. mutmut needs `os.fork` (Linux, macOS, WSL). | surviving mutants in changed functions |

Check `mutmut --version` first. Its configuration and command-line interface changed between 2.x and 3.x, and the 2.x `--paths-to-mutate` flag does not apply to 3.x.

## Probes (execution-graded)

Each probe's pass criterion is written down before the user answers (probe.md).

| Type | User does | Grading command | Pass |
| --- | --- | --- | --- |
| predict-then-run | Predicts the return value, stdout or exception for a call into their own code with given inputs | a scratch test in `.coach/logs/probes/` that calls it and prints `repr()` of the result, or `pytest -q <scratch>` | prediction matches exactly (value and type; exception class) |
| kill-this-mutant | Writes a test that kills one mutant you applied to a function they wrote. Mutants: boundary `<`↔`<=`, negated condition, removed call, swapped arguments, constant changed, `return` of a default. | in a worktree: the test passes on the original and fails on the mutant (`pytest -q <test>` twice) | both conditions |
| trace-the-exception | Predicts which exception reaches which frame (the handler that catches it, or the traceback's last frame in their code) | run the scratch call and read the traceback | exception class and frame match |
| type-predict | Predicts whether the type checker accepts a snippet built from their code, and the error if not (only if a type checker is a gate) | `mypy` or `pyright` on the scratch file | accept/reject and error code match |

Concepts these grade well: mutability and aliasing, default arguments, iteration and generators, closures and late binding, exceptions and context managers, datetime awareness and time zones, decimal versus float, `dataclasses` and equality, import side effects, and in `general.testing`, test design, fixtures and mocks.

## Logging fields

Beyond the core five: `exc_type` on error lines, and `logger` (the module that logged).

## Review checks

- Mutable default arguments, shared state at module level.
- Broad `except Exception` that hides failures, or `except` without re-raise around I/O.
- Naive datetimes crossing a boundary: database, API, logs.
- `float` for money.
- Tests that assert on mocks of the code under test rather than on its behaviour.
