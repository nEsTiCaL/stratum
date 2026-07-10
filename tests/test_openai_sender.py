"""OpenAICompatSender (I-3.7): OpenAI-kompatibler Endpunkt (interner vLLM).

Reine det-Suite gegen httpx.MockTransport (kein Netz): Request-Aufbau
(Messages, max_tokens, chat_template_kwargs, Auth-Header), Antwort-
Normalisierung (content/usage, Reasoning-Sonderfall content=null) und
Fehler-Mapping (Transient/Context/hart).
"""

from __future__ import annotations

import json

import httpx
import pytest

from core.cloud_adapter import CloudRequest, TransientCloudError
from core.openai_sender import OpenAICompatSender
from core.validator import ContextExceededError

_BASE = "http://llm.test/v1"


def _request(**overrides) -> CloudRequest:
    defaults = dict(model_id="test-model", tail="frage")
    defaults.update(overrides)
    return CloudRequest(**defaults)


def _ok_body(content="antwort", *, reasoning=None, prompt_tokens=10, completion=5):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return {
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion},
    }


def _sender_with(handler) -> OpenAICompatSender:
    transport = httpx.MockTransport(handler)
    return OpenAICompatSender(_BASE, client=httpx.Client(transport=transport))


class TestRequestBuild:
    def test_payload_and_url(self):
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=_ok_body())

        _sender_with(handler).send(_request(max_tokens=1234))
        assert seen["url"] == f"{_BASE}/chat/completions"
        assert seen["body"]["model"] == "test-model"
        assert seen["body"]["max_tokens"] == 1234
        assert seen["body"]["messages"] == [{"role": "user", "content": "frage"}]
        # ohne enable_thinking-Vorgabe: Server-Default unangetastet
        assert "chat_template_kwargs" not in seen["body"]

    def test_cache_prefix_prepended_and_system_message(self):
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=_ok_body())

        _sender_with(handler).send(
            _request(system="rolle", cache_prefix="STABIL\n", tail="frage")
        )
        msgs = seen["body"]["messages"]
        assert msgs[0] == {"role": "system", "content": "rolle"}
        # Praefix ZUERST (stabiler Anteil vorn -> vLLM-Prefix-Cache trifft).
        assert msgs[1] == {"role": "user", "content": "STABIL\nfrage"}

    def test_thinking_flag_and_api_key(self):
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["auth"] = req.headers.get("authorization")
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=_ok_body())

        transport = httpx.MockTransport(handler)
        sender = OpenAICompatSender(
            _BASE + "/",  # trailing slash wird normalisiert
            api_key="geheim",
            enable_thinking=False,
            client=httpx.Client(transport=transport),
        )
        sender.send(_request())
        assert seen["auth"] == "Bearer geheim"
        assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}


class TestResponseParse:
    def test_text_and_usage(self):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_ok_body("hallo", prompt_tokens=12, completion=100)
            )

        resp = _sender_with(handler).send(_request())
        assert resp.text == "hallo"
        assert resp.input_tokens == 12
        assert resp.output_tokens == 100
        assert resp.cache_read_tokens == 0

    def test_reasoning_cutoff_yields_empty_text(self):
        # Reasoning-Modell + max_tokens im Denken erschoepft: content=null,
        # Denken in message.reasoning -> leerer Text (Validator behandelt als
        # fail), KEIN Crash und KEIN Reasoning-Leak in den Antworttext.
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body(None, reasoning="denke noch"))

        resp = _sender_with(handler).send(_request())
        assert resp.text == ""


class TestListModels:
    def test_returns_served_model_ids(self):
        # Discovery: die deployment-private Modell-ID kommt vom Server selbst
        # (GET /v1/models), nicht aus dem Repo.
        def handler(req: httpx.Request) -> httpx.Response:
            assert str(req.url) == f"{_BASE}/models"
            return httpx.Response(
                200, json={"object": "list", "data": [{"id": "served-model"}]}
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            models = OpenAICompatSender.list_models(_BASE + "/", client=client)
        assert models == ["served-model"]

    def test_unreachable_returns_empty(self):
        def handler(_req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("weg")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            assert OpenAICompatSender.list_models(_BASE, client=client) == []


class TestErrorMapping:
    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_transient_statuses(self, status):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text="ueberlastet")

        with pytest.raises(TransientCloudError):
            _sender_with(handler).send(_request())

    def test_transport_error_is_transient(self):
        def handler(_req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("verbindung weg")

        with pytest.raises(TransientCloudError):
            _sender_with(handler).send(_request())

    def test_context_exceeded_maps_to_context_error(self):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "This model's maximum context length is 100000"
                    }
                },
            )

        with pytest.raises(ContextExceededError):
            _sender_with(handler).send(_request())

    def test_other_client_error_is_hard(self):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": {"message": "bad request"}})

        with pytest.raises(RuntimeError, match="bad request"):
            _sender_with(handler).send(_request())
