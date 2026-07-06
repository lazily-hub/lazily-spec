#!/usr/bin/env node
// Single-source feature-matrix generator.
//
// `coverage.json` (repo root) is the canonical cross-language coverage table.
// This script renders it to a markdown table and injects it between the marker
// comments
//
//     <!-- coverage-table:start -->
//     <!-- coverage-table:end -->
//
// in this repo's `README.md`, `docs/coverage.md`, and every sibling binding
// README (`../lazily-{rs,py,kt,js,dart,zig}/README.md`). Edit coverage.json,
// then run `node scripts/sync-coverage.mjs` to update every table in one shot.
//
//   node scripts/sync-coverage.mjs          # write/update all present targets
//   node scripts/sync-coverage.mjs --check  # exit 1 if any present target is stale
//
// In `--check` mode, missing sibling repos are skipped (so lazily-spec CI, which
// has no siblings checked out, still enforces docs/coverage.md ↔ coverage.json).

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const START = "<!-- coverage-table:start -->";
const END = "<!-- coverage-table:end -->";

const TARGETS = [
  join(ROOT, "README.md"),
  join(ROOT, "docs", "coverage.md"),
  join(ROOT, "..", "lazily-rs", "README.md"),
  join(ROOT, "..", "lazily-py", "README.md"),
  join(ROOT, "..", "lazily-kt", "README.md"),
  join(ROOT, "..", "lazily-js", "README.md"),
  join(ROOT, "..", "lazily-dart", "README.md"),
  join(ROOT, "..", "lazily-zig", "README.md"),
  join(ROOT, "..", "lazily-go", "README.md"),
];

function renderTable() {
  const data = JSON.parse(readFileSync(join(ROOT, "coverage.json"), "utf8"));
  const header = `| Feature | ${data.languages.join(" | ")} |`;
  const align = `| ${data.align.join(" | ").replace("Feature", "---------")} |`;
  const rows = data.rows.map(
    (r) => `| ${r.feature} | ${r.marks.join(" | ")} |`,
  );
  return [header, align, ...rows].join("\n");
}

function inject(source, table) {
  const s = source.indexOf(START);
  const e = source.indexOf(END);
  if (s === -1 || e === -1 || e < s) {
    return null; // no markers
  }
  return source.slice(0, s + START.length) + "\n" + table + "\n" + source.slice(e);
}

const table = renderTable();
const check = process.argv.includes("--check");
let stale = 0;
let wrote = 0;

for (const path of TARGETS) {
  if (!existsSync(path)) {
    continue; // sibling not checked out — skip
  }
  const source = readFileSync(path, "utf8");
  const next = inject(source, table);
  if (next === null) {
    console.error(`! ${path}: missing coverage-table markers`);
    stale += 1;
    continue;
  }
  if (next === source) {
    continue;
  }
  if (check) {
    console.error(`✗ ${path}: coverage table is out of sync with coverage.json`);
    stale += 1;
  } else {
    writeFileSync(path, next);
    console.log(`✓ ${path}: updated`);
    wrote += 1;
  }
}

if (check && stale > 0) {
  console.error(`\n${stale} target(s) stale. Run: node scripts/sync-coverage.mjs`);
  process.exit(1);
}
if (!check) {
  console.log(`Done — ${wrote} file(s) updated.`);
}
