# JSON Schemas

Schemas are provided as **JSON Schema (Draft 2020-12)**. Each implementation must validate
against these schemas. The JSON representation of the wire format is normative; future binary
codecs encode the same shapes.

| Schema | Layer |
|--------|-------|
| `snapshot.json` | IPC — Snapshot message |
| `delta.json` | IPC — Delta message (all 7 `DeltaOp` variants) |
| `ffi.json` | Cross-language FFI boundary |
| `signaling.json` | Signaling (WebSocket) |
| `distributed.json` | Distributed (CRDT) |
| `statechart.json` | Compute (Harel/SCXML chart form — not a wire message) |

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

## `statechart.json`

This is a **compute** schema, not a wire message. It normatively defines the
declarative Harel/SCXML chart form used by conformance fixtures and
cross-language chart definitions. A chart is never serialized as a distinct
wire kind; only its converged active configuration crosses IPC/FFI as an
ordinary cell `Payload`. See [State Charts](state-charts.md).

```json
{{#include ../schemas/statechart.json}}
```
