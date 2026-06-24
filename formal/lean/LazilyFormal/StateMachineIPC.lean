import LazilyFormal.StateMachine
import LazilyFormal.IPC

/-!
# Cross-module proof: StateMachine → IPC Delta

Proves that a materialized `StateMachine.send` transition is observable on the
IPC wire as a `DeltaOp.cellSet` op — linking `StateMachine.lean` with `IPC.lean`.

A guard rejection (`none`) or self-transition (`some m.current`) produces no ops
(eql guard suppresses the cascade, matching the runtime `Cell.set` behavior).
-/

namespace LazilyFormal.StateMachineIPC

open StateMachine
open IPC

/-- Translate a StateMachine send into IPC delta ops.

The machine's state is stored as a cell payload (`NodeId` → `Payload`).
When the transition accepts and the state changes, a `DeltaOp.cellSet` is
emitted. Guard rejections and self-transitions produce no ops. -/
def sendToOps (m : Machine) (e : Event) (node : NodeId) : List DeltaOp :=
  match m.transition m.current e with
  | some next => cellSetOps node m.current next
  | none => []

/-- Wrap a send's ops into a full IPC Delta at the given base epoch. -/
def sendToDelta (m : Machine) (e : Event) (node : NodeId) (baseEpoch : Epoch) : Delta :=
  nextDelta baseEpoch (sendToOps m e node)

/-- A guard rejection produces no ops. -/
theorem guard_rejection_no_ops
    (m : Machine) (e : Event) (node : NodeId)
    (rejected : m.transition m.current e = none) :
    sendToOps m e node = [] := by
  simp [sendToOps, rejected]

/-- A changed transition emits exactly one `cellSet` op for the new payload. -/
theorem changed_transition_emits_cellSet
    (m : Machine) (e : Event) (next : State) (node : NodeId)
    (accepted : m.transition m.current e = some next)
    (changed : next ≠ m.current) :
    sendToOps m e node = [DeltaOp.cellSet node next] := by
  simp only [sendToOps, accepted, cellSetOps, if_neg (Ne.symm changed)]

/-- A self-transition (some m.current) produces no ops — the eql guard
suppresses the `cellSet`, matching the runtime `Cell.set` behavior. -/
theorem self_transition_no_ops
    (m : Machine) (e : Event) (node : NodeId)
    (accepted : m.transition m.current e = some m.current) :
    sendToOps m e node = [] := by
  simp [sendToOps, accepted, cellSetOps]

/-- A changed transition produces an IPC Delta that passes sequential
application — the receiving peer accepts it and advances the epoch. -/
theorem changed_transition_accepts_delta
    (m : Machine) (e : Event) (next : State) (node : NodeId)
    (baseEpoch : Epoch)
    (accepted : m.transition m.current e = some next)
    (changed : next ≠ m.current) :
    applyDelta baseEpoch (sendToDelta m e node baseEpoch) =
      ApplyDecision.apply (baseEpoch + 1) := by
  rw [sendToDelta, changed_transition_emits_cellSet m e next node accepted changed]
  exact apply_nextDelta baseEpoch [DeltaOp.cellSet node next]

/-- A guard rejection produces an empty-but-valid delta (the peer still
advances the epoch, just with no ops to apply). -/
theorem guard_rejection_accepts_empty_delta
    (m : Machine) (e : Event) (node : NodeId) (baseEpoch : Epoch)
    (rejected : m.transition m.current e = none) :
    applyDelta baseEpoch (sendToDelta m e node baseEpoch) =
      ApplyDecision.apply (baseEpoch + 1) := by
  rw [sendToDelta, guard_rejection_no_ops m e node rejected]
  exact apply_nextDelta baseEpoch []

/-- The send state from a changed transition matches the payload in the
emitted cellSet op — the wire value reflects the machine's new state. -/
theorem wire_payload_matches_new_state
    (m : Machine) (e : Event) (next : State) (node : NodeId)
    (accepted : m.transition m.current e = some next)
    (changed : next ≠ m.current) :
    ∃ payload, DeltaOp.cellSet node payload ∈ sendToOps m e node ∧ payload = next := by
  refine ⟨next, ?_, rfl⟩
  rw [changed_transition_emits_cellSet m e next node accepted changed]
  simp

end LazilyFormal.StateMachineIPC
