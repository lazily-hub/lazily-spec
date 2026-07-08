# JSON Schemas

Schemas are provided as **JSON Schema (Draft 2020-12)**. Each implementation must validate
against these schemas. The JSON representation of the wire format is normative; future binary
codecs encode the same shapes.

| Schema | Layer |
|--------|-------|
| `defs.json` | Shared wire primitives (NodeId, NodeKey, NodeState, IpcValue, ShmBlobRef, WireStamp) |
| `snapshot.json` | IPC — Snapshot message (externally-tagged `{"Snapshot": …}` envelope) |
| `delta.json` | IPC — Delta message (externally-tagged `{"Delta": …}`, all 7 `DeltaOp` variants) |
| `ffi.json` | Cross-language FFI boundary |
| `signaling.json` | Signaling (WebSocket) |
| `distributed.json` | Distributed — CrdtSync message (`{"CrdtSync": …}`) + CRDT/cell-model types |
| `receipts.json` | Causal receipts (`{"CausalReceipts": …}`) + terminal outcome projection |
| `message-passing.json` | Command / RPC message plane (`CommandSubmit` / `CommandCancel` / `CommandEvents` / `CommandProjection`) |
| `statechart.json` | Compute (Harel/SCXML chart form — not a wire message) |

The IPC schemas describe the **normative externally-tagged envelope** that
every binding serializes (the single-key `{"Snapshot": …}` / `{"Delta": …}` /
`{"CrdtSync": …}` form), with `node` addressing and value bytes as JSON arrays
of `u8` (not base64). Shared wire primitives live in `defs.json` and are
referenced via absolute `$ref` so the primitive definitions never copy-drift.
Every conformance fixture's `wire` field validates against its schema — enforced
by `make test-schemas` (see `tests/test_schema_conformance.py`).

## `defs.json`

```json
{{#include ../schemas/defs.json}}
```

## `snapshot.json`

```json
{{#include ../schemas/snapshot.json}}
```

## `delta.json`

```json
{{#include ../schemas/delta.json}}
```

## `ffi.json`

```json
{{#include ../schemas/ffi.json}}
```

## `signaling.json`

```json
{{#include ../schemas/signaling.json}}
```

## `distributed.json`

```json
{{#include ../schemas/distributed.json}}
```

## `receipts.json`

```json
{{#include ../schemas/receipts.json}}
```

## `message-passing.json`

```json
{{#include ../schemas/message-passing.json}}
```

## `statechart.json`

This is a **compute** schema, not a wire message. It normatively defines the
declarative Harel/SCXML chart form used by conformance fixtures and
cross-language chart definitions. A chart is never serialized as a distinct
wire kind; only its converged active configuration crosses IPC/FFI as an
ordinary cell `Payload`. See [State Charts](state-charts.md).

```json
{{#include ../schemas/statechart.json}}
```
