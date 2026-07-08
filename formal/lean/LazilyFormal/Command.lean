namespace LazilyFormal.Command

/-! # Command / RPC message plane — minimal embedded model

The embedded, self-contained counterpart of the standalone
`lazily-formal/LazilyFormal/Command.lean`. It carries the same command-plane
projection kernel and the same theorems, but defines its own minimal
`ReceiptOutcome` inline (this embedded tree has no `Receipt.lean`).

Sync rule: this file is the minimal mirror. The standalone model is the source
of truth for the reducer shape; both must build. If the reducer changes, update
both.

The properties are deliberately negative where it matters: progress events never
complete a command; only a terminal causal receipt does. Stale generations are
discarded, duplicate submits are idempotent, a cancel cannot override an applied
command, conflicting terminal outcomes fail closed, and an RPC `call` is derived
behavior that cannot resolve before a terminal receipt. -/

abbrev Generation := Nat

/-- Generic receipt outcomes (mirror of `receipts.json`). `observed` / `accepted`
    are non-terminal; `applied` / `rejected` are terminal. -/
inductive ReceiptOutcome where
  | observed | accepted | applied | rejected
  deriving Repr, DecidableEq

def ReceiptOutcome.isTerminal : ReceiptOutcome → Bool
  | .observed => false
  | .accepted => false
  | .applied => true
  | .rejected => true

/-- Folded projection status for one command. -/
inductive CommandStatus where
  | absent | submitted | accepted | running
  | applied | rejected | cancelled | conflicted
  deriving Repr, DecidableEq

def CommandStatus.isTerminal : CommandStatus → Bool
  | .absent => false
  | .submitted => false
  | .accepted => false
  | .running => false
  | .applied => true
  | .rejected => true
  | .cancelled => true
  | .conflicted => true

/-- Progress event kinds — all non-terminal. -/
inductive EventKind where
  | observed | accepted | started
  deriving Repr, DecidableEq

def progressStatus : EventKind → CommandStatus
  | .observed => .accepted
  | .accepted => .accepted
  | .started => .running

def terminalStatusOf : ReceiptOutcome → CommandStatus
  | .observed => .accepted
  | .accepted => .accepted
  | .applied => .applied
  | .rejected => .rejected

inductive Input where
  | submit : Generation → Input
  | progress : Generation → EventKind → Input
  | receipt : Generation → ReceiptOutcome → Input
  | cancel : Generation → Input
  deriving Repr

def Input.isTerminalKind : Input → Bool
  | .submit _ => false
  | .progress _ _ => false
  | .receipt _ o => o.isTerminal
  | .cancel _ => true

structure CmdState where
  generation : Generation
  status : CommandStatus
  deriving Repr, DecidableEq

def initial : CmdState := { generation := 0, status := .absent }

def callResolved (s : CmdState) : Bool := s.status.isTerminal

def step (s : CmdState) (inp : Input) : CmdState :=
  match inp with
  | .submit g =>
      match s.status with
      | .absent => { generation := g, status := .submitted }
      | _ => s
  | .progress g k =>
      if s.status = .absent then s
      else if g ≠ s.generation then s
      else if s.status.isTerminal then s
      else { s with status := progressStatus k }
  | .receipt g o =>
      if s.status = .absent then s
      else if g ≠ s.generation then s
      else if o.isTerminal then
        let incoming := terminalStatusOf o
        if s.status.isTerminal then
          if s.status = incoming then s
          else { s with status := .conflicted }
        else { s with status := incoming }
      else
        if s.status.isTerminal then s
        else { s with status := terminalStatusOf o }
  | .cancel g =>
      if s.status = .absent then s
      else if g ≠ s.generation then s
      else if s.status.isTerminal then s
      else { s with status := .cancelled }

def fold (s : CmdState) (inputs : List Input) : CmdState :=
  inputs.foldl step s

def resync (_ : CmdState) (snapshot : CmdState) : CmdState := snapshot

/-! ## Theorems -/

theorem progress_nonterminal (k : EventKind) :
    (progressStatus k).isTerminal = false := by
  cases k <;> rfl

theorem terminalStatusOf_nonterminal (o : ReceiptOutcome) (ho : o.isTerminal = false) :
    (terminalStatusOf o).isTerminal = false := by
  cases o <;>
    simp_all [terminalStatusOf, ReceiptOutcome.isTerminal, CommandStatus.isTerminal]

/-- `accepted_nonterminal`: an `accepted` progress event cannot complete a command. -/
theorem accepted_nonterminal (s : CmdState) (g : Generation)
    (hpresent : s.status ≠ .absent)
    (hgen : g = s.generation)
    (hnonterminal : s.status.isTerminal = false) :
    (step s (.progress g .accepted)).status.isTerminal = false := by
  have hstep : step s (.progress g .accepted)
      = { s with status := progressStatus .accepted } := by
    simp [step, hpresent, hgen, hnonterminal]
  rw [hstep]
  exact progress_nonterminal .accepted

/-- `stale_generation_noop` (progress). -/
theorem stale_progress_noop (s : CmdState) (g : Generation) (k : EventKind)
    (hpresent : s.status ≠ .absent) (hstale : g ≠ s.generation) :
    step s (.progress g k) = s := by
  simp [step, hpresent, hstale]

/-- `stale_generation_noop` (receipt). -/
theorem stale_receipt_noop (s : CmdState) (g : Generation) (o : ReceiptOutcome)
    (hpresent : s.status ≠ .absent) (hstale : g ≠ s.generation) :
    step s (.receipt g o) = s := by
  simp [step, hpresent, hstale]

/-- `duplicate_submit_idempotent`. -/
theorem duplicate_submit_idempotent (g g' : Generation) :
    step (step initial (.submit g)) (.submit g') = step initial (.submit g) := by
  simp [step, initial]

/-- `cancel_cannot_override_applied`. -/
theorem cancel_cannot_override_applied (s : CmdState) (g : Generation)
    (happlied : s.status = .applied) :
    step s (.cancel g) = s := by
  have hterm : s.status.isTerminal = true := by rw [happlied]; rfl
  have habsent : s.status ≠ .absent := by rw [happlied]; decide
  by_cases hg : g = s.generation
  · simp [step, habsent, hg, hterm]
  · simp [step, habsent, hg]

/-- `terminal_conflict_fails_closed`. -/
theorem terminal_conflict_fails_closed (s : CmdState) (g : Generation)
    (happlied : s.status = .applied) (hgen : g = s.generation) :
    (step s (.receipt g .rejected)).status = .conflicted := by
  have habsent : s.status ≠ .absent := by rw [happlied]; decide
  simp [step, hgen, terminalStatusOf, ReceiptOutcome.isTerminal,
    CommandStatus.isTerminal, happlied]

/-- Idempotent terminal receipt. -/
theorem terminal_receipt_idempotent (s : CmdState) (g : Generation)
    (happlied : s.status = .applied) (hgen : g = s.generation) :
    step s (.receipt g .applied) = s := by
  have habsent : s.status ≠ .absent := by rw [happlied]; decide
  simp [step, hgen, terminalStatusOf, ReceiptOutcome.isTerminal,
    CommandStatus.isTerminal, happlied]

/-- `projection_reconnect_equiv`. -/
theorem projection_reconnect_equiv (start : CmdState) (inputs : List Input) :
    resync initial (fold start inputs) = fold start inputs := by
  rfl

theorem fold_nonterminal_inputs (s : CmdState) (inputs : List Input)
    (hs : s.status.isTerminal = false)
    (hinputs : ∀ inp ∈ inputs, inp.isTerminalKind = false) :
    (fold s inputs).status.isTerminal = false := by
  induction inputs generalizing s with
  | nil => simpa [fold] using hs
  | cons inp rest ih =>
    have hhead : inp.isTerminalKind = false := hinputs inp (List.mem_cons_self)
    have htail : ∀ x ∈ rest, x.isTerminalKind = false := by
      intro x hx; exact hinputs x (List.mem_cons_of_mem inp hx)
    have hstep : (step s inp).status.isTerminal = false := by
      cases inp with
      | submit g =>
        cases hstatus : s.status <;> simp_all [step, CommandStatus.isTerminal]
      | progress g k =>
        by_cases habsent : s.status = .absent
        · simpa [step, habsent] using hs
        · by_cases hgen : g = s.generation
          · by_cases hterm : s.status.isTerminal = true
            · simp_all
            · simp [step, habsent, hgen, hterm, progress_nonterminal]
          · simp [step, habsent, hgen]; simpa using hs
      | receipt g o =>
        have ho : o.isTerminal = false := by
          simpa [Input.isTerminalKind] using hhead
        by_cases habsent : s.status = .absent
        · simpa [step, habsent] using hs
        · by_cases hgen : g = s.generation
          · simp [step, habsent, hgen, ho, hs, terminalStatusOf_nonterminal o ho]
          · simp [step, habsent, hgen]; simpa using hs
      | cancel g =>
        simp [Input.isTerminalKind] at hhead
    exact ih (step s inp) hstep htail

/-- `rpc_call_terminal_only`. -/
theorem rpc_call_terminal_only (g : Generation) (inputs : List Input)
    (hinputs : ∀ inp ∈ inputs, inp.isTerminalKind = false) :
    callResolved (fold (step initial (.submit g)) inputs) = false := by
  have hs : (step initial (.submit g)).status.isTerminal = false := by
    simp [step, initial, CommandStatus.isTerminal]
  simpa [callResolved] using fold_nonterminal_inputs _ inputs hs hinputs

end LazilyFormal.Command
