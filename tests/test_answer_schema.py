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
        prompt = build_review_prompt("explain", "file:core/x.py", "x = 1")
        assert "## 1. Struktur & Verantwortlichkeiten" in prompt


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
