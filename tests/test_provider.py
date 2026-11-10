"""AI provider switch: Anthropic by default, any OpenAI-compatible endpoint when a base URL is set."""
import pytest

from brandguard import llm


class _Resp:
    status_code = 200
    headers = {}

    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def test_openai_compatible_request_and_reply(monkeypatch):
    monkeypatch.setenv("BRANDGUARD_LLM_BASE_URL", "https://api.example.in/v1/")
    monkeypatch.setenv("BRANDGUARD_LLM_API_KEY", "k-123")
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return _Resp({"choices": [{"message": {"content": "[]"}}]})

    monkeypatch.setattr("requests.post", post)
    assert llm.default_call("SYS", "USER", "m1") == "[]"
    assert seen["url"] == "https://api.example.in/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer k-123"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYS"} and seen["body"]["model"] == "m1"


def test_anthropic_is_still_the_default(monkeypatch):
    monkeypatch.delenv("BRANDGUARD_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-1")
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(url=url, headers=headers)
        return _Resp({"content": [{"text": "[]"}]})

    monkeypatch.setattr("requests.post", post)
    assert llm.default_call("S", "U", "m") == "[]" and seen["url"] == llm.API_URL and "x-api-key" in seen["headers"]


def test_availability_rules(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "BRANDGUARD_LLM_API_KEY", "BRANDGUARD_MODEL", "BRANDGUARD_LLM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    assert not llm.ai_available()
    monkeypatch.setenv("BRANDGUARD_LLM_BASE_URL", "https://x.in/v1")
    monkeypatch.setenv("BRANDGUARD_LLM_API_KEY", "k")
    assert not llm.ai_available()          # model name missing
    monkeypatch.setenv("BRANDGUARD_MODEL", "some-model")
    assert llm.ai_available()
    monkeypatch.setenv("BRANDGUARD_LLM", "off")
    assert not llm.ai_available()


def test_plain_http_endpoints_are_refused(monkeypatch):
    monkeypatch.setenv("BRANDGUARD_LLM_BASE_URL", "http://api.example.in/v1")
    with pytest.raises(ValueError):
        llm._chat_url()


def test_openai_provider_turns_reasoning_off_and_refuses_cut_off_output(monkeypatch):
    monkeypatch.setenv("BRANDGUARD_LLM_BASE_URL", "https://bharatcode.ai/api/model/v1")
    monkeypatch.setenv("BRANDGUARD_LLM_API_KEY", "k")
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(json)
        r = _Resp({"choices": [{"finish_reason": "length", "message": {"content": "[{\"rule"}}]})
        r.headers = {"x-request-id": "rq-9"}
        return r

    monkeypatch.setattr("requests.post", post)
    with pytest.raises(ValueError, match="rq-9"):
        llm.default_call("S", "U", "qwen-3.8-27b")
    assert sent["reasoning_effort"] == "none" and sent["max_tokens"] == 4000
