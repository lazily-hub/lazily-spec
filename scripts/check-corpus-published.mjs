#!/usr/bin/env node
// Corpus-publication advisory (#lzspecpushbeforebindings).
//
// Local verification resolves the corpus through the SIBLING WORKING TREE
// (`../lazily-spec/conformance/...`), so a binding sees a fixture change the
// moment it is saved. Every binding's CI instead CLONES PUBLISHED `main`. A
// corpus change can therefore be green in nine local checkouts and invisible to
// all nine CI runs, and any binding pinning a scenario or fixture count fails on
// the mismatch.
//
// That happened landing the SeqCrdt fork-clock scenarios: lazily-cs went red
// with `Expected: 8 / Actual: 6` (its census counted the working tree while CI
// replayed published main), and lazily-cpp had to pin MIN_SCENARIOS to the
// published 144 rather than the local 146, then raise it in a second commit.
//
// WHY THIS ADVISES RATHER THAN FAILS. A corpus that differs from `origin/main`
// is the NORMAL state while a fixture change is being developed — that is what
// authoring one looks like. Failing here would gate the ordinary workflow to
// catch a mistake made in a different repo. What this can do honestly is fire at
// the exact moment the rule becomes relevant, name the fixtures, and say what
// CI will see. The gate that could fail closed does not live here: it would have
// to live in each binding, and there too an unpublished corpus is a legitimate
// local state.
//
// Exit status is 0 unless git itself cannot answer, which is reported as a skip
// rather than a pass — an advisory that silently degrades to "fine" is worse
// than no advisory.

import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REMOTE_REF = process.env.LAZILY_SPEC_PUBLISHED_REF ?? "origin/main";

function git(args) {
  return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
}

function tryGit(args) {
  try {
    return { ok: true, out: git(args) };
  } catch (error) {
    return { ok: false, out: String(error?.stderr ?? error?.message ?? error).trim() };
  }
}

function skip(reason) {
  // A skip is not a pass. Say so, and say why, so a run that could not evaluate
  // the rule is never mistaken for one that evaluated it and found nothing.
  console.log(`corpus publication: SKIPPED — ${reason}`);
  console.log("  (this run did NOT establish that the corpus is published)");
  process.exit(0);
}

const resolved = tryGit(["rev-parse", "--verify", "--quiet", `${REMOTE_REF}^{commit}`]);
if (!resolved.ok || resolved.out === "") {
  skip(`\`${REMOTE_REF}\` is not resolvable here (no remote-tracking ref? run \`git fetch\`)`);
}

// THREE independent ways the working tree can be ahead of what CI clones, and
// they need different advice: work that is not committed, work that is committed
// but not pushed, and a file git has never seen. All three are invisible to a
// clone of `main`.
//
// The untracked leg is not an afterthought — it is the MOST dangerous of the
// three and the easiest to omit, because `git diff` does not report untracked
// files at all. A brand-new fixture is exactly the change most likely to redden
// a binding (it moves fixture counts, scenario counts and coverage floors at
// once), and without this leg the advisory reported a clean "OK" over it. That
// false OK was caught by exercising this branch rather than by reading the code.
const uncommitted = tryGit(["diff", "--name-only", "HEAD", "--", "conformance"]);
const unpushed = tryGit(["diff", "--name-only", `${REMOTE_REF}...HEAD`, "--", "conformance"]);
const untracked = tryGit(["ls-files", "--others", "--exclude-standard", "--", "conformance"]);
if (!uncommitted.ok || !unpushed.ok || !untracked.ok) {
  skip("git could not enumerate `conformance/` against HEAD, the published ref, or the index");
}

const split = (out) => (out === "" ? [] : out.split("\n").filter(Boolean));
const uncommittedPaths = split(uncommitted.out);
const unpushedPaths = split(unpushed.out);
const untrackedPaths = split(untracked.out);
const drifted = [...new Set([...uncommittedPaths, ...unpushedPaths, ...untrackedPaths])].sort();

if (drifted.length === 0) {
  console.log(`corpus publication OK: \`conformance/\` matches ${REMOTE_REF} — CI's clone sees what you verified`);
  process.exit(0);
}

console.log(
  `corpus publication: ${drifted.length} fixture path(s) in \`conformance/\` are AHEAD of ${REMOTE_REF}`,
);
for (const path of drifted) {
  const state = untrackedPaths.includes(path)
    ? "UNTRACKED — git has never seen this file"
    : uncommittedPaths.includes(path)
      ? unpushedPaths.includes(path)
        ? "uncommitted + unpushed commits"
        : "uncommitted"
      : "committed, not pushed";
  console.log(`  · ${path} (${state})`);
}
console.log("");
console.log("  Bindings verify against this WORKING TREE; their CI clones published");
console.log(`  ${REMOTE_REF}. Until these are pushed, every binding's CI replays the OLD`);
console.log("  corpus, and any binding pinning a scenario or fixture count will fail on");
console.log("  the mismatch (#lzspecpushbeforebindings).");
console.log("");
console.log("  Push lazily-spec FIRST, then verify and push the bindings. A count or");
console.log("  floor in a binding must describe what CI's clone guarantees, never what");
console.log("  your working tree happens to hold.");
console.log("  See docs/conformance.md § Publishing a corpus change.");
process.exit(0);
