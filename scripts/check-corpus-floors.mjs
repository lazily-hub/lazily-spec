#!/usr/bin/env node
// Corpus-floor guard (#lzcorpusfloorguard).
//
// One idea, two directions: a count something else depends on must move
// DELIBERATELY. Both directions exist because of the same incident.
//
// What happened
// -------------
// `#lzreplayframing` added three steps to an EXISTING fixture,
// `conformance/replay/canonical_encoding_equality.json` (11 -> 14). Nothing in
// ten repositories noticed. `MIN_FIXTURES` counts files and `MIN_SCENARIOS`
// counts declared scenarios; a step is neither, so both stayed green. What each
// binding kept instead was a per-fixture minimum-steps floor hard-coded inside
// its own runner — `steps.len() >= 11`, `drive_encoding_fixture(..., 11)`,
// `minimumSteps: 11`. Eight of nine were still pinned at 11, so the three new
// rows sat inside the slack and would have reported green WITHOUT EXECUTING.
// Only lazily-cs failed loudly, and only because it had written an equality
// (`Assert.Equal(11, steps.GetArrayLength())`) rather than a floor.
//
// A new FIXTURE reddens ten repos and you find out in minutes. A new STEP
// reddens nothing and you find out never.
//
// Direction 1 — the corpus's own step counts (`corpus-counts.json`)
// -----------------------------------------------------------------
// The binding-side answer to the above is to stop hard-coding the number at
// all: a runner asserts it EXECUTED every step it LOADED, which is
// constant-free and can never drift. That closes additions permanently, but it
// gives up the one thing a floor did do — notice the corpus SHRINKING. So the
// shrink is caught here, at the single place it can happen, against a committed
// manifest. Deleting a step is then a two-file change and visible in review;
// today it is invisible everywhere.
//
// Direction 2 — each binding's declared fixture/scenario floors
// -------------------------------------------------------------
// `MIN_FIXTURES` and `MIN_SCENARIOS` are not corpus totals — they are what THAT
// binding opens and replays, which is the corpus minus its own KNOWN_UNCOVERED
// and KNOWN_UNREPLAYED_SCENARIOS. So the corpus CAN derive what each floor
// should be, from the corpus plus that binding's own committed ledger, and did:
// the derivation reproduces all eight declared `MIN_FIXTURES` and all six
// declared `MIN_SCENARIOS` exactly.
//
// Equality, not a floor-on-a-floor. Slack is the failure this guard exists to
// catch — a floor 24 below reality tolerates 24 scenarios silently detaching.
// A floor ABOVE reality fails too: it is unsatisfiable, so the binding's own
// guard is red and this names why in one line instead of nine repos debugging
// it. A binding that declares NO floor for a dimension is reported, never
// failed: lazily-kt deliberately retired `MIN_FIXTURES` in favour of an
// area-partition assertion, and that is a stronger invariant, not a gap.
//
// Skips are reported, never silent — the siblings are separate checkouts, so a
// repo without them verifies nothing. `--require-all` (what CI uses, after
// sparse-cloning `scripts/`) refuses to pass on a partial audit, because a
// clone that silently stopped happening would otherwise keep reporting green.
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const CORPUS = process.env.LAZILY_SPEC_CONFORMANCE_DIR ?? join(ROOT, "conformance");
const COUNTS = join(ROOT, "corpus-counts.json");
const WRITE = process.argv.includes("--write");
const REQUIRE_ALL = process.argv.includes("--require-all");

const BINDINGS = ["rs", "py", "kt", "js", "dart", "zig", "go", "cpp", "cs", "gd"].map(
  (s) => `lazily-${s}`,
);

// Mirrors check-coverage-claims.mjs. An array nobody classified may be a
// narrowing ledger this guard failed to read, and an unread narrowing ledger
// does not weaken the audit visibly — it inverts it for one binding.
const SCOPING_ARRAYS = new Set(["REQUIRED_AREAS", "IMPLEMENTED_FAMILY_PREFIXES", "EXCUSED_AREAS"]);
const NON_SCOPING_ARRAYS = new Set([
  "KNOWN_UNCOVERED",
  "KNOWN_UNREPLAYED_SCENARIOS",
  "SCENARIO_EXCUSES",
  "KNOWN_UNBOUND_BLOCKS",
  "TEST_DIRS",
  "EXTS",
  "CORPUS_ROOT_BASELINE",
]);

function fixtureFiles(dir, base = dir) {
  const out = [];
  for (const entry of readdirSync(dir).sort()) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...fixtureFiles(full, base));
    else if (entry.endsWith(".json")) out.push(full.slice(base.length + 1));
  }
  return out;
}

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
  for (const line of lines ?? []) if (/^[A-Za-z0-9._/-]+$/.test(line)) out.add(line);
  return out;
}

function declaredArrays(source) {
  const out = new Set();
  for (const match of source.matchAll(/^([A-Z][A-Z0-9_]*)=\(/gm)) out.add(match[1]);
  return out;
}

/// A floor constant, in any of the four spellings this family uses: a bash
/// default (`MIN_X="${MIN_X:-150}"`), the same unbraced, the python heredoc's
/// `int(os.environ.get("MIN_X", "166"))`, or the node form
/// `const MIN_X = Number(process.env.MIN_X ?? "157")`.
///
/// Each spelling pins the env var name to the CONSTANT's name on purpose.
/// lazily-dart declares `MIN_FIXTURES = int(os.environ.get("MIN_BLOCK_FIXTURES",
/// "144"))` in a different guard — a different quantity that happens to share a
/// variable name and, today, a value. Matching the env key is what keeps that
/// out.
function floorMatches(source, name) {
  const out = [];
  for (const re of [
    new RegExp(`${name}="\\$\\{${name}:-(\\d+)\\}"`, "g"),
    new RegExp(`${name}=\\$\\{${name}:-(\\d+)\\}`, "g"),
    new RegExp(`${name}\\s*=\\s*int\\(os\\.environ\\.get\\("${name}",\\s*"(\\d+)"\\)\\)`, "g"),
    new RegExp(`${name}\\s*=\\s*Number\\(process\\.env\\.${name}\\s*\\?\\?\\s*"(\\d+)"\\)`, "g"),
  ]) {
    for (const match of source.matchAll(re)) out.push(Number(match[1]));
  }
  return out;
}

/// Where a binding keeps a floor is its own business, so the whole `scripts/`
/// directory is the ledger, not one file in it. lazily-js keeps MIN_FIXTURES in
/// `check-conformance-coverage.sh` and MIN_SCENARIOS in
/// `check-scenario-coverage.mjs`; reading only the first file reported it as
/// declaring no scenario floor, which is a false gap in this guard rather than a
/// gap in that binding. Two different values for one floor is a hard failure —
/// an ambiguous ledger cannot be audited, and picking one silently is how the
/// unread half stops mattering.
function floorValue(files, name) {
  const found = new Map();
  for (const [file, source] of files) {
    for (const value of floorMatches(source, name)) {
      if (!found.has(value)) found.set(value, []);
      found.get(value).push(file);
    }
  }
  if (found.size === 0) return { value: null };
  if (found.size > 1) {
    return {
      value: null,
      conflict: [...found.entries()]
        .map(([value, where]) => `${value} (${where.join(", ")})`)
        .join(" vs "),
    };
  }
  return { value: [...found.keys()][0] };
}

function fixtureArea(fixture) {
  if (fixture.includes("/")) return fixture.slice(0, fixture.indexOf("/"));
  if (fixture === "arena_blob.json" || /^(snapshot|delta)_.*\.json$/.test(fixture)) return "ipc";
  return null;
}

function loadBinding(dir) {
  const scripts = join(ROOT, "..", dir, "scripts");
  const guard = join(scripts, "check-conformance-coverage.sh");
  if (!existsSync(guard)) return null;
  const source = readFileSync(guard, "utf8");
  // Ledger ARRAYS are read from the coverage guard, which is where every
  // binding keeps them. Floor CONSTANTS are read from the whole directory.
  const files = [];
  for (const entry of readdirSync(scripts).sort()) {
    const full = join(scripts, entry);
    if (!statSync(full).isFile()) continue;
    if (!/\.(sh|mjs|js|py)$/.test(entry)) continue;
    files.push([entry, readFileSync(full, "utf8")]);
  }
  const requiredLines = bashArray(source, "REQUIRED_AREAS");
  const familyLines = bashArray(source, "IMPLEMENTED_FAMILY_PREFIXES");
  const excusedScenarios = new Set();
  for (const name of ["KNOWN_UNREPLAYED_SCENARIOS", "SCENARIO_EXCUSES"]) {
    for (const entry of quotedEntries(bashArray(source, name))) {
      const [fixture, scenario] = entry.split("|").map((part) => part.trim());
      if (fixture && scenario) excusedScenarios.add(`${fixture}|${scenario}`);
    }
  }
  return {
    dir,
    uncovered: quotedEntries(bashArray(source, "KNOWN_UNCOVERED")),
    excusedScenarios,
    requiredAreas: requiredLines === null ? null : bareEntries(requiredLines),
    implementedFamilies: familyLines === null ? null : [...quotedEntries(familyLines)],
    minFixtures: floorValue(files, "MIN_FIXTURES"),
    minScenarios: floorValue(files, "MIN_SCENARIOS"),
    unknownArrays: [...declaredArrays(source)].filter(
      (name) => !SCOPING_ARRAYS.has(name) && !NON_SCOPING_ARRAYS.has(name),
    ),
  };
}

function opens(binding, fixture) {
  if (binding.uncovered.has(fixture)) return false;
  if (
    binding.implementedFamilies !== null &&
    !binding.implementedFamilies.some((prefix) => fixture.startsWith(prefix))
  ) {
    return false;
  }
  if (binding.requiredAreas !== null) {
    const area = fixtureArea(fixture);
    if (area === null || !binding.requiredAreas.has(area)) return false;
  }
  return true;
}

// ---- the corpus's own counts -------------------------------------------------

const fixtures = fixtureFiles(CORPUS);
const steps = {};
const scenarios = {};
let problems = 0;

for (const rel of fixtures) {
  let doc;
  try {
    doc = JSON.parse(readFileSync(join(CORPUS, rel), "utf8"));
  } catch (error) {
    console.error(`ERROR: ${rel} is not valid JSON: ${error.message}`);
    problems += 1;
    continue;
  }
  if (doc === null || typeof doc !== "object") continue;
  if (Array.isArray(doc.steps)) steps[rel] = doc.steps.length;
  if (Array.isArray(doc.scenarios)) scenarios[rel] = doc.scenarios.length;
}

// A walk that found nothing reports OK having examined nothing (#lzvacuousrun).
if (fixtures.length === 0) {
  console.error(
    `ERROR: no fixtures found under ${CORPUS}. This guard is vacuously green over an`,
    "\n       empty corpus — the path is wrong, not the corpus.",
  );
  process.exit(1);
}

const observed = { fixtures: fixtures.length, steps, scenarios };

if (WRITE) {
  const { writeFileSync } = await import("node:fs");
  writeFileSync(COUNTS, `${JSON.stringify(observed, null, 2)}\n`);
  console.error(
    `corpus counts written: ${fixtures.length} fixtures, ${Object.keys(steps).length} step-bearing,` +
      ` ${Object.keys(scenarios).length} scenario-bearing`,
  );
  process.exit(0);
}

if (!existsSync(COUNTS)) {
  console.error(`ERROR: ${COUNTS} is missing. Regenerate it with \`make corpus-counts-sync\`.`);
  process.exit(1);
}

const pinned = JSON.parse(readFileSync(COUNTS, "utf8"));

if (pinned.fixtures !== observed.fixtures) {
  console.error(
    `ERROR: the corpus carries ${observed.fixtures} fixtures; corpus-counts.json pins ${pinned.fixtures}.`,
    "\n       Every binding's MIN_FIXTURES is derived from this number. Run",
    "\n       `make corpus-counts-sync` and re-derive the binding floors in the same change.",
  );
  problems += 1;
}

for (const [rel, count] of Object.entries(observed.steps)) {
  const was = pinned.steps?.[rel];
  if (was === undefined) {
    console.error(
      `ERROR: ${rel} carries ${count} steps and is not pinned in corpus-counts.json.`,
      "\n       A new step-bearing fixture must be pinned in the same change that adds it.",
    );
    problems += 1;
  } else if (was !== count) {
    const verb = count < was ? "SHRANK" : "grew";
    console.error(
      `ERROR: ${rel} ${verb} from ${was} to ${count} steps without updating corpus-counts.json.`,
      count < was
        ? "\n       A deleted step is invisible to every binding: a runner asserts it executed" +
            "\n       every step it LOADED, which stays true over a shorter fixture. This manifest" +
            "\n       is the only place a shrink is observable — so it has to be deliberate."
        : "\n       Adding a step is fine; pinning it is the part that makes it reviewable." +
            "\n       Run `make corpus-counts-sync` and commit the result with the fixture.",
    );
    problems += 1;
  }
}

for (const rel of Object.keys(pinned.steps ?? {})) {
  if (observed.steps[rel] === undefined) {
    console.error(
      `ERROR: corpus-counts.json pins ${rel}, which is no longer a step-bearing fixture.`,
      "\n       The pin is stale — delete it in the change that removed the fixture.",
    );
    problems += 1;
  }
}

// ---- each binding's declared floors ------------------------------------------

let audited = 0;
const skipped = [];
const undeclared = [];

for (const dir of BINDINGS) {
  const binding = loadBinding(dir);
  if (binding === null) {
    skipped.push(dir);
    continue;
  }
  audited += 1;

  if (binding.unknownArrays.length > 0) {
    console.error(
      `ERROR: ${dir} declares unclassified ledger array(s): ${binding.unknownArrays.join(", ")}.`,
      "\n       Classify each in check-corpus-floors.mjs: SCOPING_ARRAYS if it narrows which",
      "\n       canonical fixtures the binding opens, NON_SCOPING_ARRAYS otherwise. An unread",
      "\n       narrowing ledger does not weaken this audit visibly; it inverts it for one binding.",
    );
    problems += 1;
    continue;
  }

  const opened = fixtures.filter((rel) => opens(binding, rel));
  const expectedFixtures = opened.length;
  let expectedScenarios = 0;
  for (const rel of opened) {
    const total = scenarios[rel] ?? 0;
    expectedScenarios += total;
  }
  for (const entry of binding.excusedScenarios) {
    const fixture = entry.slice(0, entry.indexOf("|"));
    if (opened.includes(fixture)) expectedScenarios -= 1;
  }

  for (const [name, found, expected] of [
    ["MIN_FIXTURES", binding.minFixtures, expectedFixtures],
    ["MIN_SCENARIOS", binding.minScenarios, expectedScenarios],
  ]) {
    if (found.conflict !== undefined) {
      console.error(
        `ERROR: ${dir} declares ${name} more than once with different values: ${found.conflict}.`,
        "\n       An ambiguous ledger cannot be audited, and choosing one silently is how the",
        "\n       unread half stops mattering. Make them one declaration.",
      );
      problems += 1;
      continue;
    }
    const declared = found.value;
    if (declared === null) {
      undeclared.push(`${dir}:${name}`);
      continue;
    }
    if (declared === expected) continue;
    problems += 1;
    if (declared < expected) {
      console.error(
        `ERROR: ${dir} declares ${name}=${declared}; the corpus plus that binding's own ledger`,
        `\n       says ${expected}. The floor is SLACK by ${expected - declared}, which means it has`,
        "\n       stopped guarding: that many could silently detach and the run would still",
        "\n       report green. Re-pin it to the number the gate itself prints, then prove it",
        `\n       exact by setting ${expected + 1} and watching that binding's guard fail.`,
      );
    } else {
      console.error(
        `ERROR: ${dir} declares ${name}=${declared}, above the ${expected} the corpus plus that`,
        "\n       binding's ledger can produce. The floor is UNSATISFIABLE, so that binding's own",
        "\n       guard is red right now. Either the corpus lost something, or a KNOWN_UNCOVERED",
        "\n       entry was added without lowering the floor it invalidates.",
      );
    }
  }
}

if (audited === 0) {
  console.error(
    "ERROR: no sibling binding ledgers found. This guard verified nothing about the",
    "\n       bindings and must not report success (#lzvacuousrun).",
  );
  process.exit(1);
}

if (skipped.length > 0) {
  console.error(`SKIPPED (no sibling checkout): ${skipped.join(", ")}`);
  if (REQUIRE_ALL) {
    console.error(
      "ERROR: --require-all was passed and the audit is PARTIAL. A clone that silently",
      "\n       stopped happening would otherwise keep reporting green for that binding.",
    );
    process.exit(1);
  }
}

if (undeclared.length > 0) {
  console.error(
    `NOTE: no floor declared for ${undeclared.join(", ")} — reported, not failed.`,
    "\n      lazily-kt retired MIN_FIXTURES for an area-partition assertion, which is a",
    "\n      stronger invariant. A binding with neither is relying on nothing.",
  );
}

if (problems > 0) {
  console.error(`corpus floors FAILED: ${problems} problem(s)`);
  process.exit(1);
}

console.error(
  `corpus floors OK: ${observed.fixtures} fixtures pinned, ${Object.keys(steps).length} step-bearing` +
    ` fixtures pinned exactly, ${audited} binding ledger(s) audited` +
    `${skipped.length > 0 ? `, ${skipped.length} skipped` : ""}` +
    `${undeclared.length > 0 ? `, ${undeclared.length} dimension(s) undeclared` : ""}`,
);
