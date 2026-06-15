# lazily Lean formal model

This Lake package is a small formal companion to the IPC section of
`lazily-spec`. It models the Snapshot/Delta state plane and proves the
high-value invariants shared by lazily-rs and the other lazily bindings.

## Scope

The model intentionally stays above implementation internals. It does not try
to verify Rust source, async scheduling, Str0mNet/WebRTC transport behavior, or
the JSON Schema encoders. Those remain covered by implementation tests and
conformance fixtures.

The current proofs cover:

- `Delta` sequencing: `nextDelta` always creates `epoch = base_epoch + 1`.
- Gap handling: non-sequential deltas fail closed to resync instead of apply.
- `PartialEq` cell guard: equal cell writes emit no `cell_set` op.
- Memo equality suppression: equal memo recompute emits no `slot_value` or
  downstream `invalidate`.
- Eager Signal materialization: changed signals emit `slot_value`, never a bare
  `invalidate` for the signal backing slot.
- Batch coalescing: a `BatchFlush` carries a no-duplicate frontier and emits one
  delta that advances the IPC epoch once.

## Verify

```bash
lake build
```

The package is pinned by `lean-toolchain` to Lean 4.30.0.
