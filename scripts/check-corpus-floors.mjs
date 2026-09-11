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
// Direction 3 — assertion-block SITES (`#lzblockfloorpin`)
// -------------------------------------------------------
// The array pin catches a deleted `steps` row. It does not catch a deleted
// `expect` block inside a row that stays, and four bindings were guarding that
// dimension with the same kind of hand-typed constant `#lzcorpusfloorguard` just
// retired for steps: lazily-cs `MIN_BLOCKS=743`, lazily-js `638`, lazily-py
// `MIN_DECLARED_BLOCKS=620`, lazily-zig `31`. cs's own comment is the proof they
// drift — "Re-pinned from 740 for lazily-spec 4010d99 (#lzreplayframing), which
// grew canonical_encoding_equality.json from 11 steps to 14".
//
// So block sites are pinned here too, per fixture and per block-name bucket, and
// the number each binding needs is DERIVED: `--report-blocks` prints, for every
// binding, the sites and distinct digests the corpus plus that binding's own
// ledger produce. Three of the four typed constants come back to the unit
// (cs 743 sites, py 620 digests, js 638 digests) — which is what makes them
// removable. lazily-zig's 31 does not, and that is the finding rather than a
// derivation failure: 31 is the count its NARROW pre-`#lzunboundblockguard`
// walk produced, the same 31 lazily-py sat at before widening to 578, so zig is
// inventorying 31 of the 716 blocks its opened fixtures carry.
//
// The rule varies on exactly two axes, which is why the report has three rows
// rather than one number: the block-name set (three spellings, or five including
// `expect_initial`/`expect_after`), and whether an ARRAY-valued block counts each
// element as a site of its own.
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
/// Prints, per binding, the assertion-block population the corpus plus that
/// binding's own ledger produces — the number its guard should DERIVE rather
/// than type (#lzblockfloorpin). Four rows because a binding's walk differs in
/// exactly two ways, the block-name set and whether an array-valued block counts
/// its elements, and a binding needs the row that matches its own walk.
const REPORT_BLOCKS = process.argv.includes("--report-blocks");

const BINDINGS = ["rs", "py", "kt", "js", "dart", "zig", "go", "cpp", "cs", "gd"].map(
  (s) => `lazily-${s}`,
);

// Mirrors check-coverage-claims.mjs. An array nobody classified may be a
// narrowing ledger this guard failed to read, and an unread narrowing ledger
// does not weaken the audit visibly — it inverts it for one binding.
const SCOPING_ARRAYS = new Set(["REQUIRED_AREAS", "IMPLEMENTED_FAMILY_PREFIXES", "EXCUSED_AREAS"]);

/// Every spelling the corpus uses for an executable output claim, as the UNION
/// of what the bindings track — not the narrower set `gen_assertion_block_schema.py`
/// routes. The pin has to be maximal or the difference is exactly the dimension
/// that goes unguarded: `collections/semtree_incremental.json` carries six
/// `expect_initial` / `expect_after` blocks that lazily-py and lazily-js
/// inventory and the generated schema does not route at all, so a three-name pin
/// would leave those six deletable in silence.
const BLOCK_NAMES = new Set(["assertions", "expect", "expect_after", "expect_initial", "expected"]);
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

const isPlainObject = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);

/// Canonical (key-sorted, separator-free) JSON, so a block is keyed by what it
/// SAYS. lazily-py digests `json.dumps(sort_keys=True, separators=(",", ":"))`
/// and lazily-js `JSON.stringify`; the two agree on every block in the corpus
/// today, and sorting here means a fixture that reorders a block's keys does not
/// read as a new one on one side and the same one on the other.
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (isPlainObject(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/// Every assertion-block SITE a fixture carries, as `[bucket, canonical bytes]`.
///
/// A block spelled as an OBJECT is one site, bucketed under its own name. A
/// block spelled as an ARRAY of objects is one site PER ELEMENT, bucketed under
/// `name[]` — `steps[].expect` in `signaling/anti_spoof_session.json` is a list
/// of eight expected emissions, and lazily-js instruments each element as a
/// block in its own right while lazily-cs's object-only walk sees none of them.
/// Keeping the two buckets apart is what lets a binding derive its own number
/// from this pin instead of one that happens to be eight too high.
///
/// The walk descends INTO a block as well as past it. No block in the corpus
/// nests another today, so this changes no count — it is here so that the first
/// one to do so is pinned by the change that adds it rather than by the change
/// that later notices.
function blockSites(doc) {
  const out = [];
  const walk = (node) => {
    if (Array.isArray(node)) {
      for (const child of node) walk(child);
      return;
    }
    if (!isPlainObject(node)) return;
    for (const [key, value] of Object.entries(node)) {
      if (BLOCK_NAMES.has(key)) {
        if (isPlainObject(value)) out.push([key, canonical(value)]);
        else if (Array.isArray(value)) {
          for (const item of value) if (isPlainObject(item)) out.push([`${key}[]`, canonical(item)]);
        }
      }
      walk(value);
    }
  };
  walk(doc);
  return out;
}

function bashArray(source, name) {
  const open = source.indexOf(`\n${name}=(`);
  if (open === -1) return null;
  const rest = source.slice(open + name.length + 3);
  // `NAME=()` on ONE line is an empty array, not the opening of a multi-line
  // one. Scanning straight on for the next `\n)` hands back the close of
  // whichever array comes next and reads every entry in between as this array's
  // — which is exactly how 25 `KNOWN_UNBOUND_BLOCKS` entries in lazily-zig read
  // as 25 `SCENARIO_EXCUSES` and silently subtracted 25 from its derived
  // scenario count, turning an honest `MIN_SCENARIOS=151` into an
  // "UNSATISFIABLE" floor. lazily-cpp and lazily-dart carry the same shape.
  const firstNewline = rest.indexOf("\n");
  const head = firstNewline === -1 ? rest : rest.slice(0, firstNewline);
  const closesOnOpeningLine = head.indexOf(")");
  if (closesOnOpeningLine !== -1) {
    if (head.slice(0, closesOnOpeningLine).trim().length > 0) {
      throw new Error(
        `${name} opens and closes on one line with entries on it; this parser reads ` +
          "multi-line arrays and an empty `NAME=()`. Split it across lines rather " +
          "than letting it be mis-parsed.",
      );
    }
    return [];
  }
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
    // `REQUIRED_AREAS` alone names the areas the AUDIT covers, which is not the
    // same set as the fixtures the SUITE opens: lazily-kt requires 27 areas and
    // opens 148 fixtures / 157 scenarios, where deriving from the area list
    // alone gives 147 / 151. lazily-cpp pairs it with `EXCUSED_AREAS`, whose own
    // guard enforces that the two are an exact complement — and there the
    // derivation lands on the nose. So the complement is what makes an area
    // scope derivable, and without it this guard must decline to state a number
    // rather than state a wrong one.
    areaScopeIsPartition: requiredLines === null || bashArray(source, "EXCUSED_AREAS") !== null,
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
const arrays = {};
const blocks = {};
/// fixture -> [canonical block bytes], for the per-binding derivation below.
const blockBytes = {};
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
  // EVERY top-level array, not an enumerated subset. `steps` and `scenarios`
  // are the two a runner floor usually counted, but lazily-dart's stdlib runner
  // counts `mutations`, and the corpus also carries `frames`, `reads`,
  // `rejects`, `cases`, `initial_actions` and `initial_active`. Enumerating the
  // keys would leave each new one unpinned for exactly as long as nobody
  // noticed — which is the failure this guard exists to end.
  const keys = {};
  for (const [key, value] of Object.entries(doc)) {
    if (Array.isArray(value)) keys[key] = value.length;
  }
  if (Object.keys(keys).length > 0) arrays[rel] = keys;
  if (Array.isArray(doc.steps)) steps[rel] = doc.steps.length;
  if (Array.isArray(doc.scenarios)) scenarios[rel] = doc.scenarios.length;

  // Assertion-block SITES (#lzblockfloorpin). The array pin above catches a
  // deleted `steps` row; it does not catch a deleted `expect` block inside a row
  // that stays, and four bindings were guarding that dimension with a
  // hand-maintained constant instead — lazily-cs `MIN_BLOCKS=743`, lazily-js
  // `638`, lazily-py `MIN_DECLARED_BLOCKS=620`, lazily-zig `31`. cs's own
  // comment was the proof the constant drifts: "Re-pinned from 740 for
  // lazily-spec 4010d99 (#lzreplayframing), which grew
  // canonical_encoding_equality.json from 11 steps to 14". Each of those
  // numbers is reproduced EXACTLY by this walk over that binding's opened set,
  // so the number belongs here, derived, and not typed there.
  const sites = blockSites(doc);
  if (sites.length > 0) {
    const buckets = {};
    for (const [bucket] of sites) buckets[bucket] = (buckets[bucket] ?? 0) + 1;
    blocks[rel] = buckets;
    blockBytes[rel] = sites;
  }
}

// A walk that found nothing reports OK having examined nothing (#lzvacuousrun).
if (fixtures.length === 0) {
  console.error(
    `ERROR: no fixtures found under ${CORPUS}. This guard is vacuously green over an`,
    "\n       empty corpus — the path is wrong, not the corpus.",
  );
  process.exit(1);
}

const observed = { fixtures: fixtures.length, arrays, blocks };
const blockSiteTotal = Object.values(blocks).reduce(
  (n, buckets) => n + Object.values(buckets).reduce((m, count) => m + count, 0),
  0,
);

if (WRITE) {
  const { writeFileSync } = await import("node:fs");
  writeFileSync(COUNTS, `${JSON.stringify(observed, null, 2)}\n`);
  const cells = Object.values(arrays).reduce((n, keys) => n + Object.keys(keys).length, 0);
  console.error(
    `corpus counts written: ${fixtures.length} fixtures, ${cells} array length(s) across` +
      ` ${Object.keys(arrays).length} fixture(s), ${blockSiteTotal} assertion-block site(s)` +
      ` across ${Object.keys(blocks).length} fixture(s)`,
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

/// The array pin and the assertion-block pin are the same contract over two
/// quantities, so they are compared by one routine: a new cell must be pinned by
/// the change that adds it, a changed cell must be re-pinned deliberately, and a
/// pin the corpus no longer backs is stale. Only the sentence explaining WHY a
/// shrink matters differs, because the two dimensions go invisible for different
/// reasons.
function comparePins(section, noun, shrinkAdvice) {
  for (const [rel, cells] of Object.entries(observed[section])) {
    for (const [key, count] of Object.entries(cells)) {
      const was = pinned[section]?.[rel]?.[key];
      if (was === undefined) {
        console.error(
          `ERROR: ${rel} carries ${count} \`${key}\` and is not pinned in corpus-counts.json.`,
          `\n       A new counted ${noun} must be pinned in the same change that adds it.`,
        );
        problems += 1;
      } else if (was !== count) {
        const verb = count < was ? "SHRANK" : "grew";
        console.error(
          `ERROR: ${rel} \`${key}\` ${verb} from ${was} to ${count} without updating corpus-counts.json.`,
          count < was
            ? shrinkAdvice
            : "\n       Adding one is fine; pinning it is the part that makes it reviewable." +
                "\n       Run `make corpus-counts-sync` and commit the result with the fixture.",
        );
        problems += 1;
      }
    }
  }

  for (const [rel, cells] of Object.entries(pinned[section] ?? {})) {
    for (const key of Object.keys(cells)) {
      if (observed[section][rel]?.[key] === undefined) {
        console.error(
          `ERROR: corpus-counts.json pins ${rel} \`${key}\` (${noun}), which the corpus no longer carries.`,
          "\n       The pin is stale — delete it in the change that removed it.",
        );
        problems += 1;
      }
    }
  }
}

comparePins(
  "arrays",
  "array",
  "\n       A deleted entry is invisible to every binding: a runner asserts it executed" +
    "\n       every entry it LOADED, which stays true over a shorter fixture. This manifest" +
    "\n       is the only place a shrink is observable — so it has to be deliberate.",
);

comparePins(
  "blocks",
  "assertion-block site",
  "\n       A deleted assertion block is invisible in BOTH directions: the unbound-block" +
    "\n       rung compares what a run declared against what it bound, and a block that is" +
    "\n       gone is neither. The four bindings that floored this dimension now derive the" +
    "\n       number from the corpus, so a shrink lands as a derived expectation dropping in" +
    "\n       lockstep and reports nothing at all. This manifest is where it becomes visible.",
);

// A pin section the manifest predates is not "no problems found" — it is the
// whole dimension unguarded, reported as OK. The `blocks` section arrived after
// `arrays`, so an un-regenerated manifest has to say so rather than pass.
if (pinned.blocks === undefined && Object.keys(blocks).length > 0) {
  console.error(
    "ERROR: corpus-counts.json pins no `blocks` section, but the corpus carries",
    `\n       ${blockSiteTotal} assertion-block site(s). The manifest predates the block pin`,
    "\n       (#lzblockfloorpin). Run `make corpus-counts-sync` and commit the result.",
  );
  problems += 1;
}

// ---- each binding's declared floors ------------------------------------------

let audited = 0;
const skipped = [];
const undeclared = [];
const nonDerivable = [];
const blockReport = [];

/// The two axes a binding's assertion-block walk varies on. `lazily-cs` reads
/// three names and object-valued blocks only (743 sites); `lazily-py` reads five
/// names, object-valued only, and floors on distinct digests (620); `lazily-js`
/// reads five names AND each plain-object element of an array-valued block, also
/// by digest (638). All three land on the nose from this derivation, which is
/// what makes the typed constants removable.
const NARROW_BLOCK_NAMES = new Set(["assertions", "expect", "expected"]);
const BLOCK_RULES = [
  ["assertions|expect|expected, objects only", (bucket) => NARROW_BLOCK_NAMES.has(bucket)],
  ["all five names, objects only", (bucket) => !bucket.endsWith("[]")],
  ["all five names, + array elements", () => true],
];

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
  if (REPORT_BLOCKS) blockReport.push([dir, opened]);
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

  // See `areaScopeIsPartition`: an area list with no enforced complement makes
  // the opened set a lower bound, not a number, so comparing against it would
  // manufacture a false failure the moment that binding declared a floor.
  if (!binding.areaScopeIsPartition) {
    nonDerivable.push(dir);
    continue;
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

if (REPORT_BLOCKS) {
  console.error("assertion-block population, derived from the corpus plus each binding's ledger:");
  for (const [dir, opened] of blockReport) {
    console.error(`  ${dir} (${opened.length} fixtures opened)`);
    for (const [label, keep] of BLOCK_RULES) {
      let sites = 0;
      const digests = new Set();
      for (const rel of opened) {
        for (const [bucket, bytes] of blockBytes[rel] ?? []) {
          if (!keep(bucket)) continue;
          sites += 1;
          digests.add(bytes);
        }
      }
      console.error(`    ${label.padEnd(42)} sites=${sites} distinct-digests=${digests.size}`);
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

if (nonDerivable.length > 0) {
  console.error(
    `NOTE: no floor derived for ${nonDerivable.join(", ")} — REQUIRED_AREAS with no enforced`,
    "\n      EXCUSED_AREAS complement scopes the AUDIT, not the set the suite OPENS, so the",
    "\n      opened count is a lower bound rather than a number. Pairing the two arrays (as",
    "\n      lazily-cpp does) is what makes those floors auditable from here.",
  );
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
  `corpus floors OK: ${observed.fixtures} fixtures pinned, ` +
    `${Object.values(arrays).reduce((n, k) => n + Object.keys(k).length, 0)} array length(s) across ` +
    `${Object.keys(arrays).length} fixture(s) pinned exactly, ` +
    `${blockSiteTotal} assertion-block site(s) across ${Object.keys(blocks).length} fixture(s) ` +
    "pinned exactly, " +
    `${audited - nonDerivable.length} binding ledger(s) audited` +
    `${nonDerivable.length > 0 ? `, ${nonDerivable.length} not derivable` : ""}` +
    `${skipped.length > 0 ? `, ${skipped.length} skipped` : ""}` +
    `${undeclared.length > 0 ? `, ${undeclared.length} dimension(s) undeclared` : ""}`,
);
