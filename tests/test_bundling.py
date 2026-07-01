"""I-3.2: Context-Bundling + deterministische Serialisierung.

Akzeptanz (det): gleicher scope zweimal serialisiert -> byte-identisch;
Core vs. variabel getrennt; Hotspots sind span-genaue Snippets, keine
ganzen Dateien.
"""

from __future__ import annotations

from core.bundling import (
    Bundle,
    TaskContext,
    build_core_bundle,
    select_hotspots,
    serialize_bundle,
    serialize_core_bundle,
    serialize_task_context,
)
from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.repository import Repository


def _prov(*, scope: str, artifact_type: str, input_hash: str = "in-001") -> Provenance:
    return Provenance(
        schema_version="1",
        source_hash="commit-abc",
        input_hash=input_hash,
        producer="tree-sitter-py",
        producer_version="0.21.0",
        producer_class="det",
        timestamp="2026-06-29T12:00:00+00:00",
        artifact_type=artifact_type,
        scope=scope,
    )


def _det(scope: str, artifact_type: str, content: dict) -> ResultDet:
    return ResultDet(
        artifact_type=artifact_type,
        scope=scope,
        content=content,
        provenance=_prov(scope=scope, artifact_type=artifact_type),
    )


def _seed_auth_module(repo: Repository) -> None:
    repo.put_artifact(
        _det(
            "file:src/auth.py",
            "symbol_index",
            {
                "symbols": [
                    {
                        "kind": "function",
                        "name": "login",
                        "span": [1, 5],
                        "parent": None,
                        "docstring": None,
                        "signature": "(user)",
                        "visibility": "public",
                    },
                    {
                        "kind": "function",
                        "name": "_hash",
                        "span": [7, 9],
                        "parent": None,
                        "docstring": None,
                        "signature": "(pw)",
                        "visibility": "private",
                    },
                ]
            },
        )
    )
    repo.put_artifact(
        _det(
            "file:src/auth.py",
            "dependency_graph",
            {"imports": [{"target": "hashlib", "kind": "module"}]},
        )
    )
    repo.put_artifact(
        _det(
            "file:src/auth.py",
            "call_graph",
            {
                "calls": [
                    {
                        "caller": "login",
                        "callee_raw": "_hash",
                        "callee_ref": "_hash",
                        "span": [3, 3],
                        "confidence": 0.5,
                    },
                    {
                        "caller": "login",
                        "callee_raw": "unknown_thing",
                        "callee_ref": None,
                        "span": [4, 4],
                        "confidence": 0.0,
                    },
                ]
            },
        )
    )


class TestCoreBundleDeterminism:
    def test_same_scope_serialized_twice_is_byte_identical(self, conn):
        repo = Repository(conn)
        _seed_auth_module(repo)

        first = serialize_core_bundle(build_core_bundle(repo, ["file:src/auth.py"]))
        second = serialize_core_bundle(build_core_bundle(repo, ["file:src/auth.py"]))

        assert first == second

    def test_scope_order_does_not_affect_bytes(self, conn):
        repo = Repository(conn)
        _seed_auth_module(repo)
        repo.put_artifact(_det("file:src/util.py", "symbol_index", {"symbols": []}))

        a = serialize_core_bundle(
            build_core_bundle(repo, ["file:src/auth.py", "file:src/util.py"])
        )
        b = serialize_core_bundle(
            build_core_bundle(repo, ["file:src/util.py", "file:src/auth.py"])
        )

        assert a == b

    def test_missing_artifact_type_is_omitted_not_error(self, conn):
        repo = Repository(conn)
        repo.put_artifact(
            _det("file:src/only_symbols.py", "symbol_index", {"symbols": []})
        )

        bundle = build_core_bundle(repo, ["file:src/only_symbols.py"])

        assert "dependency_graph" not in bundle.artifacts["file:src/only_symbols.py"]
        assert "call_graph" not in bundle.artifacts["file:src/only_symbols.py"]

    def test_module_overview_aggregates_symbol_count(self, conn):
        repo = Repository(conn)
        _seed_auth_module(repo)

        bundle = build_core_bundle(repo, ["file:src/auth.py"])

        assert bundle.module_overview == {
            "files": ["file:src/auth.py"],
            "symbol_count": 2,
        }


class TestCoreVsVariableSeparation:
    def test_task_context_alone_does_not_change_core_bytes(self, conn):
        repo = Repository(conn)
        _seed_auth_module(repo)
        core = build_core_bundle(repo, ["file:src/auth.py"])
        core_bytes = serialize_core_bundle(core)

        ctx_a = TaskContext(question="why is login slow?")
        ctx_b = TaskContext(question="explain this", prior_result={"confidence": 0.4})

        assert serialize_task_context(ctx_a) != serialize_task_context(ctx_b)
        assert serialize_core_bundle(core) == core_bytes

    def test_full_bundle_concatenates_three_segments_in_order(self, conn):
        repo = Repository(conn)
        _seed_auth_module(repo)
        core = build_core_bundle(repo, ["file:src/auth.py"])
        ctx = TaskContext(question="q")

        bundle = Bundle(core=core, task_context=ctx, hotspots=())
        out = serialize_bundle(bundle)

        assert out.startswith(serialize_core_bundle(core))
        assert serialize_task_context(ctx) in out


class TestHotspotSelection:
    _SOURCE = (
        "def login(user):\n"  # line 1
        "    ok = True\n"  # line 2
        "    _hash(user)\n"  # line 3
        "    unknown_thing()\n"  # line 4
        "    return ok\n"  # line 5
        "\n"  # line 6
        "def _hash(pw):\n"  # line 7
        "    return pw\n"  # line 8
        "\n"  # line 9
    )

    def _source_provider(self, scope: str) -> str:
        assert scope == "file:src/auth.py"
        return self._SOURCE

    def test_only_resolved_calls_become_hotspots(self, conn):
        repo = Repository(conn)
        _seed_auth_module(repo)

        hotspots = select_hotspots(repo, ["file:src/auth.py"], self._source_provider)

        assert len(hotspots) == 1
        assert hotspots[0].scope == "file:src/auth.py"

    def test_hotspot_is_span_genuine_not_whole_file(self, conn):
        repo = Repository(conn)
        _seed_auth_module(repo)

        hotspots = select_hotspots(repo, ["file:src/auth.py"], self._source_provider)

        hotspot = hotspots[0]
        assert hotspot.start_line == 3
        assert hotspot.end_line == 3
        assert hotspot.snippet == "    _hash(user)"
        assert hotspot.snippet != self._SOURCE

    def test_max_hotspots_caps_result(self, conn):
        repo = Repository(conn)
        _seed_auth_module(repo)

        hotspots = select_hotspots(
            repo, ["file:src/auth.py"], self._source_provider, max_hotspots=0
        )

        assert hotspots == ()

    def test_no_call_graph_artifact_yields_no_hotspots(self, conn):
        repo = Repository(conn)

        hotspots = select_hotspots(repo, ["file:src/does_not_exist.py"], lambda _s: "")

        assert hotspots == ()
