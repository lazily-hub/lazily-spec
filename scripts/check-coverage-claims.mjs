#!/usr/bin/env node
// Coverage-claim guard: a mark on a wire-bearing row must be backed by a
// fixture the binding actually replays.
//
// `coverage.json` scored having the TYPES, not speaking the WIRE, and could not
// tell the two apart. "IPC wire — Snapshot + Delta + CrdtSync" read shipped for
// C++ for the entire time lazily-cpp could not encode or decode a single one of
// those frames in the json reference codec, and the CrdtSync rows read shipped
// while `distributed/crdt_sync_frames.json` sat in that binding's
// KNOWN_UNCOVERED. A binding earned the mark for defining the structs and
// driving them in-process; nothing tied the mark to a replay. That is the same
// failure the per-fixture ledger exists to prevent, one level up — and it is why
// two lazily-cpp codec gaps survived a family-wide audit.
//
// The rule this enforces
// ----------------------
// A row MAY carry `"fixtures": ["<area>/<file>.json", ...]`. The eight legacy
// root-level Snapshot/Delta/Arena fixtures are classified as area `ipc` without
// changing their canonical paths. When a row carries fixtures:
//
//   ✅  every cited fixture must be replayed by that binding
//   ~   nothing is required — `~` is a VISIBLY qualified mark, and it is the
//       honest place to record "implemented, but not this wire" (lazily-cpp's
//       msgpack codec is precisely that). The mark that misleads a reader is the
//       unqualified one, so that is the one that has to be backed.
//   —   nothing is required
//
// "Replayed" is read from the binding's OWN committed ledger, not from a claim
// in this repo: `scripts/check-conformance-coverage.sh` names every canonical
// fixture the binding does not replay in `KNOWN_UNCOVERED`, and a binding may
// additionally narrow WHICH fixtures its ledger is even about. So a fixture
// counts as replayed when it is absent from KNOWN_UNCOVERED and inside every
// scope the binding declares. Both halves matter: before `#lzcppjsoncodec`,
// lazily-cpp kept `codec` out of REQUIRED_AREAS entirely, which is how a whole
// area went unreplayed without appearing in any gap list.
//
// Two scoping ledgers exist, and reading only one is unsound
// ----------------------------------------------------------
// `REQUIRED_AREAS` (kt, cpp) names the top-level areas the audit covers.
// `IMPLEMENTED_FAMILY_PREFIXES` (gd) names the fixture-path prefixes the binding
// CLAIMS, excusing everything outside them automatically so the list does not
// rot as the corpus grows. They are the same idea at different granularity, and
// a binding declaring neither audits the whole corpus — a strictly stronger
// invariant.
//
// Reading only `REQUIRED_AREAS` is exactly the bug this section exists to
// record. lazily-gd entered staged, replaying 9 of 21 `reactive-graph` fixtures
// and excusing 128 others BY FAMILY rather than naming each one. To a parser
// that knows only KNOWN_UNCOVERED and REQUIRED_AREAS, that binding reads as
// "audits the whole corpus, declares 12 gaps" — so all 128 family-excused
// fixtures counted as replayed, and a shipped mark on any of them would have
// passed. The unread ledger did not make the claim guard weaker in a visible
// way; it silently inverted it for one binding.
//
// So an unrecognized scoping array is a HARD FAILURE, not a shrug: see
// SCOPING_ARRAYS / NON_SCOPING_ARRAYS below. The next binding that invents a
// third narrowing mechanism must be classified here before its marks are
// trusted, because the failure mode of ignoring one is a green audit over
// fixtures nobody replays.
//
// Skips are reported, never silent
// --------------------------------
// The bindings are sibling checkouts, so a repo without them can verify
// nothing. That is exactly the shape of failure this guard exists to catch, so
// the skip count is printed on every run, `--check` refuses to report success
// when it verified nothing at all, and `--require-all` (what CI uses, after
// cloning the siblings) refuses to pass on a PARTIAL audit — otherwise a repo
// that silently stopped cloning one binding would keep reporting green for it.
//
// The other direction: a `~` nobody revisits (#lzcoverageunderclaim)
// ------------------------------------------------------------------
// Everything above guards OVER-claiming. Nothing guarded a binding that sat at
// `~` after it had EARNED the row, and that is not hypothetical: lazily-cs
// finished `collections/registers_convergence.json` and its row kept reading `~`
// until a hand-written backlog note caught it, because a partial mark requires
// nothing and so is never re-examined.
//
// This does NOT become a hard failure, and the reason is written into the rule
// above: `~` requires nothing BY DESIGN — it is the honest place to record
// "implemented, but not this wire", where the shortfall is in a dimension the
// cited fixtures do not pin. A row's `fixtures` list is not a complete
// specification of its feature, so "replays every cited fixture" does not imply
// "shipped", and failing on it would punish the exact honesty `~` exists to
// permit.
//
// What it CAN say soundly is narrower and still useful: this mark is now
// INDISTINGUISHABLE FROM SHIPPED on ledger evidence alone. Deciding it needs
// binding-specific evidence a spec-side guard does not have, so these print as
// review candidates on every run rather than passing silently into the
// "unverified by design" bucket. That turns 28 marks nobody looks at into a
// short list somebody can.
//
// One limit worth stating: the finer-grained gap ledgers
// (KNOWN_UNREPLAYED_SCENARIOS / SCENARIO_EXCUSES / KNOWN_UNBOUND_BLOCKS) are
// declared empty in all ten bindings and populated at RUNTIME by
// `excuse_scenario`, so a static read cannot see a scenario-level excuse. They
// are read anyway, so a binding that starts listing entries statically narrows
// this report instead of silently widening it. Today no binding has a single
// excuse call site, which is why a replayed fixture here has nothing finer
// standing behind its `~`.

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");

// coverage.json column label -> sibling checkout directory.
const BINDING_DIRS = {
  Rust: "lazily-rs",
  Python: "lazily-py",
  Kotlin: "lazily-kt",
  JS: "lazily-js",
  Dart: "lazily-dart",
  Zig: "lazily-zig",
  Go: "lazily-go",
  "C++": "lazily-cpp",
  "C#": "lazily-cs",
  GDScript: "lazily-gd",
};

const SHIPPED = "✅";
const PARTIAL = "~";

// Arrays that NARROW which canonical fixtures a binding's ledger speaks for.
// Every one of these must be read, or the fixtures it excludes silently count as
// replayed (see the header). Adding a binding that declares a new one is a
// change to this file, not just to that binding.
const SCOPING_ARRAYS = new Set(["REQUIRED_AREAS", "IMPLEMENTED_FAMILY_PREFIXES"]);

// Arrays that exist in these guards for reasons unrelated to WHICH canonical
// fixture files the binding replays: gap ledgers at a finer grain than the
// fixture (scenarios, assertion blocks) and file-discovery mechanics. Listed
// explicitly so the unknown-array check below stays fail-closed — an
// unclassified array is treated as a possible scoping ledger nobody read.
const NON_SCOPING_ARRAYS = new Set([
  "KNOWN_UNCOVERED", // the gap ledger itself, read directly
  "KNOWN_UNREPLAYED_SCENARIOS", // scenario-level gaps inside a replayed fixture
  "SCENARIO_EXCUSES", // same, older spelling
  "KNOWN_UNBOUND_BLOCKS", // assertion-block-level gaps
  "TEST_DIRS", // where the guard looks for test sources
  "EXTS", // which extensions count as test sources
]);

/// Extract a bash array literal's entries, skipping comment lines.
///
/// The arrays are hand-maintained ledgers with a reason comment above most
/// entries, and those comments quote wire fragments (`{"type": 0}`), so a naive
/// scan for quoted strings picks up `type` and `value` as if they were fixtures.
/// Comment lines are dropped before anything is read out of them.
function bashArray(source, name) {
  const open = source.indexOf(`\n${name}=(`);
  if (open === -1) return null;
  const rest = source.slice(open + name.length + 3);
  const close = rest.search(/\n\)/);
  if (close === -1) return null;
  return rest
    .slice(0, close)
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("#"));
}

function quotedEntries(lines) {
  const out = new Set();
  for (const line of lines ?? []) {
    const match = /^"([^"]+)"$/.exec(line);
    if (match) out.add(match[1]);
  }
  return out;
}

function bareEntries(lines) {
  const out = new Set();
  for (const line of lines ?? []) {
    if (/^[A-Za-z0-9._/-]+$/.test(line)) out.add(line);
  }
  return out;
}

/// Every top-level bash array a guard declares, by name.
///
/// `^` anchored so a local assignment inside a function body is not mistaken for
/// a ledger, and uppercase-only because every ledger in this family is a
/// SCREAMING_CASE constant while the loop counters are not.
function declaredArrays(source) {
  const out = new Set();
  for (const match of source.matchAll(/^([A-Z][A-Z0-9_]*)=\(/gm)) out.add(match[1]);
  return out;
}

function loadBinding(dir) {
  const guard = join(ROOT, "..", dir, "scripts", "check-conformance-coverage.sh");
  if (!existsSync(guard)) return null;
  const source = readFileSync(guard, "utf8");
  const requiredLines = bashArray(source, "REQUIRED_AREAS");
  const familyLines = bashArray(source, "IMPLEMENTED_FAMILY_PREFIXES");
  // Finer-grained gap ledgers: a scenario or assertion block excused INSIDE a
  // fixture the binding does replay. Any entry here is a standing reason for a
  // `~`, so it removes that row from the review report below. Declared empty in
  // every binding today and appended to at runtime, so this read narrows the
  // report when a binding starts listing them and never widens it.
  const finerGaps = new Set();
  for (const name of ["KNOWN_UNREPLAYED_SCENARIOS", "SCENARIO_EXCUSES", "KNOWN_UNBOUND_BLOCKS"]) {
    for (const entry of quotedEntries(bashArray(source, name))) {
      // Entries are `corpus/fixture.json|scenario-id|reason`; the fixture is the
      // only part that joins back to a coverage row.
      finerGaps.add(entry.split("|")[0].trim());
    }
  }
  return {
    dir,
    uncovered: quotedEntries(bashArray(source, "KNOWN_UNCOVERED")),
    finerGaps,
    // `null` means the binding audits the whole corpus rather than a set of
    // required areas — a strictly stronger invariant, so nothing to check.
    requiredAreas: requiredLines === null ? null : bareEntries(requiredLines),
    // Same contract one level finer: fixture-path prefixes the binding claims.
    // `null` = claims the whole corpus.
    implementedFamilies:
      familyLines === null ? null : [...quotedEntries(familyLines)],
    unknownArrays: [...declaredArrays(source)].filter(
      (name) => !SCOPING_ARRAYS.has(name) && !NON_SCOPING_ARRAYS.has(name),
    ),
  };
}

function fixtureArea(fixture) {
  if (fixture.includes("/")) return fixture.slice(0, fixture.indexOf("/"));
  if (
    fixture === "arena_blob.json" ||
    /^snapshot_.*\.json$/.test(fixture) ||
    /^delta_.*\.json$/.test(fixture)
  ) {
    return "ipc";
  }
  return null;
}

function replays(binding, fixture) {
  if (binding.uncovered.has(fixture)) return false;
  if (binding.implementedFamilies !== null) {
    // Outside every family the binding claims. Its own guard excuses this
    // fixture silently and by design, which means it is NOT replayed — the
    // opposite of what absence from KNOWN_UNCOVERED would otherwise imply.
    if (!binding.implementedFamilies.some((prefix) => fixture.startsWith(prefix))) {
      return false;
    }
  }
  if (binding.requiredAreas !== null) {
    const area = fixtureArea(fixture);
    if (area === null || !binding.requiredAreas.has(area)) return false;
  }
  return true;
}

/// Which ledger excluded this fixture. Three different edits fix the three
/// cases, so naming "not replayed" without naming the reason sends the reader
/// to the wrong file.
function whyNotReplayed(binding, fixture) {
  if (binding.uncovered.has(fixture)) return "named in its KNOWN_UNCOVERED";
  if (
    binding.implementedFamilies !== null &&
    !binding.implementedFamilies.some((prefix) => fixture.startsWith(prefix))
  ) {
    return `outside its IMPLEMENTED_FAMILY_PREFIXES (${binding.implementedFamilies.join(", ")})`;
  }
  if (binding.requiredAreas !== null) {
    return `its area is not in REQUIRED_AREAS (${[...binding.requiredAreas].join(", ")})`;
  }
  return "reason unresolved — this is a guard bug";
}

const data = JSON.parse(readFileSync(join(ROOT, "coverage.json"), "utf8"));
const bindings = new Map();
const skipped = [];
for (const [language, dir] of Object.entries(BINDING_DIRS)) {
  const loaded = loadBinding(dir);
  if (loaded === null) skipped.push(dir);
  else bindings.set(language, loaded);
}

const violations = [];
// Partial marks a reader should re-examine. Reported, never fatal — see the
// `#lzcoverageunderclaim` section of the header for why this cannot be a gate.
const reviewCandidates = [];

// Fail closed on a ledger nobody classified. An unread scoping array does not
// weaken the audit visibly — it inverts it for that binding, which is how
// lazily-gd's 128 family-excused fixtures would have read as replayed.
for (const [language, binding] of bindings) {
  for (const name of binding.unknownArrays) {
    violations.push(
      `${binding.dir} declares an unrecognized ledger array \`${name}\` (${language} column). ` +
        `Classify it in check-coverage-claims.mjs: SCOPING_ARRAYS if it narrows which canonical ` +
        `fixtures the guard audits, NON_SCOPING_ARRAYS otherwise. An unread scoping ledger makes ` +
        `every fixture it excludes count as replayed`,
    );
  }
}

let claims = 0;
let qualified = 0;
let rowsWithFixtures = 0;

for (const row of data.rows) {
  const fixtures = row.fixtures;
  if (!Array.isArray(fixtures) || fixtures.length === 0) continue;
  rowsWithFixtures += 1;
  for (const fixture of fixtures) {
    if (!existsSync(join(ROOT, "conformance", fixture))) {
      violations.push(
        `row "${row.feature.slice(0, 60)}…" cites ${fixture}, which is not in the canonical corpus`,
      );
    }
  }
  data.languages.forEach((language, column) => {
    const binding = bindings.get(language);
    if (binding === undefined) return; // not checked out, or not a binding column
    const mark = row.marks[column];
    if (mark === PARTIAL) {
      qualified += 1;
      // Indistinguishable from shipped on ledger evidence: every cited fixture
      // is replayed and nothing finer is excused inside any of them. Not a
      // violation — see the header — but the only partial marks worth a look.
      if (
        fixtures.every((fixture) => replays(binding, fixture)) &&
        !fixtures.some((fixture) => binding.finerGaps.has(fixture))
      ) {
        reviewCandidates.push(
          `${language} is ${PARTIAL} on "${row.feature.slice(0, 60)}…" (row ${row.id}) but ${binding.dir} ` +
            `replays every fixture it cites (${fixtures.join(", ")}) with no scenario- or block-level ` +
            `excuse — either it has outgrown the mark, or the shortfall is real and not pinned by ` +
            `these fixtures`,
        );
      }
    }
    if (mark !== SHIPPED) return;
    claims += 1;
    const missing = fixtures.filter((fixture) => !replays(binding, fixture));
    if (missing.length > 0) {
      violations.push(
        `${language} is marked ${SHIPPED} on "${row.feature.slice(0, 60)}…" but ${binding.dir} does ` +
          `not replay ${missing.map((f) => `${f} [${whyNotReplayed(binding, f)}]`).join(", ")}`,
      );
    }
  });
}

const check = process.argv.includes("--check");
console.log(
  `coverage claims: ${claims} shipped mark(s) checked (${qualified} partial mark(s) left unverified by ` +
    `design, ${reviewCandidates.length} of them indistinguishable from shipped) across ` +
    `${rowsWithFixtures} fixture-bearing row(s); ` +
    `${bindings.size}/${Object.keys(BINDING_DIRS).length} binding ledgers read` +
    (skipped.length > 0 ? `, ${skipped.length} skipped (not checked out): ${skipped.join(", ")}` : ""),
);

// Printed on every run, including a green one: the whole failure this addresses
// is a mark nobody revisits, and a report that only surfaces on failure would
// never surface at all.
if (reviewCandidates.length > 0) {
  console.log("");
  for (const candidate of reviewCandidates) console.log(`· ${candidate}`);
  console.log(
    `\n${reviewCandidates.length} partial mark(s) to re-examine. NOT a failure: \`~\` requires nothing ` +
      `by design and is the honest record for a shortfall these fixtures do not pin. Resolve each by ` +
      `checking the binding, then either promote the mark (and re-run sync-coverage.mjs — a row flip ` +
      `can carry its family roll-up cell with it) or cite a fixture that does pin the gap.`,
  );
}

if (violations.length > 0) {
  console.error("");
  for (const violation of violations) console.error(`✗ ${violation}`);
  console.error(
    `\n${violations.length} coverage-claim problem(s). For an unbacked mark: either the binding ` +
      `replays the fixture (delete its KNOWN_UNCOVERED entry, or widen the family/area ledger the ` +
      `message names) or the mark is wrong — do not "fix" this by deleting the citation.`,
  );
  process.exit(1);
}

if (process.argv.includes("--require-all") && skipped.length > 0) {
  console.error(
    `\n${skipped.length} binding ledger(s) were not readable (${skipped.join(", ")}), so their marks ` +
      `went unverified. --require-all refuses a partial audit: a silently missing checkout reports ` +
      `green for every claim it did not read.`,
  );
  process.exit(1);
}

if (check && bindings.size === 0) {
  console.error(
    "\nNo binding ledgers were readable, so nothing was verified. Reporting success here would be " +
      "the same silent pass this guard exists to remove — run it from a checkout that has the siblings.",
  );
  process.exit(1);
}

console.log("coverage claims OK");
