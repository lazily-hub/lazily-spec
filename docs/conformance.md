# Conformance Fixtures

The `conformance/` directory contains canonical test fixtures that all IPC-capable bindings must
validate against. Each binding's CI should deserialize the `wire` field, run the assertions, and
re-serialize to confirm round-trip fidelity.

## Fixture schema

```json
{
  "description": "Human-readable summary",
  "protocol_version": 1,
  "kind": "Snapshot" | "Delta" | "Receipt",
  "assertions": { "…language-agnostic field checks…" },
  "wire": { "…canonical protocol JSON…" }
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
| `receipts/causal_receipts.json` | Receipt | Causal receipt projection with non-terminal and terminal outcomes |

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
| `collections/textcrdt_delta_sync.json` | `TextCrdt` delta sync (`#lztextsync`): `version_vector` (insert + tombstone ids), `delta_since` / `apply_delta`; bidirectional exchange convergence, whole-snapshot fork identity preservation, idempotent apply |
| `collections/stableid_alignment.json` | manufactured text identity: anchors / content hashes / word-LCS similarity alignment |

## Materialization mode conformance

The `conformance/materialization/` directory pins the eager-default / lazy-opt-in
[materialization mode](cell-model.md#materialization-mode) axis (`#lzmatmode`),
proved in [lazily-formal](formal-model.md)'s `Materialization` module. These are
**compute** fixtures: a binding reads `spec.val` (each derived key's canonical
value), builds the keyed family under *both* modes, replays the `reads` sequence
against the lazy build, and asserts observational transparency plus the memory
laws. Because materialization is *not observable on the value axis*, there is no
wire schema — only the compute effects below.

| Fixture | Covers |
|---------|--------|
| `materialization/observational_transparency.json` | identical `observe` values under eager vs. lazy; eager materializes all keys; lazy materializes only read keys; default mode eager (`observe_canonical`, `eager_materializes_all`, `lazy_defers_slots`, `default_mode_eager`) |
| `materialization/deferral_not_deallocation.json` | lazy present set grows monotonically and is unchanged by re-reads; final lazy set is a subset of the eager set; no churn from allocation (`materialize_present_monotone`, `lazy_present_subset_eager`, `materialize_preserves_observe`) |

## Signaling conformance

The `conformance/signaling/` directory pins the WebSocket signaling wire protocol
(see [protocol.md § Signaling Protocol](protocol.md#signaling-protocol-websocket)),
the cross-language contract shared by every distributed-plane binding and the
reference TypeScript signaling server.

- `signaling/frames.json` is a **wire** fixture: each entry's `wire` field is the
  canonical JSON for one `ClientMessage` / `ServerMessage` variant and validates
  against `schemas/signaling.json`. A binding encodes its typed message to the same
  JSON and decodes the JSON back. Tags are kebab-case (`peer-joined`, `peer-left`);
  `peer` ids are bare numbers ≤ 2⁵³−1. Client-directed frames carry `to`;
  server-forwarded frames carry a server-stamped `from`.
- `signaling/anti_spoof_session.json` is a **compute** fixture: a binding that
  implements the server room replays each `input` and asserts the emitted `expect`
  frames. It pins the load-bearing invariants — the `welcome` roster excludes the
  joining peer, a forwarded frame's `from` is the sender's server-registered id
  (never client-supplied), and an unknown target yields an `error` frame.

## Distributed (CRDT plane) conformance

The `conformance/distributed/` directory pins the CRDT anti-entropy plane
(see [protocol.md § Distributed](protocol.md#distributed-crdt-cell-plane)).

- `distributed/crdt_sync_frames.json` is a **wire** fixture: each `wire` is a
  `{"CrdtSync": {frontier, ops}}` envelope validating against
  `schemas/distributed.json` (empty, keyed+keyless ops, and a multi-peer frontier).
- `distributed/anti_entropy_converge.json` is a **compute** fixture: a binding
  replays each scenario's `ops` through its `CrdtPlaneRuntime` and asserts
  convergence to `expect.converged` independent of delivery order, plus state-based
  idempotence (re-ingesting a seen frame applies 0 new ops). It models LWW cells
  where the plane `WireStamp` is the decisive stamp under lexicographic
  `(wall_time, logical, peer)` order.

## Lossless tree conformance

The `conformance/lossless-tree/` directory pins the lossless full-document tree
CRDT (see [Lossless Tree CRDT](lossless-tree-crdt.md), `#lzlosstree`). These are
**compute** fixtures with the same `{scenarios: [{seed, steps, expect}]}` shape as
the collections fixtures: a binding builds the `seed.tree` on replica `a`
(addressing nodes by stable string `label`s), replays each `step` (`fork` /
`clone` / `sync` / `deliver` an op subset / `on` a replica an op — `create`,
`edit_leaf`, `split`, `merge_leaves`, `reorder`, `tombstone`), and asserts the
`expect` fields: `render` / `render_on` (exact rendered text per replica),
`live_nodes` (live element+leaf count, excluding the root), and `converged` (a set
of replicas that must render identically). Byte offsets in ops (`at_byte`) are
**UTF-8** and must land on a char boundary.

| Fixture | Covers |
|---------|--------|
| `lossless-tree/exact_roundtrip.json` | Token/Trivia/Raw/Error leaves incl. an invalid span + multi-byte text; `render == source` |
| `lossless-tree/one_leaf_edit_delta.json` | one-leaf edit at a UTF-8 byte offset in multi-byte text, delivered by anti-entropy |
| `lossless-tree/split_merge.json` | split a leaf then merge back; render preserved; live-node count grows then restores |
| `lossless-tree/concurrent_insert_same_parent.json` | two replicas insert into the same gap; both survive, deterministic order, converge |
| `lossless-tree/concurrent_reorder_and_leaf_edit.json` | concurrent reorder + text edit both apply (position/text are independent registers) |
| `lossless-tree/non_contiguous_anti_entropy.json` | a delivery hole is representable in the dotted frontier, re-requested, and converges |
| `lossless-tree/token_trivia_preservation.json` | a leaf edit leaves adjacent Token/Trivia leaves byte-for-byte unchanged |
| `lossless-tree/invalid_source_roundtrip.json` | unclosed fence/comment kept as Error leaves round-trips exactly; editing an adjacent Raw leaf keeps the Error spans |
| `lossless-tree/concurrent_conflict_preserves_text.json` | incompatible concurrent shapes both survive with no bytes dropped (text preservation wins over semantic shape) |

The op-delta **wire** form additionally validates against `schemas/lossless-tree.json`
(vocabulary) + `schemas/lossless-tree-delta.json` (the `TreeUpdate` message); the
Rust reference and each port validate their serialized `TreeUpdate` against these.

## Causal receipt conformance

The `conformance/receipts/` directory pins lazily's generic outcome vocabulary
for commands and effect requests (see
[protocol.md § Causal Receipts](protocol.md#causal-receipts)).

- `receipts/causal_receipts.json` is a **wire + compute** fixture: its `wire`
  field validates against `schemas/receipts.json`, and bindings replay the
  receipts into their projection. The stale-generation receipt is ignored by the
  current projection; `observed` / `accepted` remain non-terminal; `applied` is
  the terminal outcome.

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
