"""SQLite store contract registry (``#lazilysqlitestoreopen``).

``sqlite-stores.json`` pins the cross-binding SQLite store contract (explicit
busy timeout, no deferred read-then-write transactions) and every binding's
declaration of whether -- and where -- it meets it. These tests validate the
registry on its own and prove that ``scripts/check-sqlite-stores.py``, which
verifies the declarations against the sibling checkouts, fails closed on each
way a binding can drift.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = json.loads((ROOT / "sqlite-stores.json").read_text())
SCHEMA = json.loads((ROOT / "schemas" / "sqlite-stores.json").read_text())

_spec = importlib.util.spec_from_file_location(
    "check_sqlite_stores", ROOT / "scripts" / "check-sqlite-stores.py"
)
assert _spec is not None and _spec.loader is not None
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

#: The bindings spec CI clones (`.github/workflows/ci.yml`, "Fetch sibling
#: binding ledgers"). Every one must declare its SQLite store, or "none".
BINDINGS = ["rs", "py", "kt", "js", "dart", "zig", "go", "cpp", "cs", "gd"]


def test_registry_validates_against_its_schema() -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate(REGISTRY)


def test_registry_is_self_consistent_and_complete() -> None:
    assert checker.registry_problems(REGISTRY, BINDINGS) == []


def test_contract_matches_lazily_rs_reference() -> None:
    """lazily-rs 29fde5a: `SQLITE_STORE_BUSY_TIMEOUT = Duration::from_secs(30)`."""
    assert REGISTRY["contract"]["busy_timeout_ms"] == 30_000
    assert REGISTRY["contract"]["write_lock_acquisition"] == "autocommit_or_begin_immediate"
    (rs,) = [b for b in REGISTRY["bindings"] if b["binding"] == "rs"]
    assert "Duration::from_secs(30)" in rs["sqlite"]["busy_timeout"]["declaration"]


def test_ci_clones_every_registered_binding() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert f"for repo in {' '.join(BINDINGS)}; do" in workflow
    assert "scripts/check-sqlite-stores.py --require-all" in workflow


# ---------------------------------------------------------------------------
# The checker fails closed on every kind of drift
# ---------------------------------------------------------------------------

_OWNED_SOURCE = """\
use rusqlite::Connection;
pub const SQLITE_STORE_BUSY_TIMEOUT: Duration = Duration::from_secs(30);
pub struct SqliteStore {}
#[test] fn open_installs_the_busy_timeout() {}
#[test] fn two_writers_rollback() {}
#[test] fn two_writers_wal() {}
"""


def _owned_entry() -> dict:
    return {
        "binding": "xx",
        "repo": "lazily-xx",
        "scan_roots": ["src"],
        "sqlite": {
            "connection": "owned",
            "store": "SqliteStore",
            "driver_files": ["src/store.rs"],
            "busy_timeout": {
                "ms": 30000,
                "file": "src/store.rs",
                "declaration": "pub const SQLITE_STORE_BUSY_TIMEOUT: Duration = Duration::from_secs(30);",
                "test": "open_installs_the_busy_timeout",
            },
            "two_writer_tests": {
                "file": "src/store.rs",
                "names": ["two_writers_rollback", "two_writers_wal"],
            },
            "deferred_transaction_guard": {
                "file": "clippy.toml",
                "tokens": ['path = "rusqlite::Connection::transaction"'],
            },
        },
    }


def _owned_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "lazily-xx"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "store.rs").write_text(_OWNED_SOURCE)
    (repo / "src" / "lib.rs").write_text("pub mod store;\n")
    (repo / "clippy.toml").write_text(
        'disallowed-methods = [{ path = "rusqlite::Connection::transaction" }]\n'
    )
    return repo


def _problems(entry: dict, repo: Path) -> list[str]:
    return checker.binding_problems(entry, repo, REGISTRY["drivers"])


def test_a_conforming_owned_store_passes(tmp_path: Path) -> None:
    assert _problems(_owned_entry(), _owned_repo(tmp_path)) == []


def test_a_changed_busy_timeout_reddens(tmp_path: Path) -> None:
    repo = _owned_repo(tmp_path)
    (repo / "src" / "store.rs").write_text(
        _OWNED_SOURCE.replace("from_secs(30)", "from_secs(5)")
    )
    assert any("lacks the declared busy timeout" in p for p in _problems(_owned_entry(), repo))


def test_a_declared_timeout_off_contract_reddens() -> None:
    registry = copy.deepcopy(REGISTRY)
    entry = _owned_entry()
    entry["sqlite"]["busy_timeout"]["ms"] = 5000
    registry["bindings"].append(entry)
    assert any("!= the contract's 30000 ms" in p for p in checker.registry_problems(registry))


def test_a_dropped_two_writer_test_reddens(tmp_path: Path) -> None:
    repo = _owned_repo(tmp_path)
    (repo / "src" / "store.rs").write_text(
        _OWNED_SOURCE.replace("two_writers_wal", "something_else")
    )
    assert any("has no test two_writers_wal" in p for p in _problems(_owned_entry(), repo))


def test_a_dropped_deferred_transaction_ban_reddens(tmp_path: Path) -> None:
    repo = _owned_repo(tmp_path)
    (repo / "clippy.toml").write_text("disallowed-methods = []\n")
    assert any("deferred-transaction guard" in p for p in _problems(_owned_entry(), repo))


def test_an_undeclared_driver_file_reddens(tmp_path: Path) -> None:
    repo = _owned_repo(tmp_path)
    (repo / "src" / "other.rs").write_text("use rusqlite::Connection;\n")
    assert any(
        "src/other.rs uses ['rusqlite'] but is not a declared driver file" in p
        for p in _problems(_owned_entry(), repo)
    )


@pytest.mark.parametrize(
    ("rel", "source", "driver"),
    [
        ("src/a.rs", "use rusqlite::Connection;\n", "rusqlite"),
        ("src/a.py", "import sqlite3\n", "python_sqlite3"),
        ("src/a.go", 'import _ "modernc.org/sqlite"\n', "go_sqlite"),
        ("src/A.kt", "import androidx.room.Dao\n", "jvm_sqlite"),
        ("src/a.js", 'import Database from "better-sqlite3";\n', "js_sqlite"),
        ("src/a.cpp", "#include <sqlite3.h>\n", "c_sqlite"),
        ("src/A.cs", "using Microsoft.Data.Sqlite;\n", "dotnet_sqlite"),
        ("src/a.dart", "import 'package:sqlite3/sqlite3.dart';\n", "dart_sqlite"),
        ("src/a.zig", 'const c = @cImport(@cInclude("sqlite3.h"));\n', "c_sqlite"),
        ("src/a.gd", "var db = SQLite.new()\n", "godot_sqlite"),
    ],
)
def test_a_none_binding_that_grows_a_sqlite_path_reddens(
    tmp_path: Path, rel: str, source: str, driver: str
) -> None:
    repo = tmp_path / "lazily-xx"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "lib.txt.rs").write_text("// plugs a durable store (agent-doc: SQLite)\n")
    entry = {"binding": "xx", "repo": "lazily-xx", "scan_roots": ["src"], "sqlite": "none"}
    assert _problems(entry, repo) == [], "prose mentioning SQLite is not a driver"
    (repo / rel).write_text(source)
    problems = _problems(entry, repo)
    assert len(problems) == 1 and f"['{driver}']" in problems[0], problems


def test_a_scan_of_nothing_reddens(tmp_path: Path) -> None:
    repo = tmp_path / "lazily-xx"
    repo.mkdir()
    entry = {"binding": "xx", "repo": "lazily-xx", "scan_roots": ["src"], "sqlite": "none"}
    assert any("hold no source files" in p for p in _problems(entry, repo))


def test_a_host_store_must_state_the_obligation(tmp_path: Path) -> None:
    repo = tmp_path / "lazily-xx"
    (repo / "src").mkdir(parents=True)
    store = repo / "src" / "Outbox.kt"
    store.write_text("class RoomStore\n")
    entry = {
        "binding": "xx",
        "repo": "lazily-xx",
        "scan_roots": ["src"],
        "sqlite": {
            "connection": "host",
            "store": "RoomStore",
            "obligation": {"file": "src/Outbox.kt", "marker": "#lazilysqlitestoreopen"},
        },
    }
    assert any("does not state the host obligation" in p for p in _problems(entry, repo))
    store.write_text("/** busy timeout >= 30 s (#lazilysqlitestoreopen) */\nclass RoomStore\n")
    assert _problems(entry, repo) == []


def test_require_all_reddens_a_missing_sibling(tmp_path: Path, capsys) -> None:
    assert checker.main(["--bindings-root", str(tmp_path), "--require-all"]) == 1
    assert "sibling checkout" in capsys.readouterr().err


def test_sparse_paths_cover_every_declared_file() -> None:
    for entry in REGISTRY["bindings"]:
        paths = checker.sparse_paths(entry)
        sqlite = entry["sqlite"]
        if isinstance(sqlite, dict) and sqlite["connection"] == "owned":
            for rel in [sqlite["two_writer_tests"]["file"], *sqlite["driver_files"]]:
                parent = str(Path(rel).parent)
                assert parent == "." or parent in paths, (entry["binding"], rel, paths)
