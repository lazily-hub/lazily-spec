#!/usr/bin/env node
// Scenario-identity guard (#lzspecscenarioids).
//
// Every scenario in the canonical corpus must carry a STABLE `id`. This is a
// corpus-side invariant because the nine bindings' scenario ledgers all resolve
// a scenario the same way, and until this guard existed they all shared the same
// escape hatch: a scenario with neither key fell back to its POSITIONAL index,
// spelled `#<n>`.
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
// The identifier SPELLING is now settled, and it is `id`
// (`#recommendedconformanceco`). It used to be a live fork — 27 fixtures
// identified a scenario by `name`, 8 by `id`, and every binding resolved
// `id`-else-`name`, so the spelling was invisible right up until someone changed
// one. Three things decided it:
//
//   1. `schemas/stdlib-fixture.schema.json` already REQUIRES `id` and, being
//      `additionalProperties: false`, forbids `name`. Canonicalizing on `name`
//      would mean versioning a published `$id` schema to make the corpus legal
//      against itself.
//   2. Resolution is `id`-else-`name` in all nine bindings, so wherever both
//      exist `id` is already the key the ledger records. The four codec fixtures
//      carry both, spelled identically.
//   3. 35 of the 75 `name`-only scenarios used a PROSE SENTENCE as their name —
//      "folds whole subtree; edit recomputes only ancestor chain, not siblings".
//      A ledger keyed on prose silently rebinds on a copy-edit, which is the
//      same failure a positional id has and the same one this guard exists to
//      stop. `name` is a label; a label is not an identity.
//
// So `id` is required and `name` is an optional human label. Adding `id` was
// purely additive — `name` stayed, so no runner that dispatches on it broke, and
// the 40 scenarios whose name was already a slug took that slug verbatim and did
// not move their ledger key at all.
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
let labelled = 0;

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
    if (nonBlank(scenario.name)) labelled += 1;
    if (!nonBlank(scenario.id)) {
      console.error(
        `ERROR: ${rel} scenario at index ${index} carries no \`id\`.`,
        "\n       `id` is the canonical scenario identifier (#recommendedconformanceco) —",
        "\n       every binding resolves `id`-else-`name`, and the stdlib fixture schema",
        "\n       requires it. Without one this scenario's ledger entry is keyed on its",
        "\n       `name` (a prose label a copy-edit may reword) or on its POSITION, and",
        "\n       either way inserting or rewording something ahead of it silently rebinds",
        "\n       that entry — and every excuse naming it — with nothing turning red.",
        "\n       Give it a stable snake_case `id`; keep `name` as the human label.",
      );
      problems += 1;
      return;
    }
    if (!/^[a-z0-9_]+$/.test(scenario.id)) {
      console.error(
        `ERROR: ${rel} scenario at index ${index} has id ${JSON.stringify(scenario.id)},`,
        "\n       which is not snake_case. An id is a key ten repositories compare on;",
        "\n       spell it [a-z0-9_]+ and put the prose in `name`.",
      );
      problems += 1;
      return;
    }
    const twin = doc.scenarios.findIndex(
      (other, at) => at !== index && other?.id === scenario.id,
    );
    if (twin !== -1 && twin < index) {
      console.error(
        `ERROR: ${rel} scenarios at index ${twin} and ${index} share the id`,
        `${JSON.stringify(scenario.id)}. The ledger records one entry per fixture+id, so`,
        "\n       one of the two replays would book the other's evidence.",
      );
      problems += 1;
    }
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
  `scenario identity OK: ${scenarios} scenarios across ${checked} fixtures all carry a unique` +
    ` snake_case \`id\` (${labelled} also carry a human \`name\`; neither the positional` +
    " fallback nor a prose ledger key is reachable)",
);
