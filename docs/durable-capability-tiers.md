# Durable capability tiers (`#lzdurablefamily`)

Durable capability is published as one of five monotone tiers. A binding may
claim a tier only when it also satisfies every lower tier. The canonical
machine-readable registry is [`durable-tiers.json`](../durable-tiers.json).

| Tier | Contract | Required evidence |
|---|---|---|
| `core` | Reactive graph plus typed state and decision semantics. | The ordinary core conformance corpus. No network or durable-owner authority is implied. |
| `client` | Publish and observe the typed v1 NATS envelope through an injected compatible transport seam. | [`durable-client/envelope_v1.json`](../conformance/durable-client/envelope_v1.json) and cross-language interop. A client never authorizes an owner transition. |
| `durable_host` | Own durable transitions through an atomic database authority. | A mature transactional database client plus the complete durable-owner crash/replay, ordering, deduplication, receipt, fencing, and projection-fingerprint corpus. |
| `distributed_host` | Add leased broker ingress, outbox relay, bounded backpressure, drain, poison disposition, and recovery. | Every durable-host proof, a mature broker client, and real broker/database crash tests proving commit before acknowledgement. |
| `accelerated_host` | Add optional Valkey acceleration. | Every distributed-host proof plus bypass tests showing empty, stale, partitioned, or unavailable Valkey changes performance only. |

Tier names describe capability, not language parity. A Python, Kotlin,
JavaScript, Dart, Zig, Go, C++, C#, or GDScript package may ship `client`
without owning Postgres transactions or JetStream consumers. Conversely, a
native host claim requires mature database and broker libraries and the shared
failure corpus; type names or an in-memory mock are not evidence.

## Durable client envelope

[`schemas/durable-envelope.json`](../schemas/durable-envelope.json) fixes the
v1 JSON shape already used by the Rust JetStream adapter:

```text
protocol_version, message_id, schema_version, codec_version, payload
```

`payload` is an array of bytes. `schema_version` and `codec_version` are
independent positive 32-bit values. An unsupported protocol version fails
before payload decode. `message_id` is the stable transport identity and must
match the durable inbox identity when a host consumes the envelope.

The envelope deliberately carries no owner position, fence, broker sequence,
or authority flag. Owner ordering comes from the authoritative durable
position, never from NATS delivery order. The injected transport seam may be a
real NATS client, an FFI bridge, or a deterministic conformance transport, but
all implementations preserve the same envelope bytes and at-least-once
identity.

## Cross-language proof dimensions

Client interop replays the schema-validated envelope fixture across all five
portable proof dimensions. The shared obligations are:

- reject unknown envelope versions before decode;
- buffer advisory projection gaps and apply them in durable source-position
  order rather than broker arrival order;
- treat an exact identity/fingerprint repeat as a duplicate and changed content
  as a conflict;
- keep transport acknowledgements separate from durable effect receipts; and
- compare projection-fingerprint equality classes and completeness domains,
  not binding-specific digest bytes.

Projection and cache observations remain advisory at every tier. Only the
durable owner transaction may authorize a transition.
