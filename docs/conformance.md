# Conformance Fixtures

The `conformance/` directory contains canonical test fixtures that all IPC-capable bindings must
validate against. Each binding's CI should deserialize the `wire` field, run the assertions, and
re-serialize to confirm round-trip fidelity.

## Fixture schema

```json
{
  "description": "Human-readable summary",
  "protocol_version": 1,
  "kind": "Snapshot" | "Delta",
  "assertions": { "…language-agnostic field checks…" },
  "wire": { "…IpcMessage as serde_json…" }
}
```

## Current fixtures

| Fixture | Kind | Description |
|---------|------|-------------|
| `snapshot_minimal.json` | Snapshot | One payload node, no edges |
| `snapshot_multi_node.json` | Snapshot | Multiple nodes and edges |
| `snapshot_shared_blob.json` | Snapshot | SharedBlob node state |
| `delta_sequential.json` | Delta | All 7 DeltaOp variants, sequential |
| `delta_non_sequential.json` | Delta | Non-sequential delta with gap |
| `delta_shared_blob.json` | Delta | CellSet/SlotValue with SharedBlob |

## Adding a new binding

Copy the fixture-loading pattern from `lazily-rs/tests/conformance.rs`. Each test should:

1. Load the fixture.
2. Parse the `wire` field into the binding's native `IpcMessage` type.
3. Assert the `assertions` fields.
4. Re-serialize and compare for byte-for-byte round-trip fidelity.

## Keyed cell collections conformance

The `conformance/collections/` directory contains canonical fixtures for the
[keyed cell collections](cell-model.md#keyed-cell-collections) layer, which is **required
of every binding** (see the [Binding Conformance Matrix](protocol.md#binding-conformance-matrix)).
These are **compute** fixtures, not wire fixtures: a binding loads the `initial` state,
replays each `step`'s `op`, and asserts the `expected` effects (resulting `order`,
`values`, `membership`, and which reader classes — `value` / `membership` / `order` —
invalidate). The reconciliation fixture is declarative: diff `prior` → `target` and
assert the emitted minimal op set.

| Fixture | Covers |
|---------|--------|
| `collections/cellmap_independence.json` | value / set-membership / order reactivity independence |
| `collections/cellmap_atomic_move.json` | atomic ordered move keeps handle, bumps order once |
| `collections/keyed_reconciliation_lis.json` | LIS move-minimized reconciliation; stable entries not invalidated |
| `collections/semtree_incremental.json` | memoized semantic tree: ancestor-chain-only recompute, sibling isolation, memo guard |
| `collections/seqcrdt_convergence.json` | move-aware sequence CRDT: single-LWW move, concurrent-move/value-edit independence, tombstone convergence, commutativity |
| `collections/textcrdt_convergence.json` | Fugue/RGA character CRDT: concurrent same-point inserts, sticky tombstone, commutative/idempotent merge, GC |
| `collections/stableid_alignment.json` | manufactured text identity: anchors / content hashes / word-LCS similarity alignment |

## Examples

### `snapshot_minimal.json`

```json
{{#include ../conformance/snapshot_minimal.json}}
```

### `snapshot_multi_node.json`

```json
{{#include ../conformance/snapshot_multi_node.json}}
```

### `snapshot_shared_blob.json`

```json
{{#include ../conformance/snapshot_shared_blob.json}}
```

### `delta_sequential.json`

```json
{{#include ../conformance/delta_sequential.json}}
```

### `delta_non_sequential.json`

```json
{{#include ../conformance/delta_non_sequential.json}}
```

### `delta_shared_blob.json`

```json
{{#include ../conformance/delta_shared_blob.json}}
```
