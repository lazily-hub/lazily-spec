# CrdtTree Contract (`#lzcrdttree`)

`CrdtTree` is the shared lossless document-CRDT seam used by snapshots, relay
canonicals, and document-op replication. An implementation exposes:

- `version_vector()` — a compact distributed frontier;
- `delta_since(frontier)` — every operation the frontier has not observed;
- `apply_delta(delta)` — an identity-preserving, idempotent fold;
- `text()` / `value()` — the visible lossless projection; and
- `merge_from(other)` — the state join.

The join and delta fold are commutative, associative, and idempotent. A full
snapshot is exactly `delta_since(empty_frontier)`; applying it to an empty replica
must preserve operation identities, not reparse the visible text and mint a new
lineage. Applying `delta_since(version_vector())` is a no-op.

The compute fixture at
[`conformance/crdt-tree/algebra.json`](../conformance/crdt-tree/algebra.json)
pins merge order independence, idempotence, snapshot equivalence, and incremental
round-trip behavior. The Lean model in `LazilyFormal.Replication` pins the three
join laws.
