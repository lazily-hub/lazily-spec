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
4. Re-serialize and compare for byte-for-byte round-trip fidelity, subject to the
   equivalence exemptions below.

### Round-trip equivalence exemptions

Byte-for-byte comparison is the default, but it is **not** the contract for a field whose
schema declares two encodings equivalent. Where the schema says a field may be omitted *or*
sent in some canonical empty form, a binding MUST NOT be required to reproduce the sender's
choice: both encodings decode to the same value, so a binding is free to emit either one.

For such fields the round-trip comparison is **semantic**: normalize the fixture's `wire` and
the binding's re-serialized output to the same canonical form (fill in the declared default for
an absent field) before comparing. All other fields remain byte-for-byte.

Exempt fields:

| Field | Equivalent encodings | Declared by |
|-------|----------------------|-------------|
| `CrdtSync.frontier` | omitted ≡ `[]` — "unchanged since the last accepted frame" (`#lzspecfrontiersuppress`) | [`schemas/distributed.json`](../schemas/distributed.json) (`required` is `["ops"]` only) |

A binding MUST accept an omitted `frontier` on decode and treat it as empty. Rejecting the
absent form is a conformance failure; re-emitting it as `[]` is not.

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
| `collections/mergecell_algebra.json` | `SourceCell` merge algebra (`#relaycell`): KeepLatest/Sum/Max policies; per-op converged value + whether `⊕(old,op)==old` suppresses the cascade (idempotent/identity no-op = free dedup); `Cell ≡ SourceCell<KeepLatest>` |
| `collections/textcrdt_convergence.json` | Fugue/RGA character CRDT: concurrent same-point inserts, sticky tombstone, commutative/idempotent merge, GC |
| `collections/textcrdt_delta_sync.json` | `TextCrdt` delta sync (`#lztextsync`): `version_vector` (insert + tombstone ids), `delta_since` / `apply_delta`; bidirectional exchange convergence, whole-snapshot fork identity preservation, idempotent apply |
| `collections/stableid_alignment.json` | manufactured text identity: anchors / content hashes / word-LCS similarity alignment |
| `collections/workqueue_competing_delivery.json` | competing-consumer exclusive FIFO claims, delivery ownership, ack/nack, identity-preserving redelivery |
| `collections/workqueue_lease_deadletter.json` | strict visibility-timeout boundary, at-least-once requeue, max-delivery poison routing to DLQ |

## SlotMap materialization conformance

The `conformance/materialization/` directory pins the eager-vs-lazy
[materialization behavior](cell-model.md#materialization-a-caller-provided-recipe) (`#lzmatmode`) of a
[`SlotMap`](cell-model.md#keyed-cell-collections) — eager is a pre-mint loop over the
keyset; lazy is `get_or_insert_with` mint-on-access — proved in
[lazily-formal](formal-model.md)'s `Materialization` module. These are **compute**
fixtures: a binding reads the `spec` (each key's canonical value, and — for the
mixed fixture — its cell/slot entry kind), builds the keyed map under *both*
strategies, replays the `reads` sequence against the lazy build, and asserts
observational transparency plus the memory / entry-kind laws. Because
materialization is *not observable on the value axis*, there is no wire schema —
only the compute effects below.

| Fixture | Covers |
|---------|--------|
| `materialization/observational_transparency.json` | identical `observe` values under eager vs. lazy; eager materializes all keys; lazy materializes only read keys; default mode eager (`observe_canonical`, `eager_materializes_all`, `lazy_defers_slots`, `default_mode_eager`) |
| `materialization/deferral_not_deallocation.json` | lazy present set grows monotonically and is unchanged by re-reads; final lazy set is a subset of the eager set; no churn from allocation (`materialize_present_monotone`, `lazy_present_subset_eager`, `materialize_preserves_observe`) |
| `materialization/entry_kind_orthogonal_to_mode.json` | entry kind ⟂ mode: cell (input) entries are present under either mode; slot (derived) entries are deferred under lazy until read (`cell_entries_materialized_in_every_mode`, `slot_entries_deferred_under_lazy`) |

## Reactive graph disposal conformance

The `conformance/reactive-graph/` directory pins
[disposal and teardown scopes](reactive-graph.md#semantics) (`#lzspecedgeindex`) — the
explicit-lifetime half of the graph contract, whose scope law is proved as
`disposeScope_eq_disposeAll` in [lazily-formal](formal-model.md)'s `Reactive` module.
These are **compute** fixtures: a binding builds the graph by replaying each `step`'s
`op` against a fresh `Context` and asserts that step's `expect`. Disposal is not
observable on the wire — it changes what a context holds and what a publish reaches,
never a serialized frame — so there is no wire schema, only the compute effects below.

Every assertion is on **observable** state: dependent/dependency-set *sizes*, whether a
node is readable, a read's value or error, and which effects ran on a publish. Nothing
here fixes a promotion threshold, a hash strategy, or an index layout — those are
explicitly implementation-free per the
[implementation note](reactive-graph.md#semantics), and a binding that dedups edges by
linear scan at every degree conforms exactly as well as one that promotes to a hash
index.

Op vocabulary (all ids are fixture-local labels, never a binding's internal id):

| Op | Meaning |
|---|---|
| `cell {id, value}` | Create a source cell |
| `computed {id, reads[], offset, scope?}` | Create a derived formula whose value is `sum(reads) + offset`; owned by `scope` when named |
| `effect {id, reads[], scope?}` | Register an effect over `reads`; runs on creation and on each flush after a tracked invalidation |
| `read {id}` | Read a node — `expect.value`, or `expect.error` for a disposed one |
| `set_cell {id, value}` | Publish; `expect.observed_by` names the effects that ran, `expect.observed_count` their number |
| `dispose {id}` | Dispose one node, dispatching on its own kind |
| `fanout {id_prefix, reads[], count, read_each}` / `dispose_fanout {id_prefix, count}` | Create / dispose `count` sibling readers, for widths a literal step list would bloat |
| `churn {source, id_prefix, live_width, cycles, mode, read_each}` | Run `cycles` subscribe/unsubscribe cycles holding `live_width` subscribers live (`mode`: `dispose_then_create` or `scope_per_cycle`) |
| `begin_scope {scope}` / `end_scope {scope}` | Open / end a teardown scope |
| `disarm {scope}` | Cancel the scope's teardown — ending it then disposes nothing |
| `dispose_stale_handle {handle_of, handle_kind}` | Dispose through a handle whose id may have been recycled; a no-op unless the id still names a node of `handle_kind` |
| `subscribe {id, cell, callback?, on_notify?, on_notify_once?}` | Register a `Cell` observer labelled `id` on `cell`. `callback` names a *shared* callable, so two registrations naming the same `callback` subscribe the same function (default: the callback is unique to `id`). `on_notify` is a list of `subscribe`/`unsubscribe` ops the callback performs reentrantly when it runs; `on_notify_once` restricts them to the first invocation. A reentrant `subscribe` may use `id_prefix` instead of `id`, minting `<prefix>_0`, `<prefix>_1`, … per invocation |
| `unsubscribe {id, times?}` | Invoke the disposer returned by `subscribe {id}`, `times` times (default 1) — repeat calls exercise idempotency |

A fixture uses top-level `steps`, or `scenarios` plus `expected` when the claim is that
two differently-built runs agree (`expected.observationally_equal`).

| Fixture | Covers |
|---------|--------|
| `reactive-graph/dispose_detaches_edges_both_directions.json` | disposal detaches upstream *and* downstream edges; a publish to a former source does not reach the disposed node; the surviving source is unaffected |
| `reactive-graph/read_after_dispose_is_an_error.json` | reading a disposed formula, a disposed cell, or through a live reader that names one is an error — never a stale or default value; double-dispose is an idempotent no-op |
| `reactive-graph/recycled_id_inherits_nothing.json` | a node minted on a recycled id starts with an empty edge set in both directions — the owner-keyed-side-table aliasing hazard; a stale cross-kind handle disposes nothing |
| `reactive-graph/scope_teardown_equals_fold_of_disposals.json` | ending a scope is observationally equal to disposing each member individually (`disposeScope_eq_disposeAll`), including reverse-creation-order cleanup |
| `reactive-graph/scoping_bounds_teardown_not_visibility.json` | a scope's nodes read parent- and sibling-owned nodes freely in every direction; propagation crosses scope boundaries unchanged |
| `reactive-graph/disarm_disposes_nothing.json` | `disarm()` leaves node state untouched — the nodes stay readable, keep propagating, and stay individually disposable; ending the scope disposes nothing |
| `reactive-graph/cross_scope_teardown_hazard.json` | ending a scope tears down its nodes even when a node outside still reads them (**required** failure — a binding that keeps them alive is non-conforming); the mirror case is symmetric |
| `reactive-graph/churn_returns_to_baseline.json` | a subscribe/unsubscribe cycle that disposes what it creates leaves the source's dependent set at its starting size, under both individual disposal and one scope per cycle |

### Cell observer conformance (`#lzdartobservercow`)

The same directory pins
[observer semantics](reactive-graph.md#observer-semantics-cellsubscribe-lzdartobservercow) —
the hand-registered `Cell.subscribe` callbacks, which are a separate mechanism from the
tracked dependency edges above. Same compute-fixture shape, same op replay, two further
assertion keys:

| Assertion | Meaning |
|---|---|
| `observed_order` | The **exact sequence** of observer labels invoked by this step |
| `observed_counts` | Per-observer invocation counts for this step, where a shared callback runs more than once |

`observed_order` is deliberately a sequence and not a set. An unordered observer
collection satisfies a set-valued `observed_by` while firing in a fresh order on every
notification, which is precisely how the family's divergence went unnoticed — so an
observer fixture that asserts only `observed_by` is rejected by the structural guard.

**These fixtures fail against some bindings today, by design.** The observer contract was
unwritten until now and four bindings answered it differently; the fixtures encode the
family position, and the gaps are listed as
[known divergences](reactive-graph.md#observer-semantics-cellsubscribe-lzdartobservercow)
with migrations. A red result here is a binding bug, not a fixture bug.

| Fixture | Covers |
|---------|--------|
| `reactive-graph/observer_order_is_registration_order.json` | observers fire in registration order, stably across notifications; a removal closes the gap without reordering survivors; a re-registered callback appends rather than resuming its old position; the `==` guard still suppresses the notification entirely (**fails**: py, zig) |
| `reactive-graph/observer_duplicate_registrations_are_independent.json` | subscribing one callback twice yields two registrations that both fire and dispose independently — no dedup by identity or by equality (**fails**: py, zig) |
| `reactive-graph/observer_subscribe_during_notify_is_deferred.json` | an observer registered mid-notification first runs on the next one, including when observers registered earlier are still unvisited; a self-feeding subscriber terminates because the pass is bounded by the pre-callback count |
| `reactive-graph/observer_unsubscribe_during_notify_takes_effect_immediately.json` | an observer disposed mid-notification does not run in that pass even when unvisited; an already-visited observer's invocation stands; self-unsubscribe completes the call it is in; the tail observer still runs, catching a swap-remove under a live cursor (**fails**: dart, go) |
| `reactive-graph/observer_disposer_is_idempotent.json` | a disposer latches — repeat calls are silent no-ops that remove nothing else, and a spent disposer never reaches a later registration of an equal callable; cell teardown drops observers without invoking them, and a disposer outliving its cell is a no-op |

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
