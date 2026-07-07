# Lossless Tree CRDT

`LosslessTreeCrdt` is a single rooted **concrete-syntax tree** whose leaves own
every rendered byte, so the tree itself is the lossless wire authority — no
separate flat text CRDT floor is required for capable sessions. The defining
invariant is losslessness:

```text
render(tree) == source_text
```

for valid, invalid, and unknown source alike. This chapter specifies the **M1
syntax-agnostic core**: the tree state model, node/op id formats, the leaf and
element node variants, the dotted non-contiguous version frontier, the op
vocabulary, the byte-offset policy, and the compute-fixture contract every binding
replays. The Lean model of the render algebra, convergence, and frontier soundness
lives in `lazily-formal` (`LazilyFormal.LosslessTree`,
`LazilyFormal.LosslessTreeSync`).

> **M1 scope.** Create / tombstone / intra-parent reorder / leaf-edit / split-leaf
> / merge-adjacent-leaves, plus op-based delta sync, plus the op-delta wire schema
> (see [Wire schemas](#wire-schemas)). Deferred to later milestones: cross-parent
> move (single-parent + acyclicity enforcement), metadata/kind mutation, subtree
> replace, snapshot/GC and its wire schema, and full `SessionHandshake` capability
> negotiation (the capability *name* is reserved below). The Kotlin and JS bindings
> land in M2. In the create-only + intra-parent-reorder algebra, single-parent and
> acyclicity hold by construction.

## Tree state model

The document is one rooted tree. Every node has a stable identity and belongs to
exactly one parent's ordered child list.

- **`DocumentRoot`** — the sentinel root element (`TreeNodeId` `{counter: 0,
  peer: 0}`).
- **`ElementNode`** — an internal semantic node with a `kind` and an ordered list
  of children. Owns *structure only*, never text.
- **`Leaf`** — owns one exact source span, classified by a `LeafKind`:
  - `Token` — a syntax delimiter or marker;
  - `Trivia` — whitespace, blank lines, indentation, comments, separators;
  - `Raw` — valid text the adapter deliberately keeps opaque;
  - `Error` — invalid or ambiguous text that must still round-trip exactly.

`render` is a depth-first concatenation of the live leaves' text in child order.
Because every rendered byte belongs to exactly one live leaf and elements own no
text, unknown or invalid spans round-trip exactly as `Raw`/`Error` leaves rather
than being discarded — the requirement that keeps a semantic AST from being
mistaken for a lossless tree.

## Identity and clock

- **`TreeOpId` `{counter, peer}`** — a dotted operation id: a Lamport counter
  tiebroken by peer, totally ordered by `(counter, peer)`. The counter advances
  past every observed op, so a causally-later write wins last-writer-wins and
  concurrent ops tiebreak deterministically by peer. (No HLC is needed; tree
  anti-entropy is op-based.)
- **`TreeNodeId`** — a node's identity *is* the id of the op that created it, so a
  node keeps its id through reorder, edit, and (future) move.
- **`SortKey` `{frac, peer}`** — a fractional-index child position: orderable
  bytes tiebroken by the minting peer, so concurrent inserts into the same gap get
  a deterministic total order. Positions travel *inside* create/reorder ops, so
  both replicas store byte-identical keys.

## Operation vocabulary

Every mutation is one op carrying everything a remote replica needs to converge
deterministically (positions and seed text travel inside the op):

| Op | Effect |
|----|--------|
| `CreateNode {id, parent, sort, seed}` | materialize an element shell or a text leaf seeded from exact text |
| `Tombstone {node}` | tombstone a node (sticky; smaller op id wins concurrently) |
| `Reorder {node, sort}` | LWW position reassignment within the parent (identity + payload preserved) |
| `LeafEdit {node, prev, ops}` | apply an embedded text-CRDT delta to one leaf |
| `SplitLeaf {node, new, sort, at_char, prev}` | split a leaf at a char boundary into two adjacent leaves of the same kind |
| `MergeLeaves {left, right, prev_left, prev_right}` | merge two adjacent leaf siblings; total text unchanged |

Split and merge reseed a leaf's text destructively, so per-leaf text ops form a
**causal chain**: each `LeafEdit`/`SplitLeaf`/`MergeLeaves` carries the prior
text-op id (`prev`) and is buffered until it arrives, keeping out-of-order delivery
convergent.

## Dotted version frontier

The frontier summarizing "which ops do I hold" is a **dot set** — per peer, a
contiguous prefix plus out-of-order holes — never a per-peer max counter:

```text
frontier[peer] = { contiguous, sparse: {…} }
```

`diff(their_frontier)` returns the ops a replica holds that the partner's frontier
lacks (a true set difference over dots), ordered by dotted id. `apply_update` is
idempotent (already-held ops are skipped) and buffers ops whose parent/target or
`prev` has not arrived yet.

A per-peer *max* would record only the highest delivered dot and imply every lower
dot is held; delivering dot 3 while dot 2 is missing would make the partner believe
it holds 2, so its diff would omit an op it genuinely lacks and the replicas would
never converge. The dot set keeps the hole representable and re-requestable. This
is proven in `LazilyFormal.LosslessTreeSync` (`frontier_no_skip`,
`perPeerMax_skips`) and exercised by the
[`non_contiguous_anti_entropy`](conformance.md) fixture.

## Offset policy

Wire and API text offsets are **UTF-8 byte offsets, leaf-local**. The embedded text
CRDT is char-indexed, so the byte→char conversion happens only at the two
byte-taking mutators (`edit_leaf`, `split_leaf`), against that leaf's current text.
Offsets must land on a UTF-8 char boundary and within the leaf, else the mutation
is rejected. No binding may treat UTF-16 code units as wire offsets; the Kotlin/JS
bindings (later milestones) must convert.

## Conformance

The M1 fixtures live in `conformance/lossless-tree/` as compute fixtures — each
builds an initial tree on replica `a`, runs a schedule of ops / forks /
anti-entropy syncs across named replicas, and asserts exact rendered text,
live-node counts, and convergence across delivery orders:

- `exact_roundtrip` — Token/Trivia/Raw/Error leaves incl. an invalid span and
  multi-byte text; `render == source`;
- `one_leaf_edit_delta` — a one-leaf edit at a byte offset into multi-byte text,
  delivered by anti-entropy;
- `split_merge` — split then merge, render preserved, live-node count grows then
  restores;
- `concurrent_insert_same_parent` — two replicas insert into the same gap; both
  survive, deterministic order;
- `concurrent_reorder_and_leaf_edit` — a concurrent move + text edit both apply;
- `non_contiguous_anti_entropy` — a delivery hole is re-requested and converges;
- `token_trivia_preservation` — a leaf edit leaves adjacent Token/Trivia leaves
  byte-for-byte unchanged;
- `invalid_source_roundtrip` — unclosed fence / comment carried as Error leaves
  round-trips exactly, and editing an adjacent Raw leaf keeps the Error spans;
- `concurrent_conflict_preserves_text` — incompatible concurrent shapes (element
  wrap vs bare leaf) both survive with no bytes dropped (text preservation wins
  over semantic shape; adapter-level raw/error degradation layers above the core).

See [Conformance Fixtures](conformance.md) for the fixture format and the binding
replay contract.

## Wire schemas

The op-delta wire form is pinned by two JSON Schemas, derived from the lazily-rs
reference's serde output (which is the normative form):

- `schemas/lossless-tree.json` — the shared vocabulary `$defs`: `OpId`, `SortKey`
  (`frac` is a u8 array, never base64), `LeafKind` (PascalCase on the wire),
  `NodeSeed`, `TextOp`, the externally-tagged `TreeOpKind` / `TreeOp`, and the
  dotted `TreeVersionFrontier` / `DotRange`.
- `schemas/lossless-tree-delta.json` — the `TreeUpdate` message: `{ "ops": [TreeOp,
  …] }`, the output of `diff` and the input to `apply_update`.

The reference validates its own `TreeUpdate` and frontier serde output against
these schemas (`lazily-rs/tests/lossless_tree_schema.rs`), and the M2 Kotlin/JS
ports validate their emitted frames against the same files. The snapshot/checkpoint
wire schema is deferred with snapshot/GC.

## Capability

A binding that implements this chapter advertises the capability name
`lossless_tree_crdt_v1` (reserved here; wired into `SessionHandshake` capability
negotiation in a later milestone). A peer that lacks it falls back to the flat
text CRDT floor.
