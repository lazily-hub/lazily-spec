# Command / RPC Message Plane

Editor and runtime integrations need to *issue commands* — `Run Agent Doc`,
sync, focus, save, session operations — with a single reusable admission,
dedupe, cancellation, generation-guard, progress, and reconnect story. Without
one, every caller reinvents in-flight/dedupe/supersede/retry/timeout logic, and
`accepted` / `queued` feedback gets mistaken for terminal success.

lazily's command plane (`command-plane-v1`) is that shared substrate. It is an
**additive sibling** to `Snapshot` / `Delta` / `CrdtSync`, not a replacement:
command frames can ride the same transports and reflect into the normal state
graph, but they carry command traffic, not cell state.

## The four frames

| Frame | Role |
|-------|------|
| `CommandSubmit` | Submit a command: envelope + domain payload (an `IpcValue`) |
| `CommandCancel` | Preempt a still-non-terminal command by `command_id` |
| `CommandEvents` | Progress/detail events (UX + diagnostics only, never proof) |
| `CommandProjection` | Folded, queryable command state; also the reconnect resync image |

lazily owns the envelope; the **namespace owns the payload**. lazily never
decodes `payload`. Agent-doc publishes its own payload schemas
(`agent-doc.editor_route.v1`, `agent-doc.sync_tmux_layout.v1`, …) and only
references lazily's envelope.

## Progress is not proof

The single hard rule: **terminal authority is the causal receipt.** A command is
terminal only when a terminal [`CausalReceipt`](receipts.md) for its
`command_id` folds in (`applied`, or `rejected` — including the `cancelled` /
`superseded` / `timed_out` reasons). `observed` / `accepted` / `started` /
queued-admission events are non-terminal progress. A transport ACK is never
terminal.

This keeps command events from becoming a second proof system. Events may carry
queue position, retry advice, or copied CLI output; the effect still folds
through receipts and domain facts.

## RPC is a facade

`call` / `submit` / `cancel` / `observe` / `projection` are implemented entirely
over the four frames:

```ts
await client.call("agent-doc.editor_route", payload, {
  commandId,
  idempotencyKey: "project-root:plan.md:run",
  authorityGeneration: 42,
  deadlineMs: 120000,
  policy: { dedupe: "same_idempotency_key", supersede: false, cancelOnPreempt: true }
});
```

`call` resolves **only** on a terminal causal-receipt projection. A network ACK,
controller admission, or `accepted` / queued event never resolves a unary
`call`. `submit` returns the `command_id` for callers that manage events and
projection themselves. Reconnect uses `CommandProjection`; a `call` replays only
when the idempotency policy says replay is safe.

## Rules

- **Generation guards** — events/receipts outside the command's current
  authority generation are ignored (kept only as audit data).
- **Idempotency** — replaying a submit/event/receipt with a known id is a no-op.
- **Cancel before terminal only** — a cancel after `applied` is ignored.
- **Terminal conflict fails closed** — `applied` vs `rejected` at the same
  generation is not resolved by winner selection.
- **Reconnect equivalence** — folding a `CommandProjection` equals folding the
  events and receipts it summarizes.

The normative field list and rules live in
[protocol.md § Command / RPC Message Plane](protocol.md#command--rpc-message-plane).
The schema is [`schemas/message-passing.json`](schemas.md#message-passingjson).
Conformance fixtures live in `conformance/message-passing/`; each binding
replays them through its `CommandProjection` reducer and RPC facade.

```json
{{#include ../conformance/message-passing/accepted_then_applied_receipt.json}}
```
