#!/usr/bin/env node
// Prose-key declaration guard (`#lzprosekeyconvention`).
//
// The failure this closes
// -----------------------
// An `assertions` block mixes two kinds of key. Most carry a value a runner can
// compare against observed behaviour — a list, a count, a vocabulary. A few
// carry an English paragraph that states an obligation and nothing comparable:
// `clause`, `anti_vacuity`, `null_form`, `theorem`, `note`.
//
// Nothing said which was which, so nine bindings each decided, and they landed
// on FOUR different answers while replaying the same fixture:
//
//   * lazily-js excused every paragraph, its own `assert-key.js` warning against
//     comparing an English paragraph to a literal;
//   * lazily-py, lazily-dart, lazily-go, lazily-kt, lazily-cs and lazily-zig
//     excused them with individually-worded reasons naming the assertion that
//     discharges each — falsifiable in principle, checked by nothing;
//   * lazily-rs marked them `Expect::prose`, a third tracker state exempt from
//     every check, which demands a reason and then DISCARDS it;
//   * lazily-cpp ASSERTED all four of v2's new paragraphs against tallies from
//     the run.
//
// Each is defensible alone, which is exactly the shape of the 5-2 split the
// blob-backend clause itself came from: an undocumented default and a deliberate
// choice are indistinguishable from the outside, and so are four deliberate ones.
//
// The rule this enforces (corpus half)
// ------------------------------------
// The CORPUS declares which keys are prose, in `assertions.prose`, so the
// question is settled once instead of nine times. This script checks that
// declaration against the fixtures:
//
//   1. every prose-SHAPED value in a fixture's `assertions` block is declared
//      (nothing sneaks in)
//   2. every declared key exists and is prose-shaped (nothing goes stale)
//   3. `prose` never lists itself
//   4. a block declaring prose also carries an executable key — a block that is
//      entirely prose has nothing that could discharge it
//   5. `note` / `description` / `reason` inside a per-step or per-scenario
//      block are ANNOTATIONS, exempt by reserved name in every binding, so they
//      MUST NOT state an obligation
//   6. any other nested key stating an obligation must be promoted into the
//      fixture's `assertions` block and declared, since only a declared key has
//      a discharge path
//   7. generator provenance is top-level metadata naming an existing script,
//      never an assertion key that nine bindings must excuse
//
// The BINDING half — that each declared key is discharged by naming executable
// assertion keys the same fixture run actually asserted — is enforced inside
// each binding's assertion-key tracker, at runtime, because only the run knows
// what it asserted. See docs/conformance.md § Prose assertion keys.
//
// Why a shape heuristic and not a hand-kept list
// ----------------------------------------------
// A list of "keys that are prose" maintained here would go stale the same way
// the static coverage grep did: it proves a spelling, not a property. The
// detector reads the VALUE. A string with whitespace that either runs to 60
// characters or ends a sentence is prose; `"MUST"`, `"json"`, `"reference"` and
// `scripts/gen_x.py` are not. A new paragraph therefore reddens this guard on
// the commit that adds it, rather than being silently absorbed by nine runners.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const CORPUS = join(ROOT, "conformance");

const PROSE_KEY = "prose";
const MIN_PROSE_LENGTH = 60;

// Keys whose contents every binding's tracker exempts by NAME, at any depth.
const ANNOTATION_KEYS = new Set(["note", "description", "reason"]);

// Blocks the assertion-key trackers guard.
const BLOCK_KEYS = new Set(["assertions", "expect", "expected"]);

// RFC-2119 vocabulary. A paragraph carrying one of these is stating an
// obligation on the binding, not annotating the fixture.
const OBLIGATION = /\b(MUST|SHALL|REQUIRED)\b/;

/// A value is prose when it is a string that reads as a sentence: it has
/// whitespace AND either runs long or terminates like one. Both halves matter —
/// `"scripts/gen_x.py"` is long with no whitespace, `"MUST"` has neither.
function isProse(value) {
  if (typeof value !== "string") return false;
  const text = value.trim();
  if (!/\s/.test(text)) return false;
  return text.length >= MIN_PROSE_LENGTH || /[.!?]$/.test(text);
}

function* fixtures(dir) {
  for (const entry of readdirSync(dir).sort()) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) yield* fixtures(path);
    else if (entry.endsWith(".json")) yield path;
  }
}

// The corpus half of `wire_encoding` (`#lzprosekeyconvention`). Five bindings
// reported the same thing: that paragraph claims something about how the CORPUS
// FILE is written — raw text and hex rather than a pre-parsed object — and no
// assertion a *run* used to observe. `expect.wire_input_fnv1a64` now makes the
// runner compare the exact bytes it hands to the decoder, while this check
// independently derives and validates that expectation from the raw corpus
// field. `wire_json` carried as an OBJECT is the exact defect the paragraph
// forbids: a pre-parsed value cannot express an absent map entry versus an
// explicit null, which is the distinction three of these fixtures turn on.
function fnv1a64Hex(bytes) {
  let digest = 0xcbf29ce484222325n;
  for (const byte of bytes) {
    digest ^= BigInt(byte);
    digest = BigInt.asUintN(64, digest * 0x100000001b3n);
  }
  return digest.toString(16).padStart(16, "0");
}

function checkWireForms(id, doc, declaresWireEncoding, violations) {
  const scenarios = Array.isArray(doc?.scenarios) ? doc.scenarios : [];
  let jsonText = 0;
  let msgpackHex = 0;
  scenarios.forEach((scenario, index) => {
    if (scenario === null || typeof scenario !== "object") return;
    const at = scenario.id ?? scenario.name ?? `scenarios[${index}]`;
    let wireInput;
    if ("wire_json" in scenario) {
      if (typeof scenario.wire_json !== "string") {
        violations.push(
          `${id}: \`${at}.wire_json\` is a ${typeof scenario.wire_json}, not RAW TEXT. A ` +
            `pre-parsed value cannot express an absent map entry versus an explicit null, ` +
            `which is the distinction these fixtures turn on.`,
        );
      } else {
        jsonText += 1;
        wireInput = Buffer.from(scenario.wire_json, "utf8");
        try {
          JSON.parse(scenario.wire_json);
        } catch (error) {
          violations.push(`${id}: \`${at}.wire_json\` is not parseable JSON: ${error.message}`);
        }
      }
    }
    if ("wire_msgpack_hex" in scenario) {
      const hex = scenario.wire_msgpack_hex;
      if (typeof hex !== "string" || !/^[0-9a-f]*$/.test(hex) || hex.length % 2 !== 0) {
        violations.push(
          `${id}: \`${at}.wire_msgpack_hex\` is not even-length lowercase hex. The paragraph ` +
            `pins the encoding so the exact bytes survive into the runner.`,
        );
      } else {
        msgpackHex += 1;
        wireInput = Buffer.from(hex, "hex");
      }
    }
    if (declaresWireEncoding && wireInput !== undefined) {
      const expected = scenario?.expect?.wire_input_fnv1a64;
      const observed = fnv1a64Hex(wireInput);
      if (expected !== observed) {
        violations.push(
          `${id}: \`${at}.expect.wire_input_fnv1a64\` is ${JSON.stringify(expected)}, ` +
            `expected ${observed} for the exact decoder-input bytes.`,
        );
      }
    }
  });
  if (declaresWireEncoding && (jsonText === 0 || msgpackHex === 0)) {
    violations.push(
      `${id}: declares \`wire_encoding\` prose but carries ${jsonText} raw-text json and ` +
        `${msgpackHex} hex msgpack scenario(s). The paragraph claims a distinction across both ` +
        `codecs; a fixture carrying only one cannot support it.`,
    );
  }
}

const violations = [];
let blocksWithProse = 0;
let declaredKeys = 0;
let blocksScanned = 0;
let annotationsScanned = 0;

for (const path of fixtures(CORPUS)) {
  const id = relative(ROOT, path);
  let doc;
  try {
    doc = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    violations.push(`${id} is not readable JSON: ${error.message}`);
    continue;
  }

  const generator = doc?.generator;
  if (generator !== undefined) {
    if (typeof generator !== "string" || generator.length === 0) {
      violations.push(`${id}: top-level \`generator\` must be a non-empty script path`);
    } else {
      try {
        if (!statSync(join(ROOT, generator)).isFile()) {
          violations.push(`${id}: top-level \`generator\` does not name a file: ${generator}`);
        }
      } catch {
        violations.push(`${id}: top-level \`generator\` does not exist: ${generator}`);
      }
    }
  }

  // ---- Rules 1-4: the fixture's own top-level `assertions` block. ----------
  const block = doc?.assertions;
  const declaredSet = new Set();
  if (block !== null && typeof block === "object" && !Array.isArray(block)) {
    blocksScanned += 1;
    const declared = block[PROSE_KEY];
    if (declared !== undefined && !Array.isArray(declared)) {
      violations.push(`${id}: \`assertions.${PROSE_KEY}\` must be an array of key names`);
    } else {
      for (const key of declared ?? []) declaredSet.add(key);
      const keys = Object.keys(block).filter((key) => key !== PROSE_KEY);

      if (declaredSet.has(PROSE_KEY)) {
        violations.push(
          `${id}: \`assertions.${PROSE_KEY}\` lists itself. The declaration is not one of the ` +
            `keys it declares.`,
        );
      }

      for (const key of keys) {
        if (isProse(block[key]) && !declaredSet.has(key)) {
          violations.push(
            `${id}: \`assertions.${key}\` is a paragraph but is not declared in ` +
              `\`assertions.${PROSE_KEY}\`. Declare it — nine runners must not each decide ` +
              `whether it is prose — or give it a value a runner can compare.`,
          );
        }
      }

      for (const key of declaredSet) {
        if (key === PROSE_KEY) continue;
        if (!(key in block)) {
          violations.push(
            `${id}: \`assertions.${PROSE_KEY}\` names \`${key}\`, which the block does not ` +
              `carry. The declaration has gone stale.`,
          );
          continue;
        }
        if (!isProse(block[key])) {
          violations.push(
            `${id}: \`assertions.${key}\` is declared prose but its value is comparable ` +
              `(${JSON.stringify(block[key]).slice(0, 40)}). Assert it instead — declaring a ` +
              `machine-checkable value prose is the exemption this guard exists to remove.`,
          );
        }
      }

      if (declaredSet.size > 0) {
        blocksWithProse += 1;
        declaredKeys += declaredSet.size;
        if (keys.every((key) => declaredSet.has(key))) {
          violations.push(
            `${id}: every key in \`assertions\` is declared prose. A prose key is discharged ` +
              `by naming an executable sibling, so a block with none cannot be discharged.`,
          );
        }
      }
    }
  }

  checkWireForms(id, doc, declaredSet.has("wire_encoding"), violations);

  // ---- Rules 5-6: every guarded block, at any depth. -----------------------
  const walk = (node, trail) => {
    if (Array.isArray(node)) {
      node.forEach((child, index) => walk(child, `${trail}[${index}]`));
      return;
    }
    if (node === null || typeof node !== "object") return;
    for (const [key, value] of Object.entries(node)) {
      const here = trail === "" ? key : `${trail}.${key}`;
      if (key === "generator" && trail !== "") {
        violations.push(
          `${id}: \`${here}\` is provenance metadata, not an assertion; ` +
            "move it to the fixture root",
        );
      }
      const isTopLevelAssertions = here === "assertions";
      const isBlock =
        BLOCK_KEYS.has(key) && value !== null && typeof value === "object" && !Array.isArray(value);
      if (isBlock) {
        for (const [inner, text] of Object.entries(value)) {
          if (typeof text !== "string") continue;
          // The fixture's own assertions block is rules 1-4's business, and a
          // key it DECLARED prose is allowed to state an obligation — that is
          // the point of declaring it.
          if (isTopLevelAssertions && (declaredSet.has(inner) || inner === PROSE_KEY)) continue;
          const at = `${here}.${inner}`;
          if (ANNOTATION_KEYS.has(inner)) {
            annotationsScanned += 1;
            if (!OBLIGATION.test(text)) continue;
            violations.push(
              `${id}: \`${at}\` is a reserved annotation name, which every binding exempts ` +
                `by name, but it states an obligation (${JSON.stringify(text.slice(0, 60))}…). ` +
                `An obligation no runner can be made to discharge is the silent skip this ` +
                `guard removes: promote it to a key the block asserts, or reword it.`,
            );
            continue;
          }
          if (isProse(text) && OBLIGATION.test(text)) {
            violations.push(
              `${id}: \`${at}\` states an obligation in prose from a block with no prose ` +
                `declaration. Promote it into the fixture's \`assertions\` block and list it ` +
                `in \`assertions.${PROSE_KEY}\`, so a runner has to discharge it.`,
            );
          }
        }
      }
      walk(value, here);
    }
  };
  walk(doc, "");
}

console.log(
  `prose keys: ${declaredKeys} declared across ${blocksWithProse} assertion block(s) of ` +
    `${blocksScanned} scanned; ${annotationsScanned} reserved annotation(s) checked`,
);

if (violations.length > 0) {
  console.error("");
  for (const violation of violations) console.error(`✗ ${violation}`);
  console.error(
    `\n${violations.length} prose-key declaration problem(s) (#lzprosekeyconvention). ` +
      `See docs/conformance.md § Prose assertion keys.`,
  );
  process.exit(1);
}

console.log("prose keys OK");
