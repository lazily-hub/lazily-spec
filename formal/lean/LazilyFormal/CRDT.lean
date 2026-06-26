namespace LazilyFormal.CRDT

/-! # Distributed CRDT cell plane: convergence + causal-stability obligations

Formal obligations for the multi-writer plane (`#lzcrdtplane`). Two properties
back the whole plane:

* **Convergence** — the cell-register join is a semilattice (commutative,
  associative, idempotent), so replicas that exchange state in any order, with
  duplication, converge to the same value.
* **Causal stability** — a tombstone the plane deems *collectable* (delete stamp
  at or below the all-replicas-aware stability frontier) has provably been
  observed by **every** replica, so garbage-collecting it can never lose an
  edit. This is the safety invariant the Rust `CrdtPlane::is_collectable` /
  `gc_seq` / `gc_text` rely on.

A causal stamp (`HlcStamp` / `OpId`) is a *total order*; only its order matters
for these laws, so it is modeled as its order-position in `Nat`. -/

/-- A causal stamp, abstracted as its total-order position. -/
abbrev Stamp := Nat

/-- A replica/peer identity. -/
abbrev Peer := Nat

/-! ## Stamp join: the register semilattice

The last-writer-wins join keeps the higher-stamped write; the per-peer
`StampFrontier`/`OpIdFrontier` entry keeps the higher observed stamp. Both are
the same join — `max` on the stamp total order. Modeling the value as a function
of the stamp captures the real invariant (*a stamp uniquely identifies a write*,
so equal stamps carry equal values), reducing the join to `max`. -/

/-- The stamp join: the higher stamp wins. -/
def stampJoin (a b : Stamp) : Stamp := max a b

/-- Convergence law 1: the join is commutative (arrival order is irrelevant). -/
theorem stampJoin_comm (a b : Stamp) : stampJoin a b = stampJoin b a := by
  unfold stampJoin; exact Nat.max_comm a b

/-- Convergence law 2: the join is associative. -/
theorem stampJoin_assoc (a b c : Stamp) :
    stampJoin (stampJoin a b) c = stampJoin a (stampJoin b c) := by
  unfold stampJoin; exact Nat.max_assoc a b c

/-- Convergence law 3: the join is idempotent (re-merging the same state, or a
duplicated op, is a no-op). -/
theorem stampJoin_idem (a : Stamp) : stampJoin a a = a := by
  unfold stampJoin; exact Nat.max_self a

/-! ## Causal-stability frontier

`observed p` is the highest stamp this plane has seen from peer `p` (the
per-peer `max` of the `StampFrontier`). The stability frontier over a nonempty
membership is the **minimum** of those observations — the causal point every
replica has passed. A delete stamped `s` is collectable once `s ≤` that
frontier. -/

/-- The stability frontier over a nonempty membership (`head :: tail`): the
minimum observed stamp across every member. -/
def frontier (head : Peer) (tail : List Peer) (observed : Peer → Stamp) : Stamp :=
  tail.foldl (fun acc p => min acc (observed p)) (observed head)

/-- A tombstone stamped `s` is collectable once it is at or below the frontier. -/
def collectable (head : Peer) (tail : List Peer) (observed : Peer → Stamp) (s : Stamp) : Bool :=
  decide (s ≤ frontier head tail observed)

/-- A running `min`-fold never exceeds its seed: the frontier is `≤` the head's
observation. -/
theorem foldlMin_le_init (l : List Peer) (observed : Peer → Stamp) (init : Stamp) :
    l.foldl (fun acc p => min acc (observed p)) init ≤ init := by
  induction l generalizing init with
  | nil => simp
  | cons q qs ih =>
    simp only [List.foldl]
    exact Nat.le_trans (ih (min init (observed q))) (Nat.min_le_left init (observed q))

/-- A running `min`-fold is `≤` every element folded in: the frontier is `≤`
every member's observation. -/
theorem foldlMin_le_mem (l : List Peer) (observed : Peer → Stamp) (init : Stamp)
    (p : Peer) (mem : p ∈ l) :
    l.foldl (fun acc x => min acc (observed x)) init ≤ observed p := by
  induction l generalizing init with
  | nil => simp at mem
  | cons q qs ih =>
    rcases List.mem_cons.mp mem with rfl | mem'
    · simp only [List.foldl]
      exact Nat.le_trans (foldlMin_le_init qs observed _) (Nat.min_le_right _ _)
    · simp only [List.foldl]
      exact ih (min init (observed q)) mem'

/-- The frontier never exceeds any member's observation. -/
theorem frontier_le_member
    (head : Peer) (tail : List Peer) (observed : Peer → Stamp) (p : Peer)
    (mem : p ∈ head :: tail) :
    frontier head tail observed ≤ observed p := by
  unfold frontier
  rcases List.mem_cons.mp mem with rfl | mem'
  · exact foldlMin_le_init tail observed _
  · exact foldlMin_le_mem tail observed (observed head) p mem'

/-- **Causal-stability safety.** If the plane marks a tombstone stamped `s`
collectable, then `s` is at or below *every* member's observation — i.e. every
replica has provably observed the deletion, so collecting the tombstone cannot
lose an edit. This is the soundness of the `min`-over-membership watermark that
drives `SeqCrdt`/`TextCrdt` GC. -/
theorem collectable_implies_observed_everywhere
    (head : Peer) (tail : List Peer) (observed : Peer → Stamp) (s : Stamp) (p : Peer)
    (mem : p ∈ head :: tail)
    (coll : collectable head tail observed s = true) :
    s ≤ observed p := by
  have hf : s ≤ frontier head tail observed := by
    simpa [collectable] using coll
  have hp : frontier head tail observed ≤ observed p := frontier_le_member head tail observed p mem
  exact Nat.le_trans hf hp

end LazilyFormal.CRDT
