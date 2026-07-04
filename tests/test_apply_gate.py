"""I-7.5: Apply-Gate (HARTES GATE, fail-safe).

det-testbar ohne echtes git (git_apply/ingest_fn injiziert):
- kein Schreibzugriff ohne confirm / ohne Policy-Opt-in / ohne gruenen Report
- Erfolg: git apply + Re-Ingest (invalidate=True); Reihenfolge der Gates
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.apply_gate import ApplyPolicy, apply_confirmed_patch

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


def _spy_git(rc=0):
    calls = []

    def git_apply(diff, root):
        calls.append((diff, root))
        return rc, "" if rc == 0 else "conflict"

    return git_apply, calls


def _spy_ingest():
    calls = []

    def ingest_fn(repo, root, rel, *, invalidate=False):
        calls.append({"rel": rel, "invalidate": invalidate})

    return ingest_fn, calls


_ALLOW = ApplyPolicy(allow_apply=True)


class TestFailSafe:
    def test_not_confirmed_no_write(self):
        git, gcalls = _spy_git()
        r = apply_confirmed_patch(
            _Repo(),
            _ROOT,
            "file:core/x.py",
            confirmed=False,
            policy=_ALLOW,
            git_apply=git,
        )
        assert not r.applied and gcalls == []

    def test_policy_blocks_no_write(self):
        git, gcalls = _spy_git()
        r = apply_confirmed_patch(
            _Repo(),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            policy=ApplyPolicy(allow_apply=False),
            git_apply=git,
        )
        assert not r.applied and gcalls == []
        assert "fail-safe" in r.reason

    def test_no_patch_no_write(self):
        git, gcalls = _spy_git()
        r = apply_confirmed_patch(
            _Repo(patch=False),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            policy=_ALLOW,
            git_apply=git,
        )
        assert not r.applied and gcalls == []

    def test_unverified_patch_no_write(self):
        git, gcalls = _spy_git()
        r = apply_confirmed_patch(
            _Repo(verified=False),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            policy=_ALLOW,
            git_apply=git,
        )
        assert not r.applied and gcalls == []
        assert "verify_report" in r.reason

    def test_missing_report_no_write(self):
        git, gcalls = _spy_git()
        r = apply_confirmed_patch(
            _Repo(verified=None),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            policy=_ALLOW,
            git_apply=git,
        )
        assert not r.applied and gcalls == []


class TestApplySuccess:
    def test_applies_and_reingests(self):
        git, gcalls = _spy_git()
        ingest, icalls = _spy_ingest()
        r = apply_confirmed_patch(
            _Repo(),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            policy=_ALLOW,
            git_apply=git,
            ingest_fn=ingest,
        )
        assert r.applied
        assert gcalls == [("D", _ROOT)]  # git apply mit dem Diff
        assert icalls == [{"rel": "core/x.py", "invalidate": True}]  # I-4.4

    def test_git_apply_failure_reports_no_reingest(self):
        git, gcalls = _spy_git(rc=1)
        ingest, icalls = _spy_ingest()
        r = apply_confirmed_patch(
            _Repo(),
            _ROOT,
            "file:core/x.py",
            confirmed=True,
            policy=_ALLOW,
            git_apply=git,
            ingest_fn=ingest,
        )
        assert not r.applied
        assert gcalls  # apply versucht
        assert icalls == []  # aber kein Re-Ingest nach Fehler


# --------------------------------------------------------------------------
# REST /api/apply + /api/patches (nur die fail-safe-Ablehnungen -- der
# Erfolgspfad wuerde den echten Tree beruehren und ist oben mit Fakes gedeckt)
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
    # source_root = leeres tmp-Verzeichnis (nie der echte Tree); Policy erlaubt,
    # damit die Ablehnungen NICHT nur an der Policy haengen.
    repo = Repository(conn)
    app = create_app(
        Queue(conn), repo, source_root=tmp_path, apply_policy=ApplyPolicy(True)
    )
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

    def test_default_policy_blocks_even_with_confirm(self, conn, tmp_path):
        # Ohne Opt-in (Default-Policy) blockiert der Gate trotz confirm + gruen.
        repo = Repository(conn)
        _put_patch(repo)
        _put_report(repo, passed=True)
        app = create_app(Queue(conn), repo, source_root=tmp_path)  # fail-safe Default
        with TestClient(app) as client:
            r = client.post(
                "/api/apply", json={"scope": _SCOPE, "confirm": True}, headers=_AUTH
            )
        assert r.status_code == 409
        assert "fail-safe" in r.json()["detail"]

    def test_patches_lists_verified_flag(self, apply_client):
        client, repo = apply_client
        _put_patch(repo)
        _put_report(repo, passed=True)
        r = client.get("/api/patches", headers=_AUTH)
        assert r.status_code == 200
        patches = r.json()["patches"]
        assert {"scope": _SCOPE, "verified": True} in patches
