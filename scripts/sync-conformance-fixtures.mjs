#!/usr/bin/env node
// Keep the selected conformance fixtures vendored by standalone bindings
// byte-identical to this repository's canonical corpus.
//
//   node scripts/sync-conformance-fixtures.mjs --check
//   node scripts/sync-conformance-fixtures.mjs --check --require-all
//   node scripts/sync-conformance-fixtures.mjs --sync
//
// Missing sibling repositories are skipped by default so lazily-spec remains
// independently testable. Use --require-all for the multi-repository gate.

import {
  copyFileSync,
  existsSync,
  readFileSync,
  readdirSync,
  statSync,
} from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_SPEC_ROOT = resolve(HERE, "..");

let mode = "sync";
let requireAll = false;
let specRoot = DEFAULT_SPEC_ROOT;
let siblingsRoot = resolve(DEFAULT_SPEC_ROOT, "..");

const args = process.argv.slice(2);
for (let i = 0; i < args.length; i += 1) {
  const arg = args[i];
  switch (arg) {
    case "--check":
      mode = "check";
      break;
    case "--sync":
      mode = "sync";
      break;
    case "--require-all":
      requireAll = true;
      break;
    case "--spec-root":
      if (i + 1 >= args.length) {
        throw new Error("--spec-root requires a path");
      }
      specRoot = resolve(args[++i]);
      break;
    case "--siblings-root":
      if (i + 1 >= args.length) {
        throw new Error("--siblings-root requires a path");
      }
      siblingsRoot = resolve(args[++i]);
      break;
    default:
      throw new Error(`unknown argument: ${arg}`);
  }
}

const canonicalRoot = join(specRoot, "conformance");
const mirrors = [
  ["lazily-py", join(siblingsRoot, "lazily-py", "tests", "conformance")],
  ["lazily-dart", join(siblingsRoot, "lazily-dart", "test", "conformance")],
  ["lazily-rs", join(siblingsRoot, "lazily-rs", "tests", "conformance")],
  ["lazily-go", join(siblingsRoot, "lazily-go", "test", "conformance")],
  // lazily-zig vendors its subset under the library tree rather than a `tests/`
  // directory. It carries its own drift test, but that only fires when the Zig
  // suite runs; listing it here makes the corpus-side gate the single place a
  // fixture change is reconciled for every mirror.
  ["lazily-zig", join(siblingsRoot, "lazily-zig", "src", "lazily", "test")],
];

function jsonFiles(root) {
  const files = [];

  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort(
      (a, b) => a.name.localeCompare(b.name),
    )) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(path);
      } else if (entry.isFile() && entry.name.endsWith(".json")) {
        files.push(path);
      }
    }
  }

  visit(root);
  return files;
}

if (!existsSync(canonicalRoot) || !statSync(canonicalRoot).isDirectory()) {
  throw new Error(`canonical fixture directory is absent: ${canonicalRoot}`);
}

let compared = 0;
let presentMirrors = 0;
let updated = 0;
const failures = [];

for (const [binding, mirrorRoot] of mirrors) {
  if (!existsSync(mirrorRoot)) {
    const message = `${binding}: mirror absent at ${mirrorRoot}`;
    if (requireAll) {
      failures.push(message);
    } else {
      console.log(`- ${message}; skipped`);
    }
    continue;
  }

  presentMirrors += 1;
  const files = jsonFiles(mirrorRoot);
  if (files.length === 0) {
    failures.push(`${binding}: mirror contains no JSON fixtures: ${mirrorRoot}`);
    continue;
  }

  for (const mirrorPath of files) {
    const fixture = relative(mirrorRoot, mirrorPath);
    const canonicalPath = join(canonicalRoot, fixture);
    if (!existsSync(canonicalPath)) {
      failures.push(
        `${binding}: ${fixture} has no canonical counterpart at ${canonicalPath}`,
      );
      continue;
    }

    const mirrorBytes = readFileSync(mirrorPath);
    const canonicalBytes = readFileSync(canonicalPath);
    compared += 1;
    if (mirrorBytes.equals(canonicalBytes)) {
      continue;
    }

    if (mode === "check") {
      failures.push(
        `${binding}: ${fixture} drifted (${mirrorBytes.length} mirror bytes, ` +
          `${canonicalBytes.length} canonical bytes)`,
      );
    } else {
      copyFileSync(canonicalPath, mirrorPath);
      console.log(`✓ ${binding}: updated ${fixture}`);
      updated += 1;
    }
  }
}

if (presentMirrors === 0 && !requireAll) {
  console.log("- no binding mirrors are checked out; nothing to compare");
}

if (failures.length > 0) {
  for (const failure of failures) {
    console.error(`✗ ${failure}`);
  }
  if (mode === "check") {
    console.error(
      `\n${failures.length} fixture-copy problem(s). Run: ` +
        "node scripts/sync-conformance-fixtures.mjs --sync",
    );
  }
  process.exit(1);
}

if (mode === "check") {
  console.log(
    `✓ ${compared} vendored fixture(s) across ${presentMirrors} binding(s) ` +
      "match the canonical corpus byte-for-byte",
  );
} else {
  console.log(
    `Done — ${updated} fixture(s) updated; ${compared} fixture(s) inspected.`,
  );
}
