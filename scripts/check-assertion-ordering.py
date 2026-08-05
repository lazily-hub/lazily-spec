#!/usr/bin/env python3
"""Fail closed on cross-language conformance assertion source seams.

The original checks pin observation-before-assertion ordering. The companion
guard also rejects `assertKeyWith` callbacks that never read their fixture-value
parameter. They share this entry point because all nine binding Makefiles and
CI workflows already invoke it; a new standalone target would be a guard every
existing workflow could silently omit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OrderedCheck:
    path: str
    before: str
    after: str
    description: str
    paired: bool = False


CHECKS: dict[str, tuple[OrderedCheck, ...]] = {
    "rs": (
        OrderedCheck(
            "tests/distributed_conformance.rs",
            r"let\s+applied\s*=\s*ingest_ops",
            r'exp\.assert_key_with\(\s*"resolution"',
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "tests/nodeid_exact_range_conformance.rs",
            r"a\.finish\(\);",
            r"assert_eq!\(\s*replayed,\s*6",
            "fixture assertions precede the node-id runner floor",
        ),
    ),
    "py": (
        OrderedCheck(
            "tests/test_collection_conformance.py",
            r"applied\s*=\s*plane\.apply_ops",
            r'assert_key_with\(\s*expect,\s*"resolution"',
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "tests/test_nodeid_exact_range_conformance.py",
            r"verify_prose\(fixture\)",
            r"assert\s+accepted\s*==\s*6",
            "fixture assertions precede the node-id runner floor",
        ),
        OrderedCheck(
            "tests/test_nodekey_null_leniency_conformance.py",
            r"verify_prose\(fixture\)",
            r"assert\s+replayed\s*==\s*12",
            "fixture assertions precede the node-key runner floor",
        ),
        OrderedCheck(
            "tests/test_blob_backend_discriminator_conformance.py",
            r"verify_prose\(fixture\)",
            r"assert\s+accepted\s*==\s*10",
            "fixture assertions precede the blob runner floor",
        ),
        OrderedCheck(
            "tests/test_codec_conformance.py",
            r"verify_prose\(fixture\)",
            r"_assert_replay_floor\(replayed\)",
            "fixture assertions precede each codec runner floor",
            paired=True,
        ),
    ),
    "js": (
        OrderedCheck(
            "test/distributed.test.js",
            r"const\s+applied\s*=\s*ingestOps",
            r'assertKeyWith\(\s*scenario\.expect,\s*"resolution"',
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "test/nodeid-exact-range.test.js",
            r"verifyProse\(fixture\);",
            r"assert\.equal\(\s*accepted,\s*2",
            "fixture assertions precede the node-id runner floor",
        ),
        OrderedCheck(
            "test/nodekey-null-leniency.test.js",
            r"verifyProse\(fixture\);",
            r"assert\.equal\(\s*replayed,\s*12",
            "fixture assertions precede the node-key runner floor",
        ),
        OrderedCheck(
            "test/blob-backend-discriminator.test.js",
            r"verifyProse\(fixture\);",
            r"assert\.equal\(\s*accepted,\s*10",
            "fixture assertions precede the blob runner floor",
        ),
        OrderedCheck(
            "test/codec.test.js",
            r"verifyProse\(fixture\);",
            r"assert\.equal\(\s*replayed,\s*3",
            "fixture assertions precede each codec runner floor",
            paired=True,
        ),
    ),
    "go": (
        OrderedCheck(
            "receipts_distributed_conformance_test.go",
            r"if\s+got\s*:=\s*runtime\.IngestOps\(scenario\.Ops\);\s*got\s*!=\s*scenario\.Expect\.AppliedCount",
            r"assertCrdtResolution\(t,\s*scenario\.Expect\.Resolution",
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "nodeid_exact_range_conformance_test.go",
            r'assertKey\(t,\s*assertions,\s*"scenario_count"',
            r"if\s+accepted\s*!=\s*4",
            "fixture assertions precede the node-id runner floor",
        ),
    ),
    "cpp": (
        OrderedCheck(
            "tests/test_distributed_conformance.cpp",
            r"const\s+int\s+applied\s*=\s*runtime\.ingest\(frame\)",
            r"assert_max_stamp_resolution\(name,",
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "tests/test_nodeid_exact_range_conformance.cpp",
            r"block\.finish\(\);",
            r"REQUIRE\(accepted\s*==\s*4",
            "fixture assertions precede the node-id runner floor",
        ),
    ),
    "dart": (
        OrderedCheck(
            "test/distributed_conformance_test.dart",
            r"final\s+applied\s*=\s*runtime\.ingestOps\(ops\)",
            r"assertKey\(expect_,\s*'resolution'",
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "test/nodeid_exact_range_test.dart",
            r"assertKey\(block,\s*'scenario_count'",
            r"expect\(accepted,\s*intsAreDoubles",
            "fixture assertions precede the node-id runner floor",
        ),
    ),
    "kt": (
        OrderedCheck(
            "src/test/kotlin/io/github/lazily/CrdtPlaneTest.kt",
            r"val\s+applied\s*=\s*runtime\.ingest\(frame\)",
            r'a\.assertKeyWith\("resolution"',
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "src/test/kotlin/io/github/lazily/NodeIdExactRangeConformanceTest.kt",
            r"meta\.requireAllSatisfied\(\)",
            r"assertEquals\(4,\s*accepted",
            "fixture assertions precede the node-id runner floor",
        ),
    ),
    "zig": (
        OrderedCheck(
            "src/lazily/distributed_conformance.zig",
            r"const\s+applied\s*=\s*try\s+rt\.ingest",
            r'expect\.assertKeyWith\(\s*"resolution"',
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "src/lazily/nodeid_exact_range_conformance.zig",
            r"meta\.finish\(\)",
            r"expectEqual\(@as\(usize,\s*6\),\s*accepted",
            "fixture assertions precede the node-id runner floor",
        ),
    ),
    "cs": (
        OrderedCheck(
            "tests/Lazily.Tests/CrdtPlaneConformanceTests.cs",
            r"var\s+applied\s*=\s*runtime\.Ingest",
            r'expected\.AssertKeyWith\(\s*"resolution"',
            "distributed ingest precedes the resolution assertion",
        ),
        OrderedCheck(
            "tests/Lazily.Tests/NodeIdExactRangeConformanceTests.cs",
            r"prose\.VerifyProse\(Fixture\)",
            r"Assert\.Equal\(6,\s*accepted",
            "fixture assertions precede the node-id runner floor",
        ),
        OrderedCheck(
            "tests/Lazily.Tests/NodeKeyNullLeniencyConformanceTests.cs",
            r"prose\.VerifyProse\(Fixture\)",
            r"Assert\.Equal\(12,\s*replayed",
            "fixture assertions precede the node-key runner floor",
        ),
        OrderedCheck(
            "tests/Lazily.Tests/BlobBackendDiscriminatorConformanceTests.cs",
            r"prose\.VerifyProse\(Fixture\)",
            r"Assert\.Equal\(14,\s*replayed",
            "fixture assertions precede the blob runner floor",
        ),
        OrderedCheck(
            "tests/Lazily.Tests/CodecConformanceTests.cs",
            r"prose\.VerifyProse\((?:JsonFixture|MsgPackFixture)\)",
            r"Assert\.Equal\(3,\s*replayed",
            "fixture assertions precede each codec runner floor",
            paired=True,
        ),
    ),
}


def _ordering_errors(text: str, check: OrderedCheck) -> list[str]:
    before = list(re.finditer(check.before, text, re.MULTILINE))
    after = list(re.finditer(check.after, text, re.MULTILINE))
    if not before or not after:
        missing = []
        if not before:
            missing.append("fixture/work anchor")
        if not after:
            missing.append("runner/assertion anchor")
        return [f"missing {' and '.join(missing)}"]
    if check.paired:
        if len(before) != len(after):
            return [f"anchor count differs ({len(before)} before, {len(after)} after)"]
        pairs = zip(before, after)
    else:
        if len(before) != 1 or len(after) != 1:
            return [f"anchors are not unique ({len(before)} before, {len(after)} after)"]
        pairs = ((before[0], after[0]),)
    return [
        f"pair {index} is reversed"
        for index, (first, second) in enumerate(pairs, start=1)
        if first.end() > second.start()
    ]


def run_binding(binding: str, root: Path) -> list[str]:
    errors: list[str] = []
    for check in CHECKS[binding]:
        path = root / check.path
        if not path.is_file():
            errors.append(f"{check.path}: missing file")
            continue
        for error in _ordering_errors(path.read_text(encoding="utf-8"), check):
            errors.append(f"{check.path}: {check.description}: {error}")
    return errors


def self_test() -> list[str]:
    check = OrderedCheck("fixture", r"fixture\.finish\(\)", r"runner_floor\(\)", "self-test")
    paired = OrderedCheck(
        "fixture",
        r"fixture\.finish\(\)",
        r"runner_floor\(\)",
        "paired self-test",
        paired=True,
    )
    failures: list[str] = []
    if _ordering_errors("fixture.finish(); runner_floor();", check):
        failures.append("accepted ordering was rejected")
    if not _ordering_errors("runner_floor(); fixture.finish();", check):
        failures.append("reversed ordering was accepted")
    if _ordering_errors(
        "fixture.finish(); runner_floor(); fixture.finish(); runner_floor();", paired
    ):
        failures.append("accepted paired ordering was rejected")
    if not _ordering_errors(
        "runner_floor(); fixture.finish(); fixture.finish(); runner_floor();", paired
    ):
        failures.append("reversed paired ordering was accepted")
    return failures


def consumption_errors(
    binding: str | None,
    *,
    self_test_mode: bool,
    root: Path | None = None,
) -> list[str]:
    script = Path(__file__).with_name("check-assert-with-consumption.py")
    command = [sys.executable, str(script)]
    if self_test_mode:
        command.append("--self-test")
    else:
        assert binding is not None
        assert root is not None
        command.extend(("--binding", binding, "--root", str(root)))
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode == 0:
        return []
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if not output:
        output = f"callback-consumption guard exited {result.returncode} without diagnostics"
    return output.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", choices=sorted(CHECKS))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        errors = self_test()
        errors.extend(consumption_errors(None, self_test_mode=True))
        label = "self-test"
    elif args.binding:
        root = args.root.resolve()
        errors = run_binding(args.binding, root)
        errors.extend(
            consumption_errors(
                args.binding,
                self_test_mode=False,
                root=root,
            )
        )
        label = f"{args.binding} ({len(CHECKS[args.binding])} checks)"
    else:
        parser.error("choose --self-test or --binding")

    if errors:
        for error in errors:
            print(f"assertion ordering error: {error}", file=sys.stderr)
        return 1
    print(f"assertion ordering OK: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
