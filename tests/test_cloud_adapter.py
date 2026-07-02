"""I-3.1: Cloud-Adapter (Multi-Provider, Anthropic zuerst) — det-Akzeptanz.

Gegen aufgenommene Antworten (ReplayCloudSender), kein realer Egress:
Kostenrechnung Input/Output, logischer-Name->ID-Mapping je Anbieter,
Cache-Markierung am stabilen Core Bundle, Retry, Antwort->ResultProb.
"""

from __future__ import annotations

import pytest

from core.cloud_adapter import (
    CLOUD_MODEL_SPECS,
    CloudAdapter,
    CostRecord,
    RawCloudResponse,
    ReplayCloudSender,
    TransientCloudError,
    build_messages,
    cloud_model_factory,
    compute_cost,
    resolve_spec,
)
from core.router import Provider
from core.validator import Validator


class TestLogicalNameMapping:
    def test_anthropic_names_resolve_to_concrete_ids(self):
        assert resolve_spec("haiku").model_id == "claude-haiku-4-5"
        assert resolve_spec("sonnet").model_id == "claude-sonnet-4-6"
        assert resolve_spec("opus").model_id == "claude-opus-4-8"

    def test_all_anthropic_specs_are_anthropic_provider(self):
        for name in ("haiku", "sonnet", "opus"):
            assert CLOUD_MODEL_SPECS[name].provider is Provider.anthropic

    def test_unknown_or_optin_provider_resolves_none(self):
        # OpenAI/Google/Gratis sind opt-in und noch nicht verdrahtet.
        assert resolve_spec("gpt") is None
        assert resolve_spec("gemini-flash") is None
        assert resolve_spec("groq-llama") is None
        assert resolve_spec("does-not-exist") is None


class TestCostAccounting:
    def test_input_output_cost(self):
        spec = resolve_spec("sonnet")  # 3.00 in / 15.00 out je 1M
        rec = compute_cost(spec, input_tokens=1_000_000, output_tokens=1_000_000)
        assert rec.cost_usd == pytest.approx(18.00)
        assert rec.model_id == "claude-sonnet-4-6"
        assert rec.input_tokens == 1_000_000

    def test_cache_read_and_write_multipliers(self):
        spec = resolve_spec("haiku")  # 1.00 in / 5.00 out je 1M
        rec = compute_cost(
            spec,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=1_000_000,  # 0.1x input
            cache_write_tokens=1_000_000,  # 1.25x input
        )
        assert rec.cost_usd == pytest.approx(0.10 + 1.25)


class TestCacheMarking:
    def test_core_prefix_gets_cache_control(self):
        _system, messages = build_messages(None, "STABLE-CORE", "variable-tail")
        core_block = messages[0]["content"][0]
        assert core_block["text"] == "STABLE-CORE"
        assert core_block["cache_control"] == {"type": "ephemeral"}

    def test_core_block_byte_identical_across_tails(self):
        # Cache-Pflicht: gleicher Core -> identischer, markierter Block,
        # unabhaengig vom variablen tail (Prefix-Match).
        _s1, m1 = build_messages("sys", "STABLE-CORE", "frage A")
        _s2, m2 = build_messages("sys", "STABLE-CORE", "voellig andere frage B")
        assert m1[0]["content"][0] == m2[0]["content"][0]

    def test_no_prefix_is_plain_prompt(self):
        system, messages = build_messages(None, None, "nur der prompt")
        assert system is None
        assert messages == [{"role": "user", "content": "nur der prompt"}]


class TestCloudAdapterComplete:
    def test_returns_text_and_reports_cost(self):
        costs: list[CostRecord] = []
        sender = ReplayCloudSender(
            {"do it": RawCloudResponse("done", input_tokens=100, output_tokens=20)}
        )
        adapter = CloudAdapter(
            spec=resolve_spec("opus"), sender=sender, on_cost=costs.append
        )
        assert adapter.complete("do it") == "done"
        assert len(costs) == 1
        # opus 5.00 in / 25.00 out je 1M
        assert costs[0].cost_usd == pytest.approx((100 * 5.00 + 20 * 25.00) / 1_000_000)

    def test_no_cost_callback_is_optional(self):
        sender = ReplayCloudSender(
            {"x": RawCloudResponse("y", input_tokens=1, output_tokens=1)}
        )
        adapter = CloudAdapter(spec=resolve_spec("haiku"), sender=sender)
        assert adapter.complete("x") == "y"


class TestRetry:
    def test_retries_transient_then_succeeds(self):
        sender = ReplayCloudSender(
            {"q": RawCloudResponse("ok", input_tokens=1, output_tokens=1)},
            fail_first_n=2,
        )
        adapter = CloudAdapter(spec=resolve_spec("haiku"), sender=sender, max_retries=2)
        assert adapter.complete("q") == "ok"
        assert sender.calls == 3  # 2 Fehlschlaege + 1 Erfolg

    def test_raises_when_retries_exhausted(self):
        sender = ReplayCloudSender(
            {"q": RawCloudResponse("ok", input_tokens=1, output_tokens=1)},
            fail_first_n=5,
        )
        adapter = CloudAdapter(spec=resolve_spec("haiku"), sender=sender, max_retries=2)
        with pytest.raises(TransientCloudError):
            adapter.complete("q")
        assert sender.calls == 3  # 1 + max_retries


class TestModelFactory:
    def test_factory_returns_adapter_for_anthropic_name(self):
        sender = ReplayCloudSender({})
        factory = cloud_model_factory(sender)
        adapter = factory("sonnet")
        assert isinstance(adapter, CloudAdapter)
        assert adapter.spec.model_id == "claude-sonnet-4-6"

    def test_factory_returns_none_for_optin_or_local_name(self):
        factory = cloud_model_factory(ReplayCloudSender({}))
        assert factory("gpt") is None  # opt-in, unverdrahtet
        assert factory("phi4-mini") is None  # lokal, kein Cloud-Spec


_RESULT_PROB_LABEL = """\
MODEL: claude-opus-4-8

CONTENT:
Die Authentifizierungsschicht verwaltet Login-Flows und Session-Tokens.

FINDINGS:
none

RISKS:
none

RECOMMENDATIONS:
none
"""


class TestResponseToResultProb:
    def test_recorded_response_validates_as_result_prob(self):
        # Antwort -> Validator: Cloud-Adapter liefert Label-Prefix-Format,
        # Validator prueft nur ob CONTENT nicht leer ist.
        from core.router import TaskType

        sender = ReplayCloudSender(
            {"summarize auth": RawCloudResponse(_RESULT_PROB_LABEL, 500, 120)}
        )
        adapter = CloudAdapter(spec=resolve_spec("opus"), sender=sender)
        text = adapter.complete("summarize auth")

        result = Validator().validate(text, TaskType.summarize, producer_class="prob")
        assert result.passed is True
