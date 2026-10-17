# Reproducible Core cohorts

A Core cohort is an immutable bill of materials (BOM), not a list of moving
branches. Its schema is [`schemas/core-cohort.json`](../schemas/core-cohort.json),
and `scripts/verify_core_cohort.py` is the semantic verifier.

The candidate manifest is deliberately not checked in yet. A truthful candidate
can only be cut after the Core profile, capability claims, API compatibility,
packaged-consumer gates, release pins, and Rust publication path are green. Until
then, inventing tags, artifact hashes, or registry evidence would make the BOM
look reproducible while pointing at artifacts that were never qualified.

## Evidence layout

The manifest names every byte used to qualify a cohort:

- the exact Lazily Spec repository, tag, peeled 40-hex commit, conformance
  revision, and Core profile digest;
- each binding's exact repository, tag, peeled commit, Core API generation, wire
  version, Core imports, toolchain bounds, and module compatibility ranges;
- every package coordinate and version, artifact digest, provenance statement,
  and captured registry response;
- evidence digests for profile, API, fixture, package, pre-publish consumer, and
  installed published-consumer gates.

Paths are relative to an evidence directory. The verifier rejects absolute or
parent-traversing paths, missing evidence, and digest mismatches. Registry
responses are captured as evidence because a later rerun must be able to explain
whether a package was present or yanked when the cohort was finalized.

## Verification modes

Validate a candidate before publishing one binding:

```sh
uv run python scripts/verify_core_cohort.py cohorts/2026-10-12.rc1.json \
  --artifact-root .cohort-evidence \
  --spec-root . \
  --require-publish-ready \
  --expected-spec-commit "$SPEC_COMMIT" \
  --expected-binding rust \
  --expected-commit "$GITHUB_SHA" \
  --expected-tag "$GITHUB_REF_NAME"
```

`--require-publish-ready` requires the profile, API, fixture, package, and
pre-publish installed-consumer gates to have passed. The published-consumer gate
may still be pending. A binding release job must depend on this gate; merely
running it alongside a publish job is not sufficient.

After registry propagation, download every released artifact, provenance
statement, registry response, and gate record into the evidence directory, then
finalize the manifest and run:

```sh
uv run python scripts/verify_core_cohort.py cohorts/2026-10-12.beta1.json \
  --artifact-root .cohort-evidence \
  --repo-root .. \
  --spec-root . \
  --require-final \
  --report-json out/core-cohort.json \
  --report-markdown out/core-cohort.md
```

Final verification requires the complete nine-binding set, an available (not
missing or yanked) registry status for every artifact, and all six gates to pass.
With `--repo-root`, every source tag must exist locally, peel to the manifest
commit, and match the checked-out `HEAD`.

## Spec-side cohort qualification

`.github/workflows/core-cohort-qualification.yml` is a manually dispatched,
non-publishing workflow in Lazily Spec. Dispatch it at the exact Spec version tag
named by the candidate manifest and provide the manifest path plus one
`vVERSION@40-hex-commit` pin for each of the nine bindings. The ten total inputs
stay within GitHub's `workflow_dispatch` limit.

The workflow rejects a branch dispatch, a floating or malformed pin, a pin that
differs from the manifest, and a source tag that does not peel to the supplied
commit. It checks out all ten repositories at those immutable revisions,
generates fresh binding runtime evidence, re-runs the aggregate Core gates, and
uploads the manifest, dispatch pins, reports, and proof files as one retained
artifact. The workflow has read-only repository permissions and contains no
registry credentials or publish step.

Qualification intentionally runs after the binding tags exist. A binding-side
reusable-workflow call cannot pin the later Spec commit that records that
binding's release, so release workflows do not call this gate and repositories
without a release workflow do not need a placeholder caller. Publication remains
separate; a successful qualification run proves the pinned cohort rather than
publishing it.
