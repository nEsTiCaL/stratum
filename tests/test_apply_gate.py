"""I-7.5: Apply-Gate (git-frei, ohne Opt-in-Flag).

det-testbar ohne echtes Schreiben (apply_fn/ingest_fn injiziert):
- kein Schreibzugriff ohne confirm / ohne gruenen Report
- Erfolg: apply_fn schreibt, Re-Ingest je geaenderter Datei (invalidate=True)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.apply_gate import apply_confirmed_patch

_ROOT = Path(".")


class _Repo:
    """Liefert patch/verify_report je nach Verfuegbarkeit."""

    def __init__(self, *, patch=True, verified=True):
        self._patch = (
            SimpleNamespace(content={"diff": "D", "target_scope": "file:core/x.py"})
            if patch
            else None
        )
        self._report = (
            SimpleNamespace(content={"passed": verified})
            if verified is not None
            else None
        )

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        if artifact_type == "patch":
            return self._patch
        if artifact_type == "verify_report":
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
        assert "verify_report" in r.reason

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


def _prov(artifact_type, producer_class):
    return Provenance(
        schema_version="1",
        source_hash="h",
        input_hash="i",
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


def _put_report(repo, passed):
    repo.put_artifact(
        ResultDet(
            artifact_type="verify_report",
            scope=_SCOPE,
            content={"passed": passed, "applied": True, "summary": "x", "commands": []},
            provenance=_prov("verify_report", "det"),
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
        assert "verify_report" in r.json()["detail"]

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
