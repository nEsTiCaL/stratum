"""I-D.0: Dev-Harness CLI gegen echtes Postgres (ueber das Repository-Interface).

Fixture ingestieren, Befehle ausfuehren, Text- und JSON-Ausgabe pruefen. Die
Schale bekommt das Repository injiziert (kein eigener connect noetig).
"""

from __future__ import annotations

import json

import pytest

from core.ingest import ingest_content
from core.repository import Repository
from interfaces.devcli import main

SRC = (
    "import os\n"
    "\n"
    "def login(user):\n"
    "    return user\n"
    "\n"
    "class Auth:\n"
    "    def check(self):\n"
    "        return True\n"
)


@pytest.fixture
def repo(conn):
    r = Repository(conn)
    ingest_content(r, "src/auth.py", SRC, source_hash="h1")
    return r


class TestIndex:
    def test_human(self, repo, capsys):
        rc = main(["index", "src/auth.py"], repo=repo)
        out = capsys.readouterr().out
        assert rc == 0
        assert "file:src/auth.py" in out
        assert "login" in out
        assert "Auth" in out
        assert "check" in out

    def test_json(self, repo, capsys):
        rc = main(["index", "src/auth.py", "--json"], repo=repo)
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["scope"] == "file:src/auth.py"
        names = {s["name"] for s in data["symbols"]}
        assert {"login", "Auth", "check"} <= names

    def test_absent_returns_1(self, repo, capsys):
        rc = main(["index", "src/nope.py"], repo=repo)
        assert rc == 1
        assert "nicht indiziert" in capsys.readouterr().err


class TestSymbolLookup:
    def test_hit(self, repo, capsys):
        rc = main(["symbol_lookup", "login"], repo=repo)
        out = capsys.readouterr().out
        assert rc == 0
        assert "file:src/auth.py" in out
        assert "login" in out

    def test_json(self, repo, capsys):
        rc = main(["symbol_lookup", "login", "--json"], repo=repo)
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["scope"] == "file:src/auth.py"
        assert data[0]["name"] == "login"

    def test_kind_filter(self, repo, capsys):
        rc = main(["symbol_lookup", "Auth", "--kind", "class", "--json"], repo=repo)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data) == 1
        assert data[0]["kind"] == "class"

    def test_no_match_is_ok(self, repo, capsys):
        rc = main(["symbol_lookup", "missing"], repo=repo)
        out = capsys.readouterr().out
        assert rc == 0
        assert "kein Treffer" in out


class TestDependencyMap:
    def test_human(self, repo, capsys):
        rc = main(["dependency_map", "src/auth.py"], repo=repo)
        out = capsys.readouterr().out
        assert rc == 0
        assert "file:src/auth.py" in out
        assert "os" in out

    def test_json(self, repo, capsys):
        rc = main(["dependency_map", "src/auth.py", "--json"], repo=repo)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["scope"] == "file:src/auth.py"
        assert any(imp["raw"] == "os" for imp in data["imports"])
