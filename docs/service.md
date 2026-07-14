# Embedded-service plane (`#lzservice`)

Phase 7 of the realtime + distributed primitives plan — the story for "an
instance is also a host of services." Composes everything above (`#lzmemb`
membership, `#lzcoord` leases, `#lzresilience` probes). Each primitive is a pure
compute **core** (an aggregation / keyed map over plain state) split from a
reactive **cell** projecting the composed view.

## `HealthCell` — composed liveness probe

Aggregates named dependency probes into a reactive health for `/health`. Each
probe reports `up`/`down` and whether it is `critical`:

- **Unhealthy** — any *critical* probe is down.
- **Degraded** — no critical probe is down but some non-critical one is.
- **Healthy** — every probe is up.

`set(name, up, critical)` updates a probe; `health()` is the aggregate. The
worst component dominates.

## `ReadinessCell` — composed readiness probe

Aggregates readiness conditions (deps ready + leader known + lease valid) into a
reactive readiness for `/ready`. `set(name, ready)` sets a condition; `ready()`
is `true` iff **every** condition is true.

## `DiscoveryCell` — service → endpoint

A reactive map `service → endpoint` fed by service registration and
`MembershipCell`. Each entry records its owning peer, so a peer's departure
(`evict(peer)`) removes its endpoints — "call service X" resolves to the current
owner.

- `register(service, endpoint, peer)` / `deregister(service)` / `evict(peer)`.
- `resolve(service)` → endpoint; `discovery()` → the live map.

## `ServiceRegistry` — durable registration table

A durable registration table (the `DurableOutbox` pattern) plus a reactive
projection. Registrations append to an ordered **log**; the projection is the
left-fold of that log, so **replaying the log reconstructs the projection** —
the registry survives a restart.

- `register(service, endpoint)` / `deregister(service)` append to the log and
  update the projection; `projection()` → the live map; `replay()` rebuilds the
  projection from the log (idempotent).

## Conformance

| Fixture | Model | Checks |
|---------|-------|--------|
| `health.json` | `HealthCell` | Healthy → Degraded (non-critical down) → Unhealthy (critical down) → recover; health invalidation |
| `readiness.json` | `ReadinessCell` | ready only when all conditions hold; ready invalidation |
| `discovery.json` | `DiscoveryCell` | register/resolve; membership `evict` removes a peer's endpoints; deregister; map invalidation |
| `service_registry.json` | `ServiceRegistry` | register/deregister project correctly; `replay` reconstructs the projection unchanged (durability) |

## Formal model

`lazily-formal/LazilyFormal/Service.lean`: health is Unhealthy iff a critical
probe is down (`health_unhealthy_iff`) and Healthy when all probes are up
(`health_all_up_healthy`); readiness is ready iff all conditions hold
(`ready_iff_all`); the registry projection is the fold of its log so `replay`
reconstructs it (`registry_replay_reconstructs`) and a fresh registration
resolves (`register_resolves`).
