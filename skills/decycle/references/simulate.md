# Plan format for `simulate`

```json
{
  "remove": "shop.billing -> shop.orders",
  "steps": [
    {
      "id": "01",
      "title": "Invoices take a Billable instead of an Order",
      "strategy": "invert",
      "ops": [
        {"op": "add_module", "module": "shop.billing.billable"},
        {"op": "add_import", "importer": "shop.billing.invoice", "imported": "shop.billing.billable"},
        {"op": "remove_import", "importer": "shop.billing.invoice", "imported": "shop.orders.models"}
      ]
    }
  ]
}
```

- `remove`: the sibling dependency this problem eliminates, `lower -> higher`. At the end of the plan, no module inside `lower` may import anything inside `higher`.
- `steps`: in order; each becomes one ticket. Operations are cumulative across steps.
- Module names are full dotted names. Operations work on modules (files), not packages; the script lifts them to sibling dependencies at every package level.

| Op | Fields | Effect |
|---|---|---|
| `add_module` | `module` | New module (its parent packages are created if missing). Fails if it exists |
| `remove_module` | `module` | Deletes the module and every import from or to it |
| `add_import` | `importer`, `imported` | Both must exist by then |
| `remove_import` | `importer`, `imported` | Must exist. One module importing another counts once, however many names it imports |
| `merge_module` | `source`, `target` | Every import from or to `source` now belongs to `target`; `source` disappears |

A step fails if, after its operations, any sibling dependency anywhere in the package is on a cycle that was not on one before the step, or if any import breaks a decision recorded in `.decycle/decisions.json`. The plan fails if `remove` still has imports after the last step.

Model what the code will really look like, including imports a step adds on the other side (callers that now import the moved symbol from its new home, re-exports, the composition root that wires a protocol). An optimistic plan passes the simulation and then fails `lint-imports` during `/implement`.
