from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "sync-conformance-fixtures.mjs"
MIRRORS = (
    ("lazily-py", "tests/conformance"),
    ("lazily-dart", "test/conformance"),
    ("lazily-rs", "tests/conformance"),
    ("lazily-go", "test/conformance"),
)
FIXTURE = Path("collections/example.json")


def run_sync_tool(
    spec_root: Path, siblings_root: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "node",
            str(SCRIPT),
            *arguments,
            "--spec-root",
            str(spec_root),
            "--siblings-root",
            str(siblings_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def seed_all_mirrors(tmp_path: Path, content: str = '{"value":1}\n') -> tuple[Path, Path]:
    spec_root = tmp_path / "lazily-spec"
    canonical = spec_root / "conformance" / FIXTURE
    canonical.parent.mkdir(parents=True)
    canonical.write_text(content)

    for binding, mirror_dir in MIRRORS:
        mirror = tmp_path / binding / mirror_dir / FIXTURE
        mirror.parent.mkdir(parents=True)
        mirror.write_text(content)

    return spec_root, tmp_path


def test_check_detects_byte_drift_and_sync_repairs_it(tmp_path: Path) -> None:
    spec_root, siblings_root = seed_all_mirrors(tmp_path)
    initial = run_sync_tool(
        spec_root, siblings_root, "--check", "--require-all"
    )
    assert initial.returncode == 0, initial.stderr
    assert "4 binding(s)" in initial.stdout

    drifted = tmp_path / "lazily-py" / "tests/conformance" / FIXTURE
    drifted.write_text('{"value": 1}\n')

    check = run_sync_tool(spec_root, siblings_root, "--check", "--require-all")
    assert check.returncode == 1
    assert "lazily-py: collections/example.json drifted" in check.stderr

    sync = run_sync_tool(spec_root, siblings_root, "--sync", "--require-all")
    assert sync.returncode == 0, sync.stderr
    assert drifted.read_bytes() == (
        spec_root / "conformance" / FIXTURE
    ).read_bytes()


def test_check_rejects_orphaned_mirror_fixture(tmp_path: Path) -> None:
    spec_root, siblings_root = seed_all_mirrors(tmp_path)
    orphan = tmp_path / "lazily-rs" / "tests/conformance/removed.json"
    orphan.write_text("{}\n")

    result = run_sync_tool(spec_root, siblings_root, "--check", "--require-all")

    assert result.returncode == 1
    assert "removed.json has no canonical counterpart" in result.stderr


def test_missing_siblings_are_explicitly_optional_or_required(tmp_path: Path) -> None:
    spec_root = tmp_path / "lazily-spec"
    canonical = spec_root / "conformance" / FIXTURE
    canonical.parent.mkdir(parents=True)
    canonical.write_text("{}\n")
    mirror = tmp_path / "lazily-py" / "tests/conformance" / FIXTURE
    mirror.parent.mkdir(parents=True)
    mirror.write_text("{}\n")

    optional = run_sync_tool(spec_root, tmp_path, "--check")
    assert optional.returncode == 0, optional.stderr
    assert "lazily-dart: mirror absent" in optional.stdout

    required = run_sync_tool(spec_root, tmp_path, "--check", "--require-all")
    assert required.returncode == 1
    assert "lazily-dart: mirror absent" in required.stderr
