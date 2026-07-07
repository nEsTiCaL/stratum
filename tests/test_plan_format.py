"""Tests fuer core/plan_format.py (Markdown-Zerlegungsformat, det/TDD).

Prompt-Bau + toleranter Antwort-Parser (Markdown-Neuformat, JSON-Altformat,
Fences, Prosa-Zeilen). Kein Modell, kein Postgres.
"""

from __future__ import annotations

import json

import pytest

from core.plan_format import (
    PLANNABLE_TASK_TYPES,
    build_decompose_prompt,
    parse_plan_response,
)

# ---------------------------------------------------------------------------
# build_decompose_prompt()
# ---------------------------------------------------------------------------


def test_prompt_contains_headings_and_task():
    p = build_decompose_prompt("Baue ein Dashboard")
    assert "## 1. Verstaendnis" in p
    assert "## 2. Nicht abgedeckt" in p
    assert "## 3. Schritte" in p
    assert p.rstrip().endswith("Baue ein Dashboard")


def test_prompt_lists_all_plannable_task_types_with_description():
    p = build_decompose_prompt("x")
    for name, desc in PLANNABLE_TASK_TYPES:
        assert f"- {name}: {desc}" in p


def test_prompt_offers_implement_and_fix_but_not_verify():
    # implement/fix sind planbar (Schritt 7); verify haengt automatisch an
    # ihnen (Template-Registry) und darf nicht angeboten werden.
    names = [n for n, _ in PLANNABLE_TASK_TYPES]
    assert "implement" in names
    assert "fix" in names
    assert "verify" not in names


def test_prompt_demands_no_json():
    assert "JSON" not in build_decompose_prompt("x")


# ---------------------------------------------------------------------------
# parse_plan_response(): Markdown-Neuformat
# ---------------------------------------------------------------------------

_MD_FULL = """\
## 1. Verstaendnis
Du willst ein neues Login-Modul, danach Tests dazu.

## 2. Nicht abgedeckt
- "so schnell wie moeglich": kein planbarer Arbeitsschritt

## 3. Schritte
1. implement file:auth/login.py
2. test_gen file:tests/test_login.py (nach: 1)
"""


def test_markdown_full_roundtrip():
    d = parse_plan_response(_MD_FULL)
    assert d["understanding"].startswith("Du willst ein neues Login-Modul")
    assert d["not_covered"] == [
        '"so schnell wie moeglich": kein planbarer Arbeitsschritt'
    ]
    assert d["goals"] == [
        {"task_type": "implement", "scope": "file:auth/login.py", "depends_on": []},
        {
            "task_type": "test_gen",
            "scope": "file:tests/test_login.py",
            "depends_on": [0],
        },
    ]


def test_markdown_not_covered_keine_means_empty():
    d = parse_plan_response(
        "## 1. Verstaendnis\nAlles klar.\n## 2. Nicht abgedeckt\n- keine\n"
        "## 3. Schritte\n1. review file:core/x.py"
    )
    assert d["not_covered"] == []
    assert len(d["goals"]) == 1


def test_markdown_deps_are_one_based_step_numbers():
    d = parse_plan_response(
        "## 3. Schritte\n"
        "1. architecture module:dashboard\n"
        "2. implement file:dashboard/app.js (nach: 1)\n"
        "3. explain module:dashboard (nach: 1, 2)"
    )
    assert d["goals"][1]["depends_on"] == [0]
    assert d["goals"][2]["depends_on"] == [0, 1]


def test_markdown_tolerates_bold_bullets_and_fence():
    raw = (
        "```markdown\n"
        "## Verstaendnis\nOk.\n"
        "## Schritte\n"
        "- **review** `file:core/x.py`\n"
        "* implement file:core/y.py (nach: 1)\n"
        "```"
    )
    d = parse_plan_response(raw)
    assert d["goals"][0] == {
        "task_type": "review",
        "scope": "file:core/x.py",
        "depends_on": [],
    }
    # Ohne explizite Nummer zaehlen die Zeilen 1-basiert durch.
    assert d["goals"][1]["depends_on"] == [0]


def test_markdown_prose_lines_in_schritte_ignored():
    d = parse_plan_response(
        "## 3. Schritte\n"
        "Die folgenden Schritte bauen aufeinander auf.\n"
        "1. review file:core/x.py\n"
        "Danach ist der Plan fertig."
    )
    assert len(d["goals"]) == 1


def test_markdown_unknown_task_type_with_scope_raises():
    with pytest.raises(ValueError, match="unbekannter task_type"):
        parse_plan_response("## 3. Schritte\n1. deploy module:auth")


def test_markdown_unknown_dep_reference_raises():
    with pytest.raises(ValueError, match="unbekannten Schritt"):
        parse_plan_response("## 3. Schritte\n1. review file:x.py (nach: 7)")


def test_markdown_empty_schritte_gives_empty_goals():
    # Ehrlicher Null-Plan: alles in not_covered, keine Schritte.
    d = parse_plan_response(
        "## 1. Verstaendnis\nNicht planbar.\n"
        "## 2. Nicht abgedeckt\n- deploy: kein task_type\n## 3. Schritte"
    )
    assert d["goals"] == []
    assert d["not_covered"] == ["deploy: kein task_type"]


def test_goal_lines_without_headings_recognized():
    # Modell laesst das Geruest weg, liefert aber Schritt-Zeilen -> tolerant.
    d = parse_plan_response(
        "1. review file:core/x.py\n2. explain module:core (nach: 1)"
    )
    assert [g["task_type"] for g in d["goals"]] == ["review", "explain"]
    assert d["understanding"] == ""


def test_garbage_raises_value_error():
    with pytest.raises(ValueError, match="keine Zerlegung"):
        parse_plan_response("Ich kann dazu leider nichts sagen.")


# ---------------------------------------------------------------------------
# parse_plan_response(): JSON-Altformat bleibt toleriert
# ---------------------------------------------------------------------------


def test_json_object_still_accepted():
    raw = json.dumps(
        {
            "understanding": "Auth-Modul.",
            "not_covered": ["deploy: kein task_type"],
            "goals": [{"task_type": "review", "scope": "file:x.py", "depends_on": []}],
        }
    )
    d = parse_plan_response(raw)
    assert d["understanding"] == "Auth-Modul."
    assert d["not_covered"] == ["deploy: kein task_type"]
    assert d["goals"][0]["task_type"] == "review"


def test_json_bare_array_still_accepted():
    d = parse_plan_response('[{"task_type": "explain", "scope": "module:auth"}]')
    assert d["understanding"] == ""
    assert d["goals"][0]["scope"] == "module:auth"


def test_json_in_fence_still_accepted():
    raw = '```json\n[{"task_type": "review", "scope": "file:x.py"}]\n```'
    assert parse_plan_response(raw)["goals"][0]["task_type"] == "review"
