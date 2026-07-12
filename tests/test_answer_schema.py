"""E1 #2b: Antwortschema je task_type (document/test_gen != Review-Form).

build_review_prompt waehlt Header/Leitfragen je task_type; build_content splittet
nur review-foermige Antworten in text/findings/recommendations -- document/
test_gen gehen als Ganzes nach content.text.
"""

from __future__ import annotations

from core.review_format import build_content, build_review_prompt

_REVIEW_RESPONSE = (
    "## 1. Struktur & Verantwortlichkeiten\n"
    "Die Datei macht X.\n"
    "## 2. Fehlerbehandlung & Robustheit\n"
    "Y wird abgefangen.\n"
    "## 3. Bugs & Schwachstellen\n"
    "Ein Off-by-one in Z.\n"
    "## 4. Design & Verbesserungsvorschlaege\n"
    "Extrahiere Helfer H.\n"
)


class TestPromptSchemaSelection:
    def test_review_keeps_four_headings(self):
        prompt = build_review_prompt("review", "file:core/x.py", "x = 1")
        assert "## 1. Struktur & Verantwortlichkeiten" in prompt
        assert "## 3. Bugs & Schwachstellen" in prompt

    def test_document_uses_doc_schema_not_review(self):
        prompt = build_review_prompt("document", "file:core/x.py", "x = 1")
        # Doku-Schema: keine Review-Ueberschriften, dafuer Signatur-/Docstring-Fokus.
        assert "## 3. Bugs & Schwachstellen" not in prompt
        assert "dokumentierst" in prompt.lower()

    def test_test_gen_requests_single_code_block(self):
        prompt = build_review_prompt("test_gen", "file:core/x.py", "x = 1")
        assert "## 1. Struktur & Verantwortlichkeiten" not in prompt
        assert "codeblock" in prompt.lower()

    def test_unknown_type_falls_back_to_review_header(self):
        # debug ist analytisch und behaelt die Review-4-Ueberschriften-Form.
        prompt = build_review_prompt("debug", "file:core/x.py", "x = 1")
        assert "## 1. Struktur & Verantwortlichkeiten" in prompt


class TestReadIntentSchema:
    """I-UX.3: explain beantwortet die FRAGE des Nutzers (nicht Review-Form),
    summarize gibt einen Ueberblick. Keine 4-Review-Ueberschriften, kein
    Codeblock-Zwang -- die Nutzerfrage ist die primaere Aufgabe, kein 'Hinweis:'."""

    def test_explain_makes_question_primary(self):
        prompt = build_review_prompt(
            "explain",
            "file:core/x.py",
            "x = 1",
            extra_prompt="Was macht die Funktion connect()?",
        )
        assert "Was macht die Funktion connect()?" in prompt
        assert "(beantworte sie direkt):" in prompt  # primaerer Frage-Block
        assert "Hinweis:" not in prompt  # nicht als Randnotiz degradiert
        assert "## 3. Bugs & Schwachstellen" not in prompt  # keine Review-Form
        assert "erklaer" in prompt.lower()

    def test_explain_without_question_explains_purpose(self):
        prompt = build_review_prompt("explain", "file:core/x.py", "x = 1")
        assert "## 1. Struktur & Verantwortlichkeiten" not in prompt
        assert "(beantworte sie direkt):" not in prompt  # kein Frage-Block
        assert "zweck" in prompt.lower()

    def test_summarize_gives_overview_not_review(self):
        prompt = build_review_prompt("summarize", "file:core/x.py", "x = 1")
        assert "## 3. Bugs & Schwachstellen" not in prompt
        assert "ueberblick" in prompt.lower()

    def test_explain_response_whole_to_text(self):
        # Enthaelt die explain-Antwort zufaellig eine Review-artige Ueberschrift,
        # wird sie NICHT in findings gesplittet -- explain ist keine Review-Form.
        answer = (
            "Die Funktion `connect()` oeffnet eine Verbindung.\n"
            "## 3. Bugs & Schwachstellen\n"
            "Das ist hier nur Prosa, keine Findings.\n"
        )
        content = build_content(answer, "explain")
        assert set(content) == {"text"}
        assert "connect()" in content["text"]

    def test_summarize_response_whole_to_text(self):
        content = build_content(
            "Diese Datei kapselt den Client. Kernklasse: `Foo`.", "summarize"
        )
        assert set(content) == {"text"}


class TestContentSchema:
    def test_review_splits_into_fields(self):
        content = build_content(_REVIEW_RESPONSE, "review")
        assert content.get("findings")  # ## 3 -> findings
        assert content.get("recommendations")  # ## 4 -> recommendations
        assert "Struktur" in content["text"]

    def test_none_task_type_keeps_review_split(self):
        # Abwaertskompatibel: ohne task_type wie bisher.
        content = build_content(_REVIEW_RESPONSE)
        assert content.get("findings")
        assert content.get("recommendations")

    def test_document_response_whole_to_text(self):
        # Selbst wenn die Doku eine "Bugs"-artige Zeile enthaelt, wird NICHT
        # in findings gesplittet -- document ist keine Review-Form.
        doc = (
            "### `merge_defaults(values, defaults) -> dict`\n"
            "Vereinigt zwei dicts. Bugs & Schwachstellen: keine.\n"
        )
        content = build_content(doc, "document")
        assert set(content) == {"text"}
        assert "merge_defaults" in content["text"]

    def test_test_gen_code_lands_in_text_fence_stripped(self):
        code = (
            "```python\n"
            "from minicore.report import merge_defaults\n\n\n"
            "def test_no_mutation():\n"
            "    assert True\n"
            "```\n"
        )
        content = build_content(code, "test_gen")
        assert set(content) == {"text"}
        assert content["text"].startswith("from minicore.report import merge_defaults")
        assert "```" not in content["text"]
