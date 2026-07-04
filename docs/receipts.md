# Causal Receipts

`CausalReceipt` is lazily's generic outcome projection for commands and effect
requests keyed by a stable `causation_id`.

It is intentionally not a transport ACK. `observed` and `accepted` are
non-terminal receipt outcomes; they can record that a peer saw or queued work.
`applied` and `rejected` are terminal outcomes. Domain-specific facts may refine
those terminal outcomes, but they should not invent a delivery-ACK authority.

```json
{{#include ../conformance/receipts/causal_receipts.json}}
```

The normative field list and projection rules live in
[protocol.md § Causal Receipts](protocol.md#causal-receipts). The schema is
[`schemas/receipts.json`](schemas.md#receiptsjson).
