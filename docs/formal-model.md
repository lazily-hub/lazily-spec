# Lean Formal Model

`formal/lean` is a small Lean 4 Lake package for the IPC Snapshot/Delta state
machine. It is a spec companion, not an implementation replacement.

The model proves the invariants that are easiest to blur across language
bindings:

- delta epochs are strictly sequential (`epoch = base_epoch + 1`);
- gap, reorder, and restart cases fail closed to snapshot resync;
- equal `set` writes are silent;
- equal memo recomputes suppress `slot_value` and downstream invalidation;
- eager Signal changes publish concrete `slot_value` ops rather than bare
  `invalidate` ops for their backing slot;
- batch flushes carry a coalesced frontier and advance the IPC epoch once;
- command-plane projection (`LazilyFormal.Command`): progress events never
  complete a command, only a terminal receipt does; stale generations are
  discarded; duplicate submits are idempotent; a cancel cannot override an
  applied command; conflicting terminal outcomes fail closed; reconnect
  projection is fold-equivalent; and an RPC `call` cannot resolve before a
  terminal receipt. This mirrors the standalone `lazily-formal` model.

The standalone
[`LazilyFormal.Reactive`](https://github.com/lazily-hub/lazily-formal/blob/main/LazilyFormal/Reactive.lean)
model owns the compute-graph disposal proofs. Its public `Handle` identity is
`(slot, generation, kind)`, and `disposeHandle` validates all three before it
can call the raw graph-mutation primitive. The model proves:

- `disposeHandle_stale_noop`: every rejected handle preserves the complete
  arena, including graph, generations, and cleanup history;
- `disposeHandle_generation_mismatch_noop` and
  `disposeHandle_kind_mismatch_noop`: same-kind ABA and cross-kind recycling
  are independently fenced;
- `disposeHandle_matching_effect_runs_cleanup` and
  `disposeHandle_stale_runs_no_cleanup`: only a matching live effect can append
  a cleanup event; and
- `disposeHandle_recycled_old_handle_noop`: after a slot is disposed and
  recycled, the old handle cannot delete the successor, even when the successor
  has the same node kind.

Run it through the local check target:

```bash
make check
```

Keep the Lean package narrow. JSON Schema, Rust implementation behavior,
cross-language conformance fixtures, Loom/thread-safe tests, and live transport
validation remain separate verification layers.
