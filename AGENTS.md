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

<!-- tsift:code-navigation v=0.1.77 -->
## Code Navigation

Keep this block self-contained for Codex/OpenCode prompt reuse. If this repository also ships current `.claude/skills/tsift/SKILL.md` or `runbooks/code-navigation.md`, use those deeper runbooks for command detail instead of expanding this block.

Run `tsift status` at session start from the owning repo root. If the task or file lives under a git submodule (for example `src/tsift/...`), switch to that submodule root first so the harness loads the narrower local instructions and repo state instead of the superproject root. If status prints a `run:` recommendation for stale or missing tsift state, run `tsift status --fix` before relying on tsift results; when the harness cannot perform write commands, ask the user to run the printed command instead. Codex projects can install a prompt-time auto-reindex hook with `tsift init --codex`; OpenCode projects can install per-project tsift command shortcuts with `tsift init --opencode`.

Use the commands listed in its `use:` output:
- `tsift --envelope source-read <file> --budget normal` — AST-symbol projection with span metadata and source-window expansion commands (prefer over cat/head for source code files)
- `tsift --envelope symbol-read <symbol> --budget normal` — token-budgeted symbol body, AST span metadata, child refs, and graph/source expansion commands
- `tsift --envelope search <query> --budget normal` — AST-aware hybrid search preview (prefer over grep/rg)
- `tsift --envelope explain <symbol> --budget normal` — callers, callees, community preview
- `tsift graph <symbol> --callers` / `--callees` — call graph navigation
- `tsift summarize <symbol>` — cached summary (only when listed in `use:`)
- `tsift workflow search` — ordered exact/search/explain/summarize/digest recipe that preserves result handles across expansions

When a search envelope includes `report.scale_guard`, run one of its `narrow_commands` before dispatching parallel agents. The guard means the original result set or corpus is broad enough that fan-out should start from a narrower cited handle, path, or exact query.

Prefer bounded digest commands over raw transcript, diff, and verbose-log reads:
- `tsift --envelope session-review <path> --next-context --budget normal` or `tsift --envelope context-pack <path> --budget normal` instead of replaying long session docs, JSONL transcripts, or agent-doc runtime logs with `cat`, `tail`, or `sed`.
- `tsift diff-digest [path]` (`--cached`, `--revision <rev>`) instead of `git diff`, `git show`, or patch-style `git log`.
- `tsift --envelope digest-runner --kind test --path . --shell-command '<test command>'` / `tsift --envelope digest-runner --kind log --path . --shell-command '<build command>'` for noisy test/build/install output, or let the rewrite/hooks create those artifact-backed envelopes for `cargo test`, `pytest`, and verbose cargo commands.
- If RTK is installed, digest-runner delegates supported generic command families through `rtk rewrite` and records the chosen compact filter in `report.filter` while preserving tsift artifact handles.
- Codex, OpenCode, and other harnesses without Claude-style `PreToolUse` hooks should run `tsift rewrite --run '<command>'` before broad `rg`/recursive grep, raw transcript/session/log reads, `git diff`/`git show`/single-patch `git log`, `cargo test`/`pytest`, and cargo build/check/clippy/install commands so the same search, session-digest, diff-digest, and digest-runner rewrites apply manually. OpenCode can install this path as `/tsift-rewrite-run` with `tsift init --opencode`.

For local verification, run `make check` before committing. After local changes, check the latest GitHub Actions CI run with `gh run list --workflow CI --limit 1` and fix any failing tests before calling the work complete.

Only read full source files when tsift results are insufficient.
<!-- /tsift:code-navigation -->
