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
