# Protobuf graph-boundary interoperability

Protobuf is an optional, capability-negotiated encoding of Lazily's graph
boundary algebra. It does not own a second graph runtime. The canonical
semantics remain in this specification and its executable conformance traces;
canonical JSON remains the diagnostic and fixture representation, and msgpack
remains part of the existing interop matrix.

The canonical schema is
[`proto/lazily/graph_boundary/v1/graph_boundary.proto`](../proto/lazily/graph_boundary/v1/graph_boundary.proto).
Its reviewed semantic classification is
[`proto/field-ledger.json`](../proto/field-ledger.json).

Ordinary text mutation uses `GraphInput.cell_text_splice`, bounded to one stable
cell with a local UTF-8 offset and expected revision. `bootstrap_snapshot` is a
different oneof variant and is legal only for bootstrap, explicit recovery, or
checkpoint compaction. A cache or native-library reload is therefore never
promoted into operator mutation authority.

Peers advertise the `protobuf` codec, the `protobuf-graph-boundary-v1` feature,
and a compatible protocol range before exchanging these envelopes. The feature
is disabled unless both sides advertise it. Unsupported versions, unknown
semantic enum values, stale generations or epochs, sequence gaps, and invalid
snapshot purposes fail closed at admission. Duplicate sequences are idempotent.

Logical hashes are computed from the existing canonical logical representation,
never raw Protobuf bytes. Protobuf map ordering, unknown-field preservation, and
implementation-specific serialization make byte equality unsuitable as logical
identity.

The six canonical traces in
[`conformance/protobuf/graph_boundary_traces.json`](../conformance/protobuf/graph_boundary_traces.json)
pin partial typing, cross-cell bounds, cache fencing, native reload behavior,
duplicate/reordered delivery, and the snapshot/mutation variant boundary.
The binding parity ledger in `proto/field-ledger.json` records Rust, Kotlin, and
TypeScript as the reproducible-generation pilot. Python, Go, C++, Dart, Zig, and
C# remain capability-gated known-uncovered findings until their native
generators and reducers replay the same logical traces.
