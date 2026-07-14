# Presence + ephemeral plane (`#lzpresence`)

Phase 4 of the realtime + distributed primitives plan. The CRDT plane is
**durable**; collaborative / realtime apps also need an **ephemeral** plane that
does *not* persist — live cursors, typing indicators, presence. This is the most
user-visible realtime win; agent-doc itself wants `AwarenessCell` for live
cursors.

Each primitive is a pure compute **core** (a keyed map / single value + TTL over
the logical clock — `BytesPayload`) split from a reactive **cell** projecting the
live view onto a `Cell` (invalidates only on a live-view change).

## Ephemeral vs durable plane (structural)

The ephemeral plane is **distinct** from the durable plane: the CRDT plane writes
through the outbox / spill store, the ephemeral plane must **not**. This is
encoded as a marker so the durable outbox can statically reject ephemeral ops:

- `Ephemeral` — a value on the ephemeral plane; MUST NOT be persisted.
- `Durable` — a value that may be written to the outbox.

The presence / awareness / ephemeral values are `Ephemeral`; a durable sink is
generic over `Durable`, so handing it an ephemeral value fails to compile
(bindings without static generics enforce it with a runtime guard / lint).

## `PresenceCell<K, V>` — per-peer presence

Per-peer ephemeral state keyed by `PeerId` (online / device / capabilities),
kept alive by heartbeats and **auto-evicted** on membership loss (`Dead`/`Left`
from `#lzmemb`) or TTL lapse. Reuses the TTL discipline of `ExpiryPolicy` (lifted
in Phase 0).

- `heartbeat(peer, value, now, ttl)` — set/refresh the peer's presence, expiring
  at `now + ttl`.
- `evict(peer)` — drop a peer immediately (membership `Dead`/`Left`).
- `tick(now)` — evict entries whose TTL has lapsed (`now ≥ expiry`).
- `present(now)` — the live peer → value map (the reactive view).

## `AwarenessCell<T>` — typed ephemeral broadcast

Typed ephemeral broadcast (cursors, selections, typing indicators) with a TTL —
different shape from a CRDT because values **do not merge**: it is
**last-writer-per-peer**.

- `set(peer, value, now, ttl)` — overwrite the peer's awareness value
  (last-writer wins, no merge), expiring at `now + ttl`.
- `tick(now)` — evict expired entries.
- `get(peer, now)` — the peer's live value (or none); `present(now)` — the live
  map.

## `EphemeralCell<T>` — single value with auto-expiry

A single-value cell with auto-expiry — "the last value seen in window N".

- `set(value, now, ttl)` — set the value, expiring at `now + ttl`.
- `tick(now)` — clear the value when `now ≥ expiry`.
- `value(now)` — the live value, or none once expired.

## Conformance

`conformance/presence/` replays each primitive; every step asserts the live view
and its reader invalidation.

| Fixture | Model | Checks |
|---------|-------|--------|
| `presence.json` | `PresenceCell` | heartbeat sets/refreshes; membership `evict` drops; TTL `tick` evicts; present-map invalidation |
| `awareness.json` | `AwarenessCell` | last-writer-per-peer overwrite; TTL eviction; present-map invalidation |
| `ephemeral.json` | `EphemeralCell` | set; TTL `tick` clears the value; overwrite before expiry; value invalidation |

## Formal model

`lazily-formal/LazilyFormal/Presence.lean`: an entry is present iff it is not
expired (`present_iff_live`), awareness is last-writer-per-peer
(`awareness_last_writer`), ephemeral value clears exactly at expiry
(`ephemeral_clears_at_expiry`), and the **ephemeral plane never writes to the
durable outbox** — the durable projection of any ephemeral op sequence is empty
(`ephemeral_never_durable`).
