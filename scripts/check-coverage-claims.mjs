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
// fixture the binding does not replay in `KNOWN_UNCOVERED`, and the two
// area-scoped bindings additionally restrict the audit to `REQUIRED_AREAS`. So a
// fixture counts as replayed when it is absent from KNOWN_UNCOVERED and — where
// the binding declares one — its area is required. Both halves matter: before
// `#lzcppjsoncodec`, lazily-cpp kept `codec` out of REQUIRED_AREAS entirely,
// which is how a whole area went unreplayed without appearing in any gap list.
//
// Skips are reported, never silent
// --------------------------------
// The bindings are sibling checkouts, so a repo without them can verify
// nothing. That is exactly the shape of failure this guard exists to catch, so
// the skip count is printed on every run, `--check` refuses to report success
// when it verified nothing at all, and `--require-all` (what CI uses, after
// cloning the siblings) refuses to pass on a PARTIAL audit — otherwise a repo
// that silently stopped cloning one binding would keep reporting green for it.

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
};

const SHIPPED = "✅";
const PARTIAL = "~";

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

function loadBinding(dir) {
  const guard = join(ROOT, "..", dir, "scripts", "check-conformance-coverage.sh");
  if (!existsSync(guard)) return null;
  const source = readFileSync(guard, "utf8");
  const requiredLines = bashArray(source, "REQUIRED_AREAS");
  return {
    dir,
    uncovered: quotedEntries(bashArray(source, "KNOWN_UNCOVERED")),
    // `null` means the binding audits the whole corpus rather than a set of
    // required areas — a strictly stronger invariant, so nothing to check.
    requiredAreas: requiredLines === null ? null : bareEntries(requiredLines),
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
  if (binding.requiredAreas !== null) {
    const area = fixtureArea(fixture);
    if (area === null || !binding.requiredAreas.has(area)) return false;
  }
  return true;
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
    if (mark === PARTIAL) qualified += 1;
    if (mark !== SHIPPED) return;
    claims += 1;
    const missing = fixtures.filter((fixture) => !replays(binding, fixture));
    if (missing.length > 0) {
      violations.push(
        `${language} is marked ${SHIPPED} on "${row.feature.slice(0, 60)}…" but ${binding.dir} does ` +
          `not replay ${missing.join(", ")} (declared in its KNOWN_UNCOVERED, or its area is not required)`,
      );
    }
  });
}

const check = process.argv.includes("--check");
console.log(
  `coverage claims: ${claims} shipped mark(s) checked (${qualified} partial mark(s) left unverified by ` +
    `design) across ${rowsWithFixtures} fixture-bearing row(s); ` +
    `${bindings.size}/${Object.keys(BINDING_DIRS).length} binding ledgers read` +
    (skipped.length > 0 ? `, ${skipped.length} skipped (not checked out): ${skipped.join(", ")}` : ""),
);

if (violations.length > 0) {
  console.error("");
  for (const violation of violations) console.error(`✗ ${violation}`);
  console.error(
    `\n${violations.length} unbacked coverage claim(s). Either the binding replays the fixture ` +
      `(delete its KNOWN_UNCOVERED entry) or the mark is wrong — do not "fix" this by deleting the citation.`,
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
