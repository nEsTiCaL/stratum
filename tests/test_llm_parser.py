"""Tests fuer core/llm_parser.py (I-2.5)."""

from __future__ import annotations

from core.llm_parser import parse_llm_response


class TestFullFormat:
    def test_all_sections_parsed(self):
        raw = (
            "MODEL:\nphi4-mini\n\n"
            "CONTENT:\nDies ist die Hauptantwort.\n\n"
            "FINDINGS:\n- Bug auf Zeile 42\n\n"
            "RISKS:\n- SQL-Injection moeglich\n\n"
            "RECOMMENDATIONS:\n- Input validieren\n"
        )
        p = parse_llm_response(raw)
        assert p.model_self_reported == "phi4-mini"
        assert "Hauptantwort" in p.text
        assert p.findings is not None and "Bug" in p.findings
        assert p.risks is not None and "SQL" in p.risks
        assert p.recommendations is not None and "validieren" in p.recommendations

    def test_model_value_inline(self):
        raw = "MODEL: phi4-mini\nCONTENT:\nAntwort hier"
        p = parse_llm_response(raw)
        assert p.model_self_reported == "phi4-mini"
        assert p.text == "Antwort hier"

    def test_none_keyword_becomes_null(self):
        raw = (
            "CONTENT:\nHauptantwort\n"
            "FINDINGS:\nnone\n"
            "RISKS:\nnone\n"
            "RECOMMENDATIONS:\nnone\n"
        )
        p = parse_llm_response(raw)
        assert p.text == "Hauptantwort"
        assert p.findings is None
        assert p.risks is None
        assert p.recommendations is None

    def test_no_findings_phrase_becomes_null(self):
        raw = "CONTENT:\nAntwort\nFINDINGS:\nno findings\n"
        p = parse_llm_response(raw)
        assert p.findings is None

    def test_dash_becomes_null(self):
        raw = "CONTENT:\nAntwort\nRISKS:\n-\n"
        p = parse_llm_response(raw)
        assert p.risks is None


class TestFallback:
    def test_no_labels_returns_whole_text_as_content(self):
        raw = "Das ist eine einfache Antwort ohne Labels."
        p = parse_llm_response(raw)
        assert p.text == raw.strip()
        assert p.model_self_reported is None
        assert p.findings is None
        assert p.risks is None
        assert p.recommendations is None

    def test_empty_input_returns_empty_text(self):
        p = parse_llm_response("")
        assert p.text == ""
        assert p.model_self_reported is None

    def test_only_content_label(self):
        raw = "CONTENT:\nNur Inhalt, keine weiteren Sections."
        p = parse_llm_response(raw)
        assert "Inhalt" in p.text
        assert p.findings is None
        assert p.risks is None
        assert p.recommendations is None

    def test_model_and_content_only(self):
        raw = "MODEL: qwen3-8b\nCONTENT:\nKurze Antwort."
        p = parse_llm_response(raw)
        assert p.model_self_reported == "qwen3-8b"
        assert p.text == "Kurze Antwort."
        assert p.findings is None


class TestCaseInsensitive:
    def test_lowercase_labels(self):
        raw = "content:\nAntwort\nfindings:\nnone"
        p = parse_llm_response(raw)
        assert "Antwort" in p.text
        assert p.findings is None

    def test_mixed_case_labels(self):
        raw = "Content:\nAntwort\nFindings:\n- Etwas gefunden"
        p = parse_llm_response(raw)
        assert p.text == "Antwort"
        assert p.findings == "- Etwas gefunden"


class TestMultiline:
    def test_multiline_content(self):
        raw = "CONTENT:\nZeile 1\nZeile 2\nZeile 3\nFINDINGS:\nnone"
        p = parse_llm_response(raw)
        assert "Zeile 1" in p.text
        assert "Zeile 2" in p.text
        assert "Zeile 3" in p.text

    def test_multiline_findings(self):
        raw = "CONTENT:\nHauptantwort\nFINDINGS:\n- Fund 1\n- Fund 2\n- Fund 3\n"
        p = parse_llm_response(raw)
        assert p.findings is not None
        assert "Fund 1" in p.findings
        assert "Fund 3" in p.findings

    def test_whitespace_only_section_becomes_null(self):
        raw = "CONTENT:\nAntwort\nFINDINGS:\n   \n"
        p = parse_llm_response(raw)
        assert p.findings is None
