"""I-7.5: Apply-Gate (git-frei, ohne Opt-in-Flag).

det-testbar ohne echtes Schreiben (apply_fn/ingest_fn injiziert):
- kein Schreibzugriff ohne confirm / ohne gruenen Report
- Erfolg: apply_fn schreibt, Re-Ingest je geaenderter Datei (invalidate=True)

I-E.1 (apply_confirmed_patches, atomarer Sammel-Apply): gegen tmp_path-Dateien
(die Funktion rechnet ALLE Diffs vor dem ersten Schreibzugriff) -- jede Luecke
(fehlender/unpassender Report, Kontext-Mismatch, Datei-Kollision) laesst den
Workspace byte-identisch.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.apply_gate import apply_confirmed_patch, apply_confirmed_patches
from core.patch_apply import diff_hash

_ROOT = Path(".")


class _Repo:
    """Liefert patch/lint_report je nach Verfuegbarkeit. Der Report stempelt seinen
    input_hash (wie lint_gate) auf report_diff -- Default = der Patch-Diff "D", also
    ein PASSENDER Report; ein abweichender report_diff modelliert den E-14-Fall
    'gruener Alt-Report deckt einen anderen Diff'. no_op=True modelliert den
    legalen No-op-Patch (I-E.17: diff leer, content.no_op)."""

    def __init__(self, *, patch=True, verified=True, report_diff="D", no_op=False):
        content = {"diff": "D", "target_scope": "file:core/x.py"}
        if no_op:
            content = {"diff": "", "no_op": True, "target_scope": "file:core/x.py"}
        self._patch = SimpleNamespace(content=content) if patch else None
        self._report = (
            SimpleNamespace(
                content={"passed": verified},
                provenance=SimpleNamespace(input_hash=diff_hash(report_diff)),
            )
            if verified is not None
            else None
        )

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        if artifact_type == "patch":
            return self._patch
        if artifact_type == "lint_report":
            return self._report
        return None


def _spy_apply(ok=True, changed=("core/x.py",)):
    calls = []

    def apply_fn(diff, root):
        calls.append((diff, root))
        return (ok, "applied" if ok else "conflict", list(changed) if ok else [])

    return apply_fn, calls


def _spy_ingest():
    calls = []

    def ingest_fn(repo, root, rel, *, invalidate=False):
        calls.append({"rel": rel, "invalidate": invalidate})

    return ingest_fn, calls


class TestGate:
    def test_not_confirmed_no_write(self):
        apply_fn, acalls = _spy_apply()
        r = apply_confirmed_patch(
            _Repo(), _ROOT, "file:core/x.py", confirmed=False, apply_fn=apply_fn
        )
        assert not r.applied and acalls == []

    def test_no_patch_no_write(self):
        apply_fn, acalls = _spy_apply()
        r = apply_confirmed_patch(
            _Repo(patch=False),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            apply_fn=apply_fn,
        )
        assert not r.applied and acalls == []

    def test_unverified_patch_no_write(self):
        apply_fn, acalls = _spy_apply()
        r = apply_confirmed_patch(
            _Repo(verified=False),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            apply_fn=apply_fn,
        )
        assert not r.applied and acalls == []
        assert "lint_report" in r.reason

    def test_missing_report_no_write(self):
        apply_fn, acalls = _spy_apply()
        r = apply_confirmed_patch(
            _Repo(verified=None),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            apply_fn=apply_fn,
        )
        assert not r.applied and acalls == []

    def test_report_for_other_diff_no_write(self):
        # E-14-Kern: ein GRUENER lint_report, der aber einen anderen Diff geprueft
        # hat (input_hash-Mismatch), darf den aktuellen Patch NICHT verifizieren.
        apply_fn, acalls = _spy_apply()
        r = apply_confirmed_patch(
            _Repo(verified=True, report_diff="ein-anderer-diff"),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            apply_fn=apply_fn,
        )
        assert not r.applied and acalls == []
        assert "lint_report" in r.reason


class TestApplySuccess:
    def test_applies_and_reingests(self):
        apply_fn, acalls = _spy_apply(changed=("core/x.py",))
        ingest, icalls = _spy_ingest()
        r = apply_confirmed_patch(
            _Repo(),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            apply_fn=apply_fn,
            ingest_fn=ingest,
        )
        assert r.applied
        assert acalls == [("D", _ROOT)]  # apply_fn mit dem Diff + root
        assert icalls == [{"rel": "core/x.py", "invalidate": True}]  # I-4.4

    def test_multi_file_reingests_each(self):
        apply_fn, _ = _spy_apply(changed=("core/x.py", "core/y.py"))
        ingest, icalls = _spy_ingest()
        r = apply_confirmed_patch(
            _Repo(),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            apply_fn=apply_fn,
            ingest_fn=ingest,
        )
        assert r.applied
        assert [c["rel"] for c in icalls] == ["core/x.py", "core/y.py"]

    def test_apply_failure_reports_no_reingest(self):
        apply_fn, acalls = _spy_apply(ok=False)
        ingest, icalls = _spy_ingest()
        r = apply_confirmed_patch(
            _Repo(),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            apply_fn=apply_fn,
            ingest_fn=ingest,
        )
        assert not r.applied
        assert acalls  # apply versucht
        assert icalls == []  # aber kein Re-Ingest nach Fehler


# --------------------------------------------------------------------------
# I-E.1: apply_confirmed_patches -- atomarer Sammel-Apply (alle oder keiner)
# --------------------------------------------------------------------------


def _mkdiff(name: str, old: str, new: str) -> str:
    return f"--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-{old}\n+{new}\n"


class _MultiRepo:
    """patch + lint_report je scope. Wert je scope: Diff-String ODER kompletter
    content-dict (no_op-Patches, I-E.17). report_for: scope -> Diff, den der
    gruene Report deckt (None -> kein Report; fehlt der Eintrag -> Report deckt
    den eigenen Patch-Diff = verifiziert)."""

    def __init__(self, patches: dict, report_for: dict | None = None):
        self._patches = patches
        self._report_for = report_for or {}

    def _content(self, scope):
        val = self._patches[scope]
        return val if isinstance(val, dict) else {"diff": val}

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        if artifact_type == "patch" and scope in self._patches:
            return SimpleNamespace(content=self._content(scope))
        if artifact_type == "lint_report" and scope in self._patches:
            covered = self._report_for.get(scope, self._content(scope)["diff"])
            if covered is None:
                return None
            return SimpleNamespace(
                content={"passed": True},
                provenance=SimpleNamespace(input_hash=diff_hash(covered)),
            )
        return None


def _fanout_root(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("b\n", encoding="utf-8")
    return tmp_path


class TestApplyConfirmedPatches:
    def test_applies_all_and_reingests_each(self, tmp_path):
        root = _fanout_root(tmp_path)
        repo = _MultiRepo(
            {
                "file:a.py": _mkdiff("a.py", "a", "a2"),
                "file:b.py": _mkdiff("b.py", "b", "b2"),
            }
        )
        ingest, icalls = _spy_ingest()
        r = apply_confirmed_patches(
            repo, root, ["file:a.py", "file:b.py"], confirmed=True, ingest_fn=ingest
        )
        assert r.applied
        assert (root / "a.py").read_text(encoding="utf-8") == "a2\n"
        assert (root / "b.py").read_text(encoding="utf-8") == "b2\n"
        assert [c["rel"] for c in icalls] == ["a.py", "b.py"]
        assert all(c["invalidate"] for c in icalls)

    def test_not_confirmed_writes_nothing(self, tmp_path):
        root = _fanout_root(tmp_path)
        repo = _MultiRepo({"file:a.py": _mkdiff("a.py", "a", "a2")})
        r = apply_confirmed_patches(repo, root, ["file:a.py"], confirmed=False)
        assert not r.applied
        assert (root / "a.py").read_text(encoding="utf-8") == "a\n"

    def test_empty_scopes_rejected(self, tmp_path):
        r = apply_confirmed_patches(_MultiRepo({}), tmp_path, [], confirmed=True)
        assert not r.applied

    def test_one_missing_patch_blocks_all(self, tmp_path):
        root = _fanout_root(tmp_path)
        repo = _MultiRepo({"file:a.py": _mkdiff("a.py", "a", "a2")})  # b fehlt
        r = apply_confirmed_patches(
            repo, root, ["file:a.py", "file:b.py"], confirmed=True
        )
        assert not r.applied
        assert "file:b.py" in r.reason
        assert (root / "a.py").read_text(encoding="utf-8") == "a\n"  # NICHT geschrieben

    def test_one_unverified_patch_blocks_all(self, tmp_path):
        # E-14 je Kind: b.py hat nur einen gruenen Report fuer einen ANDEREN Diff.
        root = _fanout_root(tmp_path)
        repo = _MultiRepo(
            {
                "file:a.py": _mkdiff("a.py", "a", "a2"),
                "file:b.py": _mkdiff("b.py", "b", "b2"),
            },
            report_for={"file:b.py": "ein-anderer-diff"},
        )
        r = apply_confirmed_patches(
            repo, root, ["file:a.py", "file:b.py"], confirmed=True
        )
        assert not r.applied
        assert "file:b.py" in r.reason and "lint_report" in r.reason
        assert (root / "a.py").read_text(encoding="utf-8") == "a\n"

    def test_one_context_mismatch_blocks_all(self, tmp_path):
        # Atomaritaet: Patch b passt nicht (Workspace-Drift) -> auch der gueltige
        # Patch a wird NICHT geschrieben (alle oder keiner).
        root = _fanout_root(tmp_path)
        repo = _MultiRepo(
            {
                "file:a.py": _mkdiff("a.py", "a", "a2"),
                "file:b.py": _mkdiff("b.py", "WRONG", "b2"),
            }
        )
        r = apply_confirmed_patches(
            repo, root, ["file:a.py", "file:b.py"], confirmed=True
        )
        assert not r.applied
        assert "file:b.py" in r.reason
        assert (root / "a.py").read_text(encoding="utf-8") == "a\n"
        assert (root / "b.py").read_text(encoding="utf-8") == "b\n"

    def test_cross_patch_file_collision_blocks_all(self, tmp_path):
        # Zwei Kinder patchen DIESELBE Datei (E-10-Muster): beide Diffs sind gegen
        # den Original-Inhalt gerechnet -> last-wins waere still falsch. Ehrlich
        # abbrechen, nichts schreiben.
        root = _fanout_root(tmp_path)
        repo = _MultiRepo(
            {
                "file:a.py": _mkdiff("a.py", "a", "a2"),
                "file:dup.py": _mkdiff("a.py", "a", "a3"),
            }
        )
        r = apply_confirmed_patches(
            repo, root, ["file:a.py", "file:dup.py"], confirmed=True
        )
        assert not r.applied
        assert "Kollision" in r.reason
        assert (root / "a.py").read_text(encoding="utf-8") == "a\n"

    def test_no_op_children_skipped_rest_applied(self, tmp_path):
        # I-E.17: legale No-op-Kinder blockieren den Sammel-Apply nicht -- sie
        # brauchen weder Report noch Schreibzugriff, der Rest laeuft atomar.
        root = _fanout_root(tmp_path)
        repo = _MultiRepo(
            {
                "file:a.py": _mkdiff("a.py", "a", "a2"),
                "file:b.py": {"diff": "", "no_op": True},
            }
        )
        ingest, icalls = _spy_ingest()
        r = apply_confirmed_patches(
            repo, root, ["file:a.py", "file:b.py"], confirmed=True, ingest_fn=ingest
        )
        assert r.applied and r.written
        assert "No-op" in r.reason
        assert (root / "a.py").read_text(encoding="utf-8") == "a2\n"
        assert (root / "b.py").read_text(encoding="utf-8") == "b\n"  # unangetastet
        assert [c["rel"] for c in icalls] == ["a.py"]

    def test_all_no_op_succeeds_without_write(self, tmp_path):
        root = _fanout_root(tmp_path)
        repo = _MultiRepo({"file:a.py": {"diff": "", "no_op": True}})
        r = apply_confirmed_patches(repo, root, ["file:a.py"], confirmed=True)
        assert r.applied
        assert r.written is False
        assert "No-op" in r.reason
        assert (root / "a.py").read_text(encoding="utf-8") == "a\n"


class TestSingleNoOpApply:
    def test_no_op_patch_applies_without_write_or_report(self):
        # I-E.17 Einzelpfad (/api/apply auf ein No-op-Kind): ehrlich erfolgreich,
        # written=False, kein Report-Zwang (es gibt nichts zu verifizieren).
        apply_fn, acalls = _spy_apply()
        r = apply_confirmed_patch(
            _Repo(no_op=True, verified=None),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            apply_fn=apply_fn,
        )
        assert r.applied
        assert r.written is False
        assert "No-op" in r.reason
        assert acalls == []  # kein Schreibversuch


# --------------------------------------------------------------------------
# REST /api/apply + /api/patches (nur die Ablehnungen -- der Erfolgspfad wuerde
# den echten Tree beruehren und ist oben mit Fakes gedeckt)
# --------------------------------------------------------------------------

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.models.provenance_schema import Provenance  # noqa: E402
from core.models.result_det_schema import ResultDet  # noqa: E402
from core.models.result_prob_schema import ResultProb  # noqa: E402
from core.queue import Queue  # noqa: E402
from core.repository import Repository  # noqa: E402
from interfaces.webgui.app import create_app  # noqa: E402
from tests.conftest import TEST_API_KEY  # noqa: E402

_AUTH = {"Authorization": f"Bearer {TEST_API_KEY}"}
_SCOPE = "file:core/x.py"


def _prov(artifact_type, producer_class, input_hash="i"):
    return Provenance(
        schema_version="1",
        source_hash="h",
        input_hash=input_hash,
        producer="p",
        producer_version="1",
        producer_class=producer_class,
        timestamp="2026-07-04T00:00:00+00:00",
        artifact_type=artifact_type,
        scope=_SCOPE,
    )


def _put_patch(repo):
    repo.put_artifact(
        ResultProb(
            artifact_type="patch",
            scope=_SCOPE,
            content={"diff": "D", "target_scope": _SCOPE},
            confidence=0.8,
            provenance=_prov("patch", "prob"),
        )
    )


def _put_report(repo, passed, *, diff="D"):
    # Der Report stempelt seinen input_hash auf den geprueften Diff (wie lint_gate);
    # Default = der Patch-Diff "D" aus _put_patch -> patch-gekoppelt gruen.
    repo.put_artifact(
        ResultDet(
            artifact_type="lint_report",
            scope=_SCOPE,
            content={"passed": passed, "applied": True, "summary": "x", "commands": []},
            provenance=_prov("lint_report", "det", input_hash=diff_hash(diff)),
        )
    )


@pytest.fixture
def apply_client(conn, tmp_path):
    # source_root = leeres tmp-Verzeichnis (nie der echte Tree); kein
    # workspace_base -> Apply zielt auf source_root.
    repo = Repository(conn)
    app = create_app(Queue(conn), repo, source_root=tmp_path)
    with TestClient(app) as c:
        yield c, repo


class TestApplyRest:
    def test_apply_without_confirm_rejected(self, apply_client):
        client, repo = apply_client
        _put_patch(repo)
        _put_report(repo, passed=True)
        r = client.post(
            "/api/apply", json={"scope": _SCOPE, "confirm": False}, headers=_AUTH
        )
        assert r.status_code == 409

    def test_apply_unverified_rejected(self, apply_client):
        client, repo = apply_client
        _put_patch(repo)
        _put_report(repo, passed=False)  # roter Report
        r = client.post(
            "/api/apply", json={"scope": _SCOPE, "confirm": True}, headers=_AUTH
        )
        assert r.status_code == 409
        assert "lint_report" in r.json()["detail"]

    def test_apply_requires_auth(self, apply_client):
        client, _ = apply_client
        r = client.post("/api/apply", json={"scope": _SCOPE, "confirm": True})
        assert r.status_code == 401

    def test_patches_lists_verified_flag(self, apply_client):
        client, repo = apply_client
        _put_patch(repo)
        _put_report(repo, passed=True)
        r = client.get("/api/patches", headers=_AUTH)
        assert r.status_code == 200
        patches = r.json()["patches"]
        assert {"scope": _SCOPE, "verified": True} in patches

    def test_patches_verified_false_for_stale_report(self, apply_client):
        # E-14: ein gruener lint_report zu einem FRUEHEREN Diff verifiziert den
        # aktuellen Patch NICHT (patch-gekoppelt statt scope-weit).
        client, repo = apply_client
        _put_report(repo, passed=True, diff="alt-diff")  # gruen, aber fuer "alt-diff"
        _put_patch(repo)  # aktueller Patch-Diff "D"
        r = client.get("/api/patches", headers=_AUTH)
        assert r.status_code == 200
        assert {"scope": _SCOPE, "verified": False} in r.json()["patches"]
