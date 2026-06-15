# Lean Formal Model

`formal/lean` is a small Lean 4 Lake package for the IPC Snapshot/Delta state
machine. It is a spec companion, not an implementation replacement.

The model proves the invariants that are easiest to blur across language
bindings:

- delta epochs are strictly sequential (`epoch = base_epoch + 1`);
- gap, reorder, and restart cases fail closed to snapshot resync;
- equal `set_cell` writes are silent;
- equal memo recomputes suppress `slot_value` and downstream invalidation;
- eager Signal changes publish concrete `slot_value` ops rather than bare
  `invalidate` ops for their backing slot;
- batch flushes carry a coalesced frontier and advance the IPC epoch once.

Run it from `formal/lean`:

```bash
lake build
```

Keep the Lean package narrow. JSON Schema, Rust implementation behavior,
cross-language conformance fixtures, Loom/thread-safe tests, and live transport
validation remain separate verification layers.
