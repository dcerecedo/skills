# Resolver protocol

A resolver checks code references for the files whose extensions it claims.
The mod runs its `command` with one JSON request on stdin and reads one JSON
answer from stdout. Exit code 0 means the answer is valid; anything else makes
the mod fall back to its text check for those references.

## verify

Command: `<command> verify`

```json
{
  "root": "/abs/repo",
  "checks": [
    { "key": "7", "path": "app/locks/service.py", "line": 57, "end": 57,
      "role": "call", "code": "LockService.issue_code", "via": "call" }
  ]
}
```

`role` is `def` (the ref should point at the definition of `code`), `call`
(the ref is a call site that should reach `code`), `within` (the ref is a line
inside the body of `code`, where an activity step or a state transition
happens) or `any` (the line just has to exist). A resolver that does not know
a role answers `ok` for it. `via` is a hint about how the call travels: `call`, `url`,
`signal`, `task`, `orm`, `http`, `event` or `other`.

Answer:

```json
{ "results": { "7": { "status": "verified", "reason": "direct call at line 57" } } }
```

`status` is one of `ok` (def, within or any: found), `verified` (call: statically
resolved), `unverified` (call: the name is there but the resolver cannot prove
the hop, e.g. dynamic dispatch) or `error` (the reference is wrong; `reason`
says what is actually there so the model can fix it).

## seed (optional)

Command: `<command> seed`

```json
{ "root": "/abs/repo", "entry": "app/api/bookings.py:88", "depth": 3, "maxNodes": 120 }
```

Answer: `{ "functions": [...], "edges": [...], "notes": [...] }`, a static call
tree from the function that contains the entry line. Each function has `id`,
`qualname`, `path`, `line`; each edge `from`, `to` (function ids, or null when
unresolved), `name`, `line`, `via` and `candidates` when the name is ambiguous.
The model uses it as a map to read from, never as the explanation itself.
