# lazily-spec

Canonical wire protocol, JSON Schemas, conformance fixtures, and the
cross-language feature-coverage matrix for the lazily reactive-signals family.

## Commit & Push

Commit and push completed work at the end of every turn that changed code,
schemas, fixtures, docs, or the coverage matrix — do not leave finished work
uncommitted. Run `make check` first and ensure it is green; stage only the
files that belong to the change (never secrets or private customer names — see
the workspace `runbooks/private-name-hygiene.md`); write a concise commit
message in the repo's existing style; push to the current branch on `origin`.
This standing rule overrides the harness default of "commit only when
explicitly asked" for this repo.

## Publishing a corpus change

**Push the `conformance/` change here FIRST, then verify and push the bindings.**

Bindings verify against this repo's **working tree**; their CI **clones published
`main`**. A corpus change can be green in nine local checkouts and invisible to
all nine CI runs, and any binding pinning a scenario or fixture count fails on
the mismatch. A count or floor in a binding must describe what CI's clone
guarantees, never what your working tree happens to hold.

`make check` warns when `conformance/` is ahead of `origin/main`. Full rule and
worked example: [docs/conformance.md](docs/conformance.md) § Publishing a corpus
change (`#lzspecpushbeforebindings`).

## Scenario identity

Every scenario in `conformance/` carries a unique snake_case **`id`**. That is
the canonical identity (`#recommendedconformanceco`): it is what all nine
bindings resolve to, what each binding's replay ledger records, and what a
runner dispatches on. `name` is an optional human label — prose is fine there,
and rewording it must never change what a ledger entry means.

`make check` enforces this through `scenario-identity-check`, which fails on a
missing `id`, a non-snake_case `id`, an `id` repeated within a fixture, and an
empty corpus. Adding a scenario means coining an id; renaming one rebinds a
ledger entry in ten repositories, so do it deliberately and sweep the bindings
in the same change.

Fixture subsets vendored by lazily-py, lazily-dart, lazily-rs, lazily-go, and
lazily-zig are reconciled here: run `make fixture-copies-sync` after any corpus
edit.

## Prose assertion keys

An assertion key whose value is an English paragraph states an obligation and
carries nothing a runner can compare (`#lzprosekeyconvention`). The corpus
declares which keys those are in `assertions.prose`; a binding never decides for
itself, because when it did, the nine landed on four different treatments of the
same four keys. A prose key is **discharged** by naming the executable keys that
carry its obligation, verified against what the run actually asserted — never
asserted (that pins wording) and never excused with free text (that is
unfalsifiable).

Adding a paragraph to an `assertions` block therefore means listing it in that
block's `prose` array in the same edit; `make check` fails otherwise, and so does
every binding, because `prose` is itself a key their consumption guards see. The
full clause, the seven tracker failure modes, and the pinned per-binding API
spelling are in [`docs/conformance.md`](docs/conformance.md#prose-assertion-keys-lzprosekeyconvention).
Reserved annotation names — `note`, `description`, `reason` — stay exempt inside
per-step blocks, so they must not carry a MUST.

<!-- tsift:code-navigation v=0.1.80 -->
## Code Navigation

Run `tsift status` at session start from the owning repo root. If the task or file lives under a git submodule (for example `src/tsift/...`), switch to that submodule root first so the harness loads the narrower local instructions and repo state instead of the superproject root. If status prints a `run:` recommendation for stale or missing tsift state, run `tsift status --fix` before relying on tsift results; when the harness cannot perform write commands, ask the user to run the printed command instead.

Prefer tsift envelopes over raw reads:
- `tsift --envelope search <query>` instead of `grep`/`rg`
- `tsift --envelope source-read <file>` / `tsift --envelope symbol-read <symbol>` instead of `cat`/`head`
- `tsift --envelope explain <symbol>` and `tsift graph <symbol> --callers` / `--callees` for call graphs
- `tsift diff-digest [path]` instead of `git diff`, `git show`, or patch-style `git log`
- `tsift --envelope session-review <path>` / `tsift --envelope context-pack <path>` instead of replaying long session docs, transcripts, or runtime logs
- `tsift --envelope digest-runner --kind test|log --path . --shell-command '<command>'` instead of raw test/build output

Command detail lives in [`runbooks/code-navigation.md`](runbooks/code-navigation.md) — budgets, `tsift workflow search`, `report.scale_guard` handling, the harness rewrite path for `PreToolUse`-less harnesses, and Codex/OpenCode integration. `tsift init` writes and versions that runbook alongside this block, so it is present in every initialized checkout; read it before broad exploration instead of expanding this block. A repository that also ships a current `.claude/skills/tsift/SKILL.md` should use that skill as the deeper source.

For local verification, run `make check` before committing. After local changes, check the latest GitHub Actions CI run with `gh run list --workflow CI --limit 1` and fix any failing tests before calling the work complete.

Only read full source files when tsift results are insufficient.
<!-- /tsift:code-navigation -->
