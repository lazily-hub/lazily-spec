# lazily-spec

Language-agnostic wire protocol specification for the **lazily** reactive signals family.

**lazily** is one reactive model — sources, computeds, effects, keyed collections,
CRDTs, and a distributed sync plane — implemented natively in nine languages. This repo
is the hub: it defines the canonical message schemas, the cross-language feature matrix,
and the conformance corpus. Each binding declares the subset it actually replays; the
coverage and Core-profile gates reject claims that outrun that executable evidence.

Start here: the [wire protocol](protocol.md), the [cell model](cell-model.md), the
[Core support contract](docs/core-support.md), the **Feature Set** matrix below, and
the **Conformance Fixtures** each binding declares and must pass.
Concurrency-bearing APIs use the machine-readable
[`concurrency-scopes.json`](concurrency-scopes.json) taxonomy documented in
[Concurrency Scopes](docs/concurrency-scopes.md).

The repository, including its first-party specifications and conformance
fixtures, is licensed under [Apache License 2.0](LICENSE). Fixture reuse and
generated/imported provenance requirements are recorded in
[Fixture provenance and licensing](docs/fixture-provenance.md).

## Implementations

Nine native language bindings plus a React adapter. Their shipped and partial surfaces,
declared fixture closures, and execution flavors differ. Per-binding evidence is tracked
in the **Feature Set** matrix, **Binding Conformance**, and the generated Core support
contract; presence in this repository family alone does not imply Core qualification.

| Repo | Language |
|------|----------|
| [lazily-rs](https://github.com/lazily-hub/lazily-rs) | Rust — the reference implementation |
| [lazily-py](https://github.com/lazily-hub/lazily-py) | Python |
| [lazily-go](https://github.com/lazily-hub/lazily-go) | Go |
| [lazily-kt](https://github.com/lazily-hub/lazily-kt) | Kotlin / JVM |
| [lazily-js](https://github.com/lazily-hub/lazily-js) | JavaScript / TypeScript |
| [lazily-cs](https://github.com/lazily-hub/lazily-cs) | C# / .NET |
| [lazily-cpp](https://github.com/lazily-hub/lazily-cpp) | C++ |
| [lazily-zig](https://github.com/lazily-hub/lazily-zig) | Zig |
| [lazily-dart](https://github.com/lazily-hub/lazily-dart) | Dart / Flutter |
| [lazily-react](https://github.com/lazily-hub/lazily-react) | React / Preact bindings layered over `lazily-js` — an adapter, not a separate language binding |

**Formal model:** [lazily-formal](https://github.com/lazily-hub/lazily-formal) — the
Lean 4 model of the shared primitive types, the flat FSM kernel, and the full Harel/SCXML
state chart. It is the neutral formal home every binding depends on equally, and the
executable reference behind the state-chart conformance fixtures (see **Formal Model**).

## Feature Set

Coverage by feature family across every binding (`lazily-rs`, `lazily-py`, `lazily-kt`, `lazily-js`, `lazily-dart`,
`lazily-zig`, `lazily-go`, `lazily-cpp`, `lazily-cs`). Legend: ✅ shipped · `~` partial · `—` absent · `⊘` not applicable.
This table is generated from [`coverage.json`](coverage.json) — the canonical
matrix with per-cell notes and platform carve-outs lives in
[Cross-Language Coverage](docs/coverage.md). Edit `coverage.json` and run
`make coverage-sync` to update it in one shot; `make coverage-check` guards drift.

<!-- coverage-table:start -->
#### Summary — family × language

| Family | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Reactive graph | ✅ | ~ | ~ | ~ | ✅ | ✅ | ✅ | ✅ | ✅ | ~ |
| Materialization | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Family sync | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Statecharts | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Keyed collections | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| Reactive queue | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Broadcast topic | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Work queue | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| CRDT data types | ✅ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ✅ | — |
| Lossless tree | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Egress | ✅ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ |
| Ingress | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Wire codec | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | ✅ | — |
| Transport & FFI | ✅ | ~ | ~ | ~ | ~ | ✅ | ✅ | ~ | ✅ | — |
| Message passing | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| Reliable sync | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | — |
| Durable owner | ✅ | — | — | — | — | — | — | — | — | — |
| Durable capability tiers | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ |
| Distributed plane | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Causal receipts | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Security boundary | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Membership | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Coordination | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Presence | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Temporal | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Rate shaping | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Windowing | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Resilience | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Portable stdlib | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Service plane | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Instrumentation | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

**Roll-up rule:** a family cell is `✅` only when *every required* row in that family is `✅`; `~` when the family is mixed (some shipped or partial); `—` when no required row is shipped or partial; `⊘` only when every required row in the family is not applicable. Rows the spec marks **MAY** (`optional`) are excluded from the roll-up — declining an optional feature is not a gap.

A family cell summarises 83 feature rows. For row-level marks, per-cell notes, and platform carve-outs see [the canonical coverage matrix in `lazily-spec`](https://github.com/lazily-hub/lazily-spec/blob/main/docs/coverage.md).
<!-- coverage-table:end -->

CRDT convergence and the wire protocol are pinned by the shared conformance fixtures
and JSON Schemas in `lazily-spec` and the Lean models in `lazily-formal`.

## Binding Conformance

The bindings the columns above refer to are listed, with links, under
**Implementations** near the top of this file.

Every binding MUST implement the layers in the [Binding Conformance Matrix](protocol.md#binding-conformance-matrix).
The **distributed CRDT plane (`CrdtSync`)** and the full keyed cell collections layer
(`SourceMap`, `SourceTree`, keyed reconciliation) are unconditional — implementable on any
runtime that speaks the wire. The **C-ABI FFI boundary** is required by default, with a
narrow platform carve-out: a binding whose runtime structurally cannot host a native
in-process C ABI (browser/Worker JS, sandboxed runtimes) declares `ffi = none`, still
exposes the full state plane over IPC/WebSocket/WebRTC, and must not advertise itself as
embeddable. The **thread-safe** and **async** reactive contexts are required where the
platform supports them — a platform that structurally lacks threading or suspendable
async declares `thread_safe = none` / `async = none` (see
[Concurrency layers are required](protocol.md#concurrency-layers-are-required)). The
**shared-memory payload path** (`ShmBlobArena`) is required where the platform supports
it; a binding that cannot host a shared-memory arena declares `shared_memory = none` and
MUST fall back to **I/O channels accessing the memory** — large payloads are carried
`Inline` over IPC/WebSocket/WebRTC instead of as `ShmBlobRef` descriptors (see
[Shared-memory payload path is required](protocol.md#shared-memory-payload-path-is-required)).
Any omitted `MUST` row MUST be advertised rather than fail silently.

Python, Dart, Rust, and Go vendor selected fixture subsets so their suites can
run without a sibling checkout. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
fixture-mirror maintenance and verification commands.

## Protocol Layers

| Layer | Spec | Schema |
|-------|------|--------|
| IPC (Snapshot + Delta) | [protocol.md](protocol.md) § IPC | [schemas/snapshot.json](schemas/snapshot.json), [schemas/delta.json](schemas/delta.json) |
| Shared wire primitives | [protocol.md](protocol.md) § Shared Types | [schemas/defs.json](schemas/defs.json) |
| Cross-language FFI | [protocol.md](protocol.md) § FFI | [schemas/ffi.json](schemas/ffi.json) |
| Signaling (WebSocket) | [protocol.md](protocol.md) § Signaling | [schemas/signaling.json](schemas/signaling.json) |
| Distributed (CRDT) | [protocol.md](protocol.md) § Distributed | [schemas/distributed.json](schemas/distributed.json) |
| Causal receipts | [protocol.md](protocol.md) § Causal Receipts | [schemas/receipts.json](schemas/receipts.json) |
| Capability negotiation | [protocol.md](protocol.md) § Capability Negotiation | inline |

## Wire Format

All messages use **JSON** with `serde`-compatible tagging (`"type"` discriminant). Future binary codecs (bincode, postcard, protobuf) encode the same schemas — the JSON representation is normative.

## Schema Format

Schemas are provided as **JSON Schema (Draft 2020-12)**. Each implementation must validate against these schemas.

## Formal Model

`formal/lean` contains a small Lean 4 Lake package for the IPC Snapshot/Delta
state machine. It proves the epoch sequencing, fail-closed resync,
PartialEq/memo suppression, batch coalescing, and eager Signal `slot_value`
invariants that all bindings share.

The language-agnostic formal model — shared primitive types, the flat FSM
kernel, and the full Harel/SCXML state chart — lives in its own repo,
[`lazily-formal`](https://github.com/lazily-hub/lazily-formal), as the neutral
formal home every binding depends on equally. It is the executable reference
behind the state-chart conformance fixtures (see below).

Local verification instructions are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Relationship to lazily-rs SPEC.md

This repo extracts the wire-protocol and cross-language compatibility sections from `lazily-rs/SPEC.md` into a standalone reference. Rust-specific internals (the concrete `Context`/`ThreadSafeContext` lock strategy, benchmarks) remain in the Rust crate; the *existence* of the thread-safe and async context surfaces is cross-language and required where the platform supports it.

## Conformance Fixtures

The `conformance/` directory contains canonical test fixtures that all IPC-capable bindings must validate against. Each binding's CI should deserialize the `wire` field, run the assertions, and re-serialize to confirm round-trip fidelity.

**Fixture schema:**

```json
{
  "description": "Human-readable summary",
  "protocol_version": 1,
  "kind": "Snapshot" | "Delta" | "Receipt",
  "assertions": { "…language-agnostic field checks…" },
  "wire": { "…canonical protocol JSON…" }
}
```

**Core qualification evidence:** Candidate bindings declare intentional runtime
skips, a report command, and fixtureless proof commands in
`scripts/core-conformance.json`. The aggregate check executes each report command
without a shell from its binding root; the command must create
`LAZILY_CORE_REPORT_PATH`. Validate the closed profile with:

```bash
make core-evidence-check \
  CORE_BINDINGS_ROOT=/path/to/binding-checkouts \
  CORE_EVIDENCE_REPORTS=/path/to/fresh/reports
```

The verifier passes its per-command budget to every report and proof command as
`LAZILY_CORE_COMMAND_TIMEOUT_MS`, so a runner can bound its own children and
fail with a precise diagnostic before the verifier's blind timeout fires. A
report command that exceeds `CORE_EVIDENCE_TIMEOUT_MS` fails with the exact
timeout, after its old report and binding evidence directory have already been
removed. The Dart runner probes each distinct `dart` on `PATH` with a bounded
`dart --version` and skips one that never exits or prints no SDK banner (the AUR
flutter wrapper `exec`s itself forever when its unionfs mount fails);
`DART=/absolute/path/to/dart` pins the SDK instead.

Generated outputs must also be fresh: the verifier stamps a marker file next to
the outputs immediately before spawning, and rejects (and deletes) a report,
binding evidence file, or proof artifact whose mtime predates it, so a command
that restores a preserved artifact (`cp -p`, a cache) instead of producing one
fails closed. Each `OK` line prints the report's date and the command's start
time.

The verifier executes every fixtureless proof command without a shell from the
binding root. It exposes `LAZILY_CORE_EVIDENCE_PATH` and requires the command to
recreate that regular file beneath the report directory. Assertion evidence must
be generated beneath the binding-id report subdirectory (or be a canonical
`audits/` artifact) and include a resolving `#/...` pointer; missing, escaping,
symlinked, empty, or explicitly `untested` evidence is rejected. The report
directory for that binding is cleared before its report command runs, so run-local
assertion evidence cannot be inherited from an older qualification. Each pointer
must resolve to a structured record whose status is `mutation-killed` (an active
per-route negative control) or `consumed-with-family-negative-controls` (exact
route consumption plus active expectation-family negative controls); successful
replay by itself is not discriminability evidence.

Runtime skips close exactly in both directions. `scenario: "*"` means every
scenario; an optional `execution_flavor` narrows the skip to the canonical
`single_threaded`, `thread_safe`, or `async` profile flavor. Fixture reports use
`status: "passed"`, `"partial"`, or `"skipped"`; skipped fixtures cannot claim
consumed assertion blocks, while partial fixtures may name only canonical blocks
that the run actually consumed. Generated fixtureless evidence must also stay
beneath the binding-id subdirectory. `--require-all` rejects every missing
declaration or report.

**Current fixtures:**

| Fixture | Kind | Description |
|---------|------|-------------|
| `snapshot_minimal.json` | Snapshot | One payload node, no edges |
| `snapshot_multi_node.json` | Snapshot | Multiple nodes and edges |
| `snapshot_shared_blob.json` | Snapshot | SharedBlob node state |
| `delta_sequential.json` | Delta | All 7 DeltaOp variants, sequential |
| `delta_non_sequential.json` | Delta | Non-sequential delta with gap |
| `delta_shared_blob.json` | Delta | CellSet/SlotValue with SharedBlob |
| `receipts/causal_receipts.json` | Receipt | Generic causal receipt projection with terminal `applied` / `rejected` outcomes |

**Adding a new binding:** Copy the fixture-loading pattern from `lazily-rs/tests/conformance.rs`. Each test should (1) load the fixture, (2) parse the `wire` field into the binding's native `IpcMessage` type, (3) assert the `assertions` fields, (4) re-serialize and compare.

## Keyed Cell Collections Conformance

The `conformance/collections/` directory contains canonical fixtures for the [keyed cell collections](cell-model.md#keyed-cell-collections) layer, which is **required of every binding**. Unlike IPC fixtures these are **compute** — a binding loads the `initial` state, replays each `step`'s `op`, and asserts the `expected` observable effects (resulting `order`, `values`, `membership`, and which reader classes — `value` / `membership` / `order` — invalidate). The reconciliation fixture is declarative: diff `prior` → `target` and assert the emitted minimal op set.

| Fixture | Covers |
|---------|--------|
| `collections/cellmap_independence.json` | value / set-membership / order reactivity independence (write, insert, remove, pure reorder) |
| `collections/cellmap_atomic_move.json` | atomic ordered move keeps handle/dependents, bumps order once, leaves value readers untouched |
| `collections/keyed_reconciliation_lis.json` | LIS move-minimized reconciliation; stable entries not invalidated by sibling reorder |
| `collections/semtree_incremental.json` | memoized semantic tree: ancestor-chain-only recompute, sibling isolation, memo equality guard |
| `collections/seqcrdt_convergence.json` | move-aware sequence CRDT: single-LWW move, concurrent-move/value-edit independence, tombstone convergence |
| `collections/textcrdt_convergence.json` | Fugue/RGA character CRDT: concurrent same-point inserts, sticky tombstone, commutative/idempotent merge, GC |
| `collections/textcrdt_delta_sync.json` | `TextCrdt` delta sync (`#lztextsync`): `version_vector` / `delta_since` / `apply_delta`; bidirectional exchange convergence, whole-snapshot fork identity preservation, idempotent apply |
| `collections/stableid_alignment.json` | manufactured text identity: anchors / content hashes / word-LCS similarity alignment |
| `collections/workqueue_competing_delivery.json` | exclusive FIFO claims, delivery ownership, ack/nack, identity-preserving redelivery |
| `collections/workqueue_lease_deadletter.json` | visibility timeout, at-least-once requeue, max-delivery poison routing to DLQ |

## State Chart Conformance

The `conformance/statechart/` directory contains canonical Harel/SCXML state-chart fixtures (see [State Charts](docs/state-charts.md)). The declarative chart form is normatively defined by [`schemas/statechart.json`](schemas/statechart.json). Unlike IPC fixtures, these are **compute** — a chart is never serialized as a distinct wire kind; only its converged active-state value crosses IPC as an ordinary cell `Payload`. The fixtures fix cross-language *behavior*: each binding loads the declarative `chart`, replays `steps`, and asserts `accepted`, `active`, `matches`, and (when present) `actions` identically.

| Fixture | Covers |
|---------|--------|
| `statechart/flat_cycle.json` | flat transitions, rejection, cycle |
| `statechart/hierarchical_player.json` | nesting, walk-up transition resolution, LCA across levels, `matches()` |
| `statechart/guarded_door.json` | named guards, fail-closed rejection, guard pass |
| `statechart/parallel_regions.json` | orthogonal (AND) regions, per-region transitions, multi-leaf configuration |
| `statechart/history_shallow.json` | shallow history: resume last direct child; first-entry default |
| `statechart/history_deep.json` | deep history: resume full nested leaf configuration |
| `statechart/entry_exit_actions.json` | entry/exit/transition action ordering across LCA boundaries |
| `statechart/malformed_rejected.json` | authoritative `kind`, strict field types, and declared-state reference closure |

## Durable Owner Conformance

The `conformance/durable-owner/` corpus defines the backend-neutral atomic owner
boundary for event history or snapshot state: monotone positions, exact fencing,
versioned bytes, stable inbox/outbox/receipt identities, crash recovery, and
source-bound projection fingerprints. See the
[Durable Owner Contract](docs/durable-owner.md) and
[`schemas/durable-owner.json`](schemas/durable-owner.json).

## Reliable Sync Conformance

The `conformance/reliable-sync/` directory contains canonical fixtures for the
[Reliable Sync protocol](protocol.md#reliable-sync-lzsync) (`#lzsync`) — the delivery-reliability
layer over the `Snapshot`/`Delta`/`CrdtSync` planes. These are **compute** fixtures: a binding
replays each scenario against its `ResyncCoordinator` / `DurableOutbox` / liveness implementation and
asserts the `expect` fields identically. Fixtures that carry a top-level `wire` frame also pin the
serde round-trip of the two new control frames (`ResyncRequest`, `OutboxAck`, schema
[`schemas/reliable-sync.json`](schemas/reliable-sync.json)) and the multi-epoch `Delta`. The two
control frames MUST round-trip through both `json` and `msgpack`, the same discipline the three
`IpcMessage` variants hold.

| Fixture | Model | Covers |
|---------|-------|--------|
| `reliable-sync/multi_epoch_delta.json` | MultiEpochDelta | a `Delta` with `epoch > base_epoch + 1` applies equal to the unit-delta fold; atomic `last_epoch` advance; gap rule unchanged under span |
| `reliable-sync/resync_gap_converge.json` | ResyncCoordinator | drop a delta suffix → `RequestSnapshot` → apply `Snapshot` → same graph as the no-drop receiver; single request per gap |
| `reliable-sync/idempotent_redelivery.json` | ResyncCoordinator | a re-delivered (`base_epoch < last_epoch`) delta is `Ignore`d; net state unchanged (at-least-once ⇒ exactly-once effect, receiver half) |
| `reliable-sync/outbox_replay_after_crash.json` | DurableOutbox | append-before-send, replay-from-cursor after a simulated crash, `ack_through` retention, send-failure retain; exactly-once effect under replay |
| `reliable-sync/outbox_journal_decode.json` | FileOutboxStore | a complete unknown interior opcode is rejected; one torn trailing record is forgiven without losing earlier complete records |
| `reliable-sync/liveness_orset_lww.json` | LivenessCells | OR-set open-set membership + LWW `alive`/lease; whole-editor-death cascade; derived live-doc aggregate converges under retry/re-delivery; per-doc isolation |

The correctness backstop is `lazily-formal` `ReliableSync.lean`; the fixtures are the cross-language
(rs/js/kt) drift catch pinned to that model.

## Versioning

Protocol versioning follows the IPC capability negotiation: each session exchanges `{ protocol_id, protocol_major_version, codec }` before any graph state flows. A major version bump is a breaking change; minor additions are additive.

The **Reliable Sync** layer (`#lzsync`) is an **additive, non-breaking** extension: it introduces two
new externally-tagged control frames (`ResyncRequest`, `OutboxAck`) and relaxes the `Delta` epoch
invariant to `epoch >= base_epoch + 1` (the prior `== base_epoch + 1` is the span-1 special case, so
every existing `Delta` frame stays valid). No `protocol_major_version` bump; a peer that does not
advertise a reliable-sync feature flag simply never receives the new control frames.
