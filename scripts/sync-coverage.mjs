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
// README (`../lazily-{rs,py,kt,js,dart,zig,go,cpp,cs,gd,formal}/README.md`). Edit coverage.json,
// then run `node scripts/sync-coverage.mjs` to update every table in one shot.
//
//   node scripts/sync-coverage.mjs          # write/update all present targets
//   node scripts/sync-coverage.mjs --check  # exit 1 if any present target is stale
//
// In `--check` mode, missing sibling repos are skipped (so lazily-spec CI, which
// has no siblings checked out, still enforces docs/coverage.md ↔ coverage.json).
//
// Two renderings, one source (#lzcoveragereadmerollup). `docs/coverage.md` is the
// ONLY place the 74-row detail lives; every README carries the family × language
// roll-up plus a link to it. That is not just brevity: a row mark usually does not
// move its family's roll-up cell, so the common coverage.json edit now rewrites one
// file instead of thirteen, and a row-level change stops fanning a commit out across
// twelve repos. Row-level parity is not lost — it was never the README's job to
// guard it. `scripts/check-coverage-claims.mjs` ties every wire-bearing mark to a
// fixture the binding replays, and each binding's `scripts/check-conformance-coverage.sh`
// fails on a canonical fixture it does not replay. Both run in CI, on the data, not
// on a rendered table someone has to read.

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const START = "<!-- coverage-table:start -->";
const END = "<!-- coverage-table:end -->";

// `detail: true` renders the roll-up AND the per-family row tables; `false`
// renders the roll-up plus a link to the canonical detail. Exactly one target is
// allowed to carry the detail, so there is never a second copy to drift.
const TARGETS = [
  { path: join(ROOT, "docs", "coverage.md"), detail: true },
  { path: join(ROOT, "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-rs", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-py", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-kt", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-js", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-dart", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-zig", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-go", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-cpp", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-cs", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-gd", "README.md"), detail: false },
  { path: join(ROOT, "..", "lazily-formal", "README.md"), detail: false },
];

// Absolute, because ten of the eleven summary targets render on a DIFFERENT
// repository's GitHub page, where a relative path to lazily-spec resolves to
// nothing.
const DETAIL_URL =
  "https://github.com/lazily-hub/lazily-spec/blob/main/docs/coverage.md";

// Roll-up rule (#lzcoveragelayout Phase 4). A summary cell that averages is a
// lie, so this is total and stated: a family is shipped only when EVERY row in
// it is shipped. Kept next to LEGEND_ROLLUP below, which publishes it.
const SHIPPED = "✅";
const PARTIAL = "~";
const ABSENT = "—";
const NA = "⊘";

function rollUp(marks) {
  if (marks.every((m) => m === SHIPPED)) return SHIPPED;
  if (marks.every((m) => m === NA)) return NA;
  // No row shipped and none partial: the family is absent here, even if some of
  // its rows are structurally not applicable.
  if (marks.every((m) => m === ABSENT || m === NA)) return ABSENT;
  return PARTIAL;
}

// `below` only exists where the detail tables are rendered; a summary target has
// no *(opt)* marker to point at, so the clause has to change with the rendering
// rather than describe a table that is not there.
const legendRollUp = (withDetail) =>
  "**Roll-up rule:** a family cell is `✅` only when *every required* row in that family is `✅`; " +
  "`~` when the family is mixed (some shipped or partial); `—` when no required row is shipped or partial; " +
  "`⊘` only when every required row in the family is not applicable. " +
  `Rows the spec marks **MAY** (\`optional\`${withDetail ? ", shown as *opt* below" : ""}) are excluded from the roll-up — ` +
  "declining an optional feature is not a gap.";

function renderTable(withDetail) {
  const data = JSON.parse(readFileSync(join(ROOT, "coverage.json"), "utf8"));
  // Four marks (#lzcoveragelayout Phase 2): ✅ shipped, ~ partial,
  // — absent (not yet implemented), ⊘ not applicable (structurally cannot).
  // A ⊘ cell MUST carry a reason in the row's `na` map (language name →
  // reason); the guard below refuses a ⊘ without a reason and a reason
  // without a ⊘, so 'cannot' is never confused with 'has not'.
  const naNotes = [];
  // Families are authored, not inferred — the feature text does not encode them
  // (54 distinct prefixes across 74 rows). `families` fixes the render order.
  if (!Array.isArray(data.families) || data.families.length === 0) {
    throw new Error(
      "coverage.json is missing a non-empty `families` array — each entry needs `id` and `title`, and it fixes the order the family tables render in.",
    );
  }
  const familyTitle = new Map();
  for (const [i, f] of data.families.entries()) {
    if (typeof f.id !== "string" || typeof f.title !== "string") {
      throw new Error(
        `coverage.json families[${i}] needs a string \`id\` and \`title\`.`,
      );
    }
    if (familyTitle.has(f.id)) {
      throw new Error(`coverage.json declares family '${f.id}' twice.`);
    }
    familyTitle.set(f.id, f.title);
  }
  for (const [i, r] of data.rows.entries()) {
    if (typeof r.id !== "string" || typeof r.label !== "string") {
      throw new Error(
        `coverage.json row ${i} is missing a string \`id\`/\`label\` — every row needs both (the short cell text and the footnote key).`,
      );
    }
    // No row may be orphaned: an unknown family would silently vanish from
    // every per-family table while still counting as covered.
    if (typeof r.family !== "string" || !familyTitle.has(r.family)) {
      throw new Error(
        `coverage.json row '${r.id}' has family '${r.family}', which is not declared in \`families\`. Every row must belong to exactly one declared family.`,
      );
    }
    const na = r.na ?? {};
    data.languages.forEach((lang, li) => {
      const mark = r.marks[li];
      const hasReason = Object.prototype.hasOwnProperty.call(na, lang);
      if (mark === NA && !hasReason) {
        throw new Error(
          `coverage.json row '${r.id}' marks ${lang} as '${NA}' (not applicable) but gives no reason in \`na\`. Use \`—\` for absent, or record why ${lang} cannot support it.`,
        );
      }
      if (hasReason && mark !== NA) {
        throw new Error(
          `coverage.json row '${r.id}' records an \`na\` reason for ${lang} but marks it '${mark}', not '${NA}'. An \`na\` reason belongs only on a not-applicable cell.`,
        );
      }
      if (hasReason) {
        naNotes.push(`- ${lang} — ${r.label}: ${na[lang]}`);
      }
    });
  }
  const header = (first) => `| ${first} | ${data.languages.join(" | ")} |`;
  const align = `| ${data.align.join(" | ").replace("Feature", "---------")} |`;

  // Group in `families` order; a family declared with no rows is a stale entry
  // rather than an empty section, so it fails rather than rendering blank.
  const grouped = data.families.map((f) => ({
    ...f,
    rows: data.rows.filter((r) => r.family === f.id),
  }));
  const barren = grouped.filter((g) => g.rows.length === 0).map((g) => g.id);
  if (barren.length > 0) {
    throw new Error(
      `coverage.json declares family/families [${barren.join(", ")}] that no row belongs to. Remove them from \`families\` or assign rows.`,
    );
  }

  // Roll-up first: the compact "where are we" view (#lzcoveragelayout Phase 4).
  // It regenerates from `rows` alone — there is no second hand-maintained source.
  //
  // Optional (MAY) rows are excluded, or one declined optional feature reads as
  // a family-wide gap: `frame-codec-postcard` is Rust-only by design and would
  // otherwise show every other binding as partial on the whole codec family.
  // A family of nothing but optional rows falls back to scoring them, so it can
  // never render an empty cell.
  const rollUpRows = grouped.map((g) => {
    const scored = g.rows.some((r) => !r.optional)
      ? g.rows.filter((r) => !r.optional)
      : g.rows;
    const marks = data.languages.map((_, li) =>
      rollUp(scored.map((r) => r.marks[li])),
    );
    return `| ${g.title} | ${marks.join(" | ")} |`;
  });

  // Narrow detail tables: the cell shows the short `label` plus a footnote
  // reference (`[^id]`); the normative `feature` prose is relocated to footnote
  // definitions below so row width follows the language axis, not the prose
  // (#lzcoveragelayout Phase 1).
  const detail = [];
  for (const g of grouped) {
    detail.push(
      "",
      `#### ${g.title}`,
      "",
      header("Feature"),
      align,
      ...g.rows.map(
        (r) =>
          `| ${r.label}${r.optional ? " *(opt)*" : ""} [^${r.id}] | ${r.marks.join(" | ")} |`,
      ),
    );
  }

  const footnotes = data.rows.map((r) => `[^${r.id}]: ${r.feature}`);
  const parts = [
    "#### Summary — family × language",
    "",
    header("Family"),
    align,
    ...rollUpRows,
    "",
    legendRollUp(withDetail),
  ];
  if (!withDetail) {
    // The roll-up answers "where are we"; it deliberately cannot answer "which
    // row". Say so and point at the one place that can, rather than letting a
    // `~` read as the whole story.
    parts.push(
      "",
      `A family cell summarises ${data.rows.length} feature rows. For row-level marks, ` +
        `per-cell notes, and platform carve-outs see ` +
        `[the canonical coverage matrix in \`lazily-spec\`](${DETAIL_URL}).`,
    );
    return parts.join("\n");
  }
  parts.push(...detail, "", ...footnotes);
  if (naNotes.length > 0) {
    parts.push("", "**Not applicable:**", ...naNotes);
  }
  return parts.join("\n");
}

function inject(source, table) {
  const s = source.indexOf(START);
  const e = source.indexOf(END);
  if (s === -1 || e === -1 || e < s) {
    return null; // no markers
  }
  return source.slice(0, s + START.length) + "\n" + table + "\n" + source.slice(e);
}

// Rendered once each, not per target: every summary target gets byte-identical
// text, so a divergence between two READMEs is impossible by construction.
const RENDERED = { true: renderTable(true), false: renderTable(false) };

// Exactly one detail copy is the whole point of the split; two would reintroduce
// the drift this removes.
const detailTargets = TARGETS.filter((t) => t.detail);
if (detailTargets.length !== 1) {
  throw new Error(
    `TARGETS must declare exactly one \`detail: true\` target (found ${detailTargets.length}). The row-level table lives in one file; every other target links to it.`,
  );
}

const check = process.argv.includes("--check");
let stale = 0;
let wrote = 0;

for (const { path, detail } of TARGETS) {
  if (!existsSync(path)) {
    continue; // sibling not checked out — skip
  }
  const source = readFileSync(path, "utf8");
  const next = inject(source, RENDERED[detail]);
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
