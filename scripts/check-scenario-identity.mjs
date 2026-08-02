#!/usr/bin/env node
// Scenario-identity guard (#lzspecscenarioids).
//
// Every scenario in the canonical corpus must carry a STABLE identifier — an
// `id`, else a `name`. This is a corpus-side invariant because the nine
// bindings' scenario ledgers all resolve a scenario the same way, and until
// this guard existed they all shared the same escape hatch: a scenario with
// neither key fell back to its POSITIONAL index, spelled `#<n>`.
//
// A positional id is fragile in exactly the way the replay ladder cares about.
// The ledger records "this run replayed `collections/mergecell_algebra.json`
// scenario #1", and the guard compares that against the scenario found at
// index 1 on disk. Insert a scenario at the front of the array and every entry
// silently rebinds to a different scenario — every ledger record, and every
// `KNOWN_UNREPLAYED_SCENARIOS` excuse, now names something nobody chose. Nothing
// turns red. The evidence quietly starts describing the wrong thing, which is
// the failure mode the whole ladder exists to prevent, one level up.
//
// So the fallback is not a feature to keep working; it is a hole to close. The
// three `collections/mergecell_algebra.json` scenarios — distinguishable only by
// their `policy` field — were the last users of it, and they now carry
// `keep_latest` / `sum` / `max`. With the corpus fully identified, every binding
// can turn its positional fallback into a hard error, and this guard is what
// stops a new fixture from quietly re-arming it.
//
// Identifier SPELLING is deliberately not settled here: 27 fixtures identify a
// scenario by `name` and 7 by `id`, and canonicalizing on one would rebind 122
// ledger entries across ten repositories at once. That is a separate decision.
// What this guard fixes is the part that is not a matter of taste — a scenario
// with NO identifier at all.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = process.env.LAZILY_SPEC_CONFORMANCE_DIR ?? "conformance";

function fixtures(dir) {
  const out = [];
  for (const entry of readdirSync(dir).sort()) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...fixtures(full));
    else if (entry.endsWith(".json")) out.push(full);
  }
  return out;
}

const nonBlank = (value) => typeof value === "string" && value.trim() !== "";

let problems = 0;
let checked = 0;
let scenarios = 0;
const spelling = { id: 0, name: 0 };

for (const path of fixtures(ROOT)) {
  let doc;
  try {
    doc = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    console.error(`ERROR: ${path} is not valid JSON: ${error.message}`);
    problems += 1;
    continue;
  }
  if (doc === null || typeof doc !== "object" || !Array.isArray(doc.scenarios)) continue;
  checked += 1;
  doc.scenarios.forEach((scenario, index) => {
    scenarios += 1;
    const rel = path.slice(ROOT.length + 1);
    if (scenario === null || typeof scenario !== "object" || Array.isArray(scenario)) {
      console.error(
        `ERROR: ${rel} scenario at index ${index} is not an object, so it can carry no identifier.`,
      );
      problems += 1;
      return;
    }
    if (nonBlank(scenario.id)) {
      spelling.id += 1;
      return;
    }
    if (nonBlank(scenario.name)) {
      spelling.name += 1;
      return;
    }
    console.error(
      `ERROR: ${rel} scenario at index ${index} carries neither \`id\` nor \`name\`.`,
      "\n       Every binding's replay ledger would record it by POSITION, so inserting a",
      "\n       scenario ahead of it silently rebinds that ledger entry — and every excuse",
      "\n       naming it — to a different scenario, with nothing turning red.",
      "\n       Give it a stable `id` (or `name`); do not rely on the position.",
    );
    problems += 1;
  });
}

// The corpus itself must be non-empty, for the same reason every binding's
// guard asserts a magnitude: a walk over zero fixtures finds zero unidentified
// scenarios and reports OK having examined nothing (#lzvacuousrun).
if (checked === 0 || scenarios === 0) {
  console.error(
    `ERROR: found ${scenarios} scenario(s) across ${checked} scenario-bearing fixture(s) in ${ROOT}.`,
    "\n       This guard is vacuously green over an empty population — no scenario can",
    "\n       lack an identifier when none was examined. The corpus path is wrong.",
  );
  process.exit(1);
}

if (problems > 0) {
  console.error(`scenario identity FAILED: ${problems} problem(s)`);
  process.exit(1);
}

console.error(
  `scenario identity OK: ${scenarios} scenarios across ${checked} fixtures all carry a stable` +
    ` identifier (${spelling.id} by \`id\`, ${spelling.name} by \`name\`; no positional fallback` +
    " is reachable)",
);
