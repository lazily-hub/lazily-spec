namespace LazilyFormal.Replication

/-! Minimal algebraic pins for `CrdtTree` and the storage-independent durable outbox. -/

/-- The abstract document state join. Text/tree implementations refine this `max`
semilattice with identity-bearing operation sets. -/
def treeJoin (a b : Nat) : Nat := max a b

theorem treeJoin_comm (a b : Nat) : treeJoin a b = treeJoin b a := by
  unfold treeJoin
  exact Nat.max_comm a b

theorem treeJoin_assoc (a b c : Nat) :
    treeJoin (treeJoin a b) c = treeJoin a (treeJoin b c) := by
  unfold treeJoin
  exact Nat.max_assoc a b c

theorem treeJoin_idem (a : Nat) : treeJoin a a = a := by
  unfold treeJoin
  exact Nat.max_self a

/-- Durable cursors advance monotonically even when a stale acknowledgement arrives. -/
def advanceCursor (cursor ack : Nat) : Nat := max cursor ack

theorem cursor_monotone (cursor ack : Nat) : cursor ≤ advanceCursor cursor ack := by
  unfold advanceCursor
  exact Nat.le_max_left cursor ack

/-- A replay suffix contains only epochs strictly above the durable cursor. -/
def replayFrom (cursor : Nat) (frames : List (Nat × Nat)) : List (Nat × Nat) :=
  frames.filter (fun frame => decide (cursor < frame.1))

theorem replay_prune_safe (cursor epoch payload : Nat) (frames : List (Nat × Nat))
    (member : (epoch, payload) ∈ replayFrom cursor frames) : cursor < epoch := by
  unfold replayFrom at member
  have filtered := (List.mem_filter.mp member).2
  simpa using filtered

theorem appended_unacked_replays (cursor epoch payload : Nat) (frames : List (Nat × Nat))
    (fresh : cursor < epoch) :
    (epoch, payload) ∈ replayFrom cursor ((epoch, payload) :: frames) := by
  simp [replayFrom, fresh]

end LazilyFormal.Replication
