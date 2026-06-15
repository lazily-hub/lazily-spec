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
