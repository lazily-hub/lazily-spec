namespace LazilyFormal.IPC

abbrev NodeId := Nat
abbrev Epoch := Nat
abbrev Payload := Nat

inductive NodeKind where
  | cell
  | slot
  | signal
  deriving DecidableEq, Repr

inductive NodeState where
  | resolved (payload : Payload)
  | dirty
  | unset
  deriving DecidableEq, Repr

structure NodeSnapshot where
  node : NodeId
  kind : NodeKind
  state : NodeState
  deriving DecidableEq, Repr

structure EdgeSnapshot where
  dependent : NodeId
  dependency : NodeId
  deriving DecidableEq, Repr

structure Snapshot where
  epoch : Epoch
  nodes : List NodeSnapshot
  edges : List EdgeSnapshot
  roots : List NodeId
  deriving DecidableEq, Repr

inductive DeltaOp where
  | cellSet (node : NodeId) (payload : Payload)
  | slotValue (node : NodeId) (payload : Payload)
  | invalidate (node : NodeId)
  | nodeAdd (node : NodeId) (kind : NodeKind) (state : NodeState)
  | nodeRemove (node : NodeId)
  | edgeAdd (dependent : NodeId) (dependency : NodeId)
  | edgeRemove (dependent : NodeId) (dependency : NodeId)
  deriving DecidableEq, Repr

structure Delta where
  baseEpoch : Epoch
  epoch : Epoch
  ops : List DeltaOp
  deriving DecidableEq, Repr

inductive ApplyDecision where
  | apply (newEpoch : Epoch)
  | resyncRequired
  deriving DecidableEq, Repr

def nextDelta (baseEpoch : Epoch) (ops : List DeltaOp) : Delta :=
  { baseEpoch := baseEpoch, epoch := baseEpoch + 1, ops := ops }

def isSequentialAfter (lastEpoch : Epoch) (delta : Delta) : Bool :=
  delta.baseEpoch == lastEpoch && delta.epoch == lastEpoch + 1

def applyDelta (lastEpoch : Epoch) (delta : Delta) : ApplyDecision :=
  if isSequentialAfter lastEpoch delta then
    ApplyDecision.apply delta.epoch
  else
    ApplyDecision.resyncRequired

theorem nextDelta_epoch (baseEpoch : Epoch) (ops : List DeltaOp) :
    (nextDelta baseEpoch ops).epoch = baseEpoch + 1 := by
  rfl

theorem nextDelta_sequential (baseEpoch : Epoch) (ops : List DeltaOp) :
    isSequentialAfter baseEpoch (nextDelta baseEpoch ops) = true := by
  simp [isSequentialAfter, nextDelta]

theorem apply_nextDelta (baseEpoch : Epoch) (ops : List DeltaOp) :
    applyDelta baseEpoch (nextDelta baseEpoch ops) =
      ApplyDecision.apply (baseEpoch + 1) := by
  simp [applyDelta, isSequentialAfter, nextDelta]

theorem gap_requires_resync
    (lastEpoch baseEpoch epoch : Epoch)
    (ops : List DeltaOp)
    (gap : Not (baseEpoch = lastEpoch)) :
    applyDelta lastEpoch { baseEpoch := baseEpoch, epoch := epoch, ops := ops } =
      ApplyDecision.resyncRequired := by
  simp [applyDelta, isSequentialAfter, gap]

theorem nonsequential_epoch_requires_resync
    (lastEpoch epoch : Epoch)
    (ops : List DeltaOp)
    (badEpoch : Not (epoch = lastEpoch + 1)) :
    applyDelta lastEpoch { baseEpoch := lastEpoch, epoch := epoch, ops := ops } =
      ApplyDecision.resyncRequired := by
  simp [applyDelta, isSequentialAfter, badEpoch]

def cellSetOps (node : NodeId) (oldValue newValue : Payload) : List DeltaOp :=
  if oldValue = newValue then
    []
  else
    [DeltaOp.cellSet node newValue]

theorem equal_cell_set_is_silent
    (node : NodeId)
    (oldValue newValue : Payload)
    (same : oldValue = newValue) :
    cellSetOps node oldValue newValue = [] := by
  simp [cellSetOps, same]

theorem changed_cell_set_emits_cell_set
    (node : NodeId)
    (oldValue newValue : Payload)
    (changed : Not (oldValue = newValue)) :
    cellSetOps node oldValue newValue = [DeltaOp.cellSet node newValue] := by
  simp [cellSetOps, changed]

def downstreamInvalidations (downstream : List NodeId) : List DeltaOp :=
  downstream.map DeltaOp.invalidate

def memoOps
    (node : NodeId)
    (oldValue newValue : Payload)
    (downstream : List NodeId) :
    List DeltaOp :=
  if oldValue = newValue then
    []
  else
    DeltaOp.slotValue node newValue :: downstreamInvalidations downstream

theorem equal_memo_suppresses_downstream
    (node : NodeId)
    (oldValue newValue : Payload)
    (downstream : List NodeId)
    (same : oldValue = newValue) :
    memoOps node oldValue newValue downstream = [] := by
  simp [memoOps, same]

theorem changed_memo_publishes_then_invalidates
    (node : NodeId)
    (oldValue newValue : Payload)
    (downstream : List NodeId)
    (changed : Not (oldValue = newValue)) :
    memoOps node oldValue newValue downstream =
      DeltaOp.slotValue node newValue :: downstreamInvalidations downstream := by
  simp [memoOps, changed]

def signalOps (node : NodeId) (oldValue newValue : Payload) : List DeltaOp :=
  if oldValue = newValue then
    []
  else
    [DeltaOp.slotValue node newValue]

theorem equal_signal_is_silent
    (node : NodeId)
    (oldValue newValue : Payload)
    (same : oldValue = newValue) :
    signalOps node oldValue newValue = [] := by
  simp [signalOps, same]

theorem changed_signal_materializes_slot_value
    (node : NodeId)
    (oldValue newValue : Payload)
    (changed : Not (oldValue = newValue)) :
    signalOps node oldValue newValue = [DeltaOp.slotValue node newValue] := by
  simp [signalOps, changed]

theorem signal_never_emits_bare_invalidate
    (node : NodeId)
    (oldValue newValue : Payload) :
    DeltaOp.invalidate node ∉ signalOps node oldValue newValue := by
  by_cases same : oldValue = newValue
  · simp [signalOps, same]
  · simp [signalOps, same]

structure BatchFlush where
  changedCells : List NodeId
  frontier : List NodeId
  frontierNodup : frontier.Nodup
  ops : List DeltaOp
  opsDescribeFrontier :
    ops = frontier.map DeltaOp.invalidate

def BatchFlush.toDelta (flush : BatchFlush) (baseEpoch : Epoch) : Delta :=
  nextDelta baseEpoch flush.ops

theorem batch_frontier_is_coalesced (flush : BatchFlush) :
    flush.frontier.Nodup := by
  exact flush.frontierNodup

theorem batch_flush_advances_epoch_once
    (flush : BatchFlush)
    (baseEpoch : Epoch) :
    (flush.toDelta baseEpoch).epoch = baseEpoch + 1 := by
  rfl

theorem batch_flush_ops_are_frontier_invalidations
    (flush : BatchFlush) :
    flush.ops = flush.frontier.map DeltaOp.invalidate := by
  exact flush.opsDescribeFrontier

end LazilyFormal.IPC
