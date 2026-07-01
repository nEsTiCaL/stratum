"""I-3.4: Detektor-Bibliothek (regex/entropy).

Akzeptanz: praeaparierte Secrets erkannt (Golden); sauberes Bundle PASS;
Secret -> REDACT mit Platzhalter; Sensitivitaets-Ableitung korrekt.
"""

from __future__ import annotations

import pytest

from core.detector import DetectorResult, detect, redact_bytes
from core.secret_scan import Sensitivity

# ---------------------------------------------------------------------------
# Fake-Keys (alle erfunden, keine echten Credentials)
# ---------------------------------------------------------------------------
_ANTHROPIC_KEY = "sk-ant-api03-fakeKeyABCDEFGHIJKLMNOP12345678901234567890"
_OPENAI_KEY = "sk-proj-fakeKeyABCDEFGHIJKLMNOP123456789012345678901234567"
_AWS_KEY = "AKIAJFAKE01234567890"  # AKIA + 16 uppercase/digit chars
_GITHUB_TOKEN = "ghp_fakeTokenABCDEFGHIJKLMNOP1234567890ABCDE"
_GOOGLE_KEY = "AIzafakeKey0123456789ABCDEFGHIJKLMNOPQR"  # AIza + 35 chars
_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
# 32 vollstaendig unterschiedliche Zeichen -> Shannon-Entropie = log2(32) ~= 5 bit/char
_HIGH_ENTROPY = "A3kR9xPmQ7yZvW2sT8nL6oU4iC1dH5jF"

_CLEAN = "def greet(name: str) -> str:\n    return f'Hello, {name}!'"
_EMAIL_TEXT = "kontakt: max.mustermann@example.com -- fuer Rueckfragen"


class TestGoldenHighSensitivity:
    """Bekannte Secret-Patterns werden als sensitivity=high erkannt."""

    @pytest.mark.parametrize(
        "rule_prefix, text",
        [
            ("anthropic_api_key", f'ANTHROPIC_API_KEY = "{_ANTHROPIC_KEY}"'),
            ("openai_api_key", f'key = "{_OPENAI_KEY}"'),
            ("aws_access_key_id", f"AccessKeyId: {_AWS_KEY}"),
            ("github_token", f"token: {_GITHUB_TOKEN}"),
            ("google_api_key", f"api_key = '{_GOOGLE_KEY}'"),
            ("jwt", f"Authorization: Bearer {_JWT}"),
            ("high_entropy_string", f"secret = '{_HIGH_ENTROPY}'"),
        ],
    )
    def test_detected_as_high(self, rule_prefix: str, text: str):
        result = detect(text)
        assert result.sensitivity is Sensitivity.high, (
            f"expected high for {rule_prefix}"
        )
        rules = {m.rule for m in result.matches}
        prefix0 = rule_prefix.split("_")[0]
        assert any(r.startswith(prefix0) or r == rule_prefix for r in rules), (
            f"expected rule {rule_prefix!r} in {rules}"
        )


class TestCleanContent:
    def test_clean_code_is_none(self):
        result = detect(_CLEAN)
        assert result.sensitivity is Sensitivity.none
        assert result.matches == ()
        assert result.stub is False

    def test_empty_bytes(self):
        result = detect(b"")
        assert result.sensitivity is Sensitivity.none


class TestLowSensitivity:
    def test_email_is_low(self):
        result = detect(_EMAIL_TEXT)
        assert result.sensitivity is Sensitivity.low
        assert any(m.rule == "email" for m in result.matches)

    def test_email_overridden_by_key(self):
        text = f"{_EMAIL_TEXT} key={_ANTHROPIC_KEY}"
        result = detect(text)
        assert result.sensitivity is Sensitivity.high


class TestDetectorResult:
    def test_scanner_name(self):
        result = detect(_CLEAN)
        assert result.scanner == "regex-entropy-v1"

    def test_stub_false(self):
        result = detect(_CLEAN)
        assert result.stub is False

    def test_returns_DetectorResult(self):
        result = detect(_CLEAN)
        assert isinstance(result, DetectorResult)


class TestRedactBytes:
    def test_replaces_key_with_placeholder(self):
        text = f'key = "{_ANTHROPIC_KEY}"'
        content = text.encode()
        result = detect(content)
        redacted = redact_bytes(content, result.matches)
        assert _ANTHROPIC_KEY.encode() not in redacted
        assert b"[REDACTED:" in redacted

    def test_clean_content_unchanged(self):
        content = _CLEAN.encode()
        result = detect(content)
        assert redact_bytes(content, result.matches) == content

    def test_placeholder_format(self):
        content = f"x = {_AWS_KEY}".encode()
        result = detect(content)
        high = tuple(m for m in result.matches if m.sensitivity is Sensitivity.high)
        redacted = redact_bytes(content, high)
        assert b"[REDACTED:aws_access_key_id]" in redacted

    def test_multiple_keys_all_redacted(self):
        text = f"a={_ANTHROPIC_KEY} b={_AWS_KEY}"
        content = text.encode()
        result = detect(content)
        redacted = redact_bytes(content, result.matches)
        assert _ANTHROPIC_KEY.encode() not in redacted
        assert _AWS_KEY.encode() not in redacted

    def test_no_matches_returns_original(self):
        content = b"nothing here"
        assert redact_bytes(content, ()) is content


class TestBytesInput:
    def test_bytes_decoded_correctly(self):
        content = f"key={_GITHUB_TOKEN}".encode()
        result = detect(content)
        assert result.sensitivity is Sensitivity.high
