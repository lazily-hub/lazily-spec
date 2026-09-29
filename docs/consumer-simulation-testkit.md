# Consumer simulation testkit (`#lzconsumerstestkit`)

The consumer simulation testkit runs one materialized generated history through
an in-memory deterministic simulation adapter and one or more explicitly
selected real adapters. It localizes divergence to the first action that
produced it. A final-state comparison is not sufficient.

Status: **MAY** as a family feature. A binding that exposes this testkit **MUST**
satisfy this contract and replay
`conformance/simulation/consumer_testkit.json`.

## Adapter identity and selection

Every adapter has a stable `adapter_id`, `kind`, `protocol_id`, `reducer_id`,
and non-empty narrow-port contract. Adapter ids are unique. The selected
simulation adapter exists and has kind `in_memory`.

A testkit run selects at least one non-simulated boundary before construction:

- `postgres` and `nats` adapters are selected by kind; or
- an `external_process` adapter is selected by both its stable adapter id and
  one of `cli`, `filesystem`, `local_socket`, or `editor_replica`.

Configured real adapters that were not selected, selections that do not resolve
to an adapter, duplicate selections, and a selection whose id resolves to the
wrong kind fail construction before any callback is invoked.

All adapters declare the same `protocol_id` and the same set of narrow ports.
Port equality includes stable port id, semantic kind, and determinism; adapter
ordering and port declaration ordering are not semantic.

## Reducer provenance

The in-memory, PostgreSQL, and NATS adapters invoke the same production
decision/reducer path and therefore declare the same non-empty
`production_reducer_id`. Their `reducer_id` identifies that path.

An external process may use an independently implemented reducer. It declares
its own stable `reducer_id`, shares the `protocol_id`, and leaves
`production_reducer_id` empty. A testkit **MUST NOT** claim that two languages
execute the same reducer merely because their observations agree.

## Narrow ports and stubs

Every port is explicitly `deterministic` or `nondeterministic`. The in-memory
adapter may stub only nondeterministic ports. A real adapter may not stub any
port. A deterministic port may never be stubbed.

The in-memory adapter exposes deterministic-world evidence and does not expose
a service id, probe, external-process port, or materialized-history callback.
That evidence **MUST** preserve stable world identity for the run and expose an
executed-step count plus immutable trace entries naming their action id and
kind. A binding with a full `SimWorld` uses it directly; a binding need not port
an unrelated scheduler merely to satisfy this testkit, and may instead expose a
narrow evidence interface with those three properties. A real adapter exposes a
stable service id, a readiness probe, reset/apply/observe callbacks, and its
exact materialized action history. A real adapter does not expose deterministic
world evidence. An external-process adapter also names its selected external
port.

## Construction and run boundary

Construction fails closed for invalid or duplicate ids, missing callbacks,
missing required adapters, reducer or protocol drift, a different narrow-port
contract, illegal stubs, and adapter-kind-specific fields on the wrong kind.
No probe, reset, apply, or observe callback runs before construction succeeds.

For a successful construction, `run`:

1. validates the generated scenario identity, seed, generator version, unique
   action ids, and exact scenario digest;
2. probes every selected real adapter and resets every adapter;
3. proves each real adapter's materialized history is initially empty;
4. applies the same cloned action to every adapter in stable adapter-id order;
5. proves the in-memory adapter advanced the same simulation world and that its
   new trace contains execution of the current action;
6. proves every real adapter materialized the exact generated-history prefix;
7. freezes and canonically encodes every complete observation map; and
8. compares every real observation with the in-memory observation before the
   next action executes.

A missing or additional observation key, a canonical value mismatch, an empty
observation map, a materialized-history mismatch, or a simulation bypass stops
the run at the first bad action. A value divergence reports at least the
one-based step, action id, non-baseline adapter id, and observation id.

## Result evidence

A successful result contains the scenario digest, adapter ids in stable sorted
order, identity evidence for every adapter, and one checkpoint per action. Each
checkpoint contains the one-based step, action id, and the canonical digest of
every adapter's observation map. Identity evidence includes adapter kind,
service id when real, external port when applicable, protocol id, reducer id,
and production reducer id when shared.

The canonical fixture supplies an independently readable counter history, real
adapter selections, an external-process selection, and three mutants. Binding
runners must construct their public testkit from that data; reimplementing the
fixture's comparisons solely in the test runner does not satisfy conformance.

This contract complements [Deterministic Simulation Oracles](deterministic-simulation-oracles.md):
that document defines checked deterministic steps and oracle authority, while
this one defines the boundary between a deterministic consumer and selected
real or external-process implementations.
