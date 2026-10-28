"""Tests for the LLM client (app.agent.llm).

Every HTTP call goes to httpx.MockTransport (a TEST DOUBLE). No network, no real key.
"""

import json

import httpx
import pytest

from app.agent.llm import (
    ANTHROPIC_VERSION,
    LLMError,
    LLMSettings,
    completer_from_env,
    make_completer,
)

KEY = "sk-test-not-a-real-key"


def transport(status=200, payload=None, seen=None, exc=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if exc is not None:
            raise exc
        return httpx.Response(status, json=payload if payload is not None else {})
    return httpx.MockTransport(handler)


def test_openai_compatible_request_and_reply():
    seen = []
    t = transport(payload={"choices": [{"message": {"content": "hello"}}]}, seen=seen)
    complete = make_completer("openai_compatible", KEY, "gpt-test", transport=t, max_tokens=123)
    assert complete("my prompt") == "hello"
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body == {"model": "gpt-test", "messages": [{"role": "user", "content": "my prompt"}],
                    "temperature": 0, "max_tokens": 123}


def test_openai_compatible_custom_base_url():
    seen = []
    t = transport(payload={"choices": [{"message": {"content": "x"}}]}, seen=seen)
    make_completer("openai_compatible", KEY, "m", base_url="https://api.groq.com/openai/v1/",
                   transport=t)("p")
    assert str(seen[0].url) == "https://api.groq.com/openai/v1/chat/completions"


def test_anthropic_request_and_reply():
    seen = []
    t = transport(payload={"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
                  seen=seen)
    complete = make_completer("anthropic", KEY, "claude-test", transport=t)
    assert complete("p") == "ab"
    req = seen[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == KEY
    assert req.headers["anthropic-version"] == ANTHROPIC_VERSION
    body = json.loads(req.content)
    assert body["model"] == "claude-test" and body["temperature"] == 0
    assert body["messages"] == [{"role": "user", "content": "p"}]


def test_non_200_raises_without_leaking_the_key():
    complete = make_completer("openai_compatible", KEY, "m", transport=transport(status=401))
    with pytest.raises(LLMError) as e:
        complete("p")
    assert "401" in str(e.value) and KEY not in str(e.value)


def test_timeout_raises_llm_error():
    t = transport(exc=httpx.ReadTimeout("slow"))
    with pytest.raises(LLMError, match="timed out"):
        make_completer("anthropic", KEY, "m", transport=t)("p")


def test_network_error_raises_llm_error():
    t = transport(exc=httpx.ConnectError("down"))
    with pytest.raises(LLMError, match="ConnectError"):
        make_completer("anthropic", KEY, "m", transport=t)("p")


def test_malformed_body_raises_llm_error():
    t = transport(payload={"unexpected": True})
    with pytest.raises(LLMError, match="unexpected response"):
        make_completer("openai_compatible", KEY, "m", transport=t)("p")


def test_unknown_provider_or_missing_values_are_rejected():
    with pytest.raises(ValueError):
        make_completer("magic", KEY, "m")
    with pytest.raises(ValueError):
        make_completer("anthropic", "", "m")
    with pytest.raises(ValueError):
        make_completer("anthropic", KEY, "")


def test_from_env_disabled_when_provider_empty(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert completer_from_env(LLMSettings(_env_file=None)) is None


def test_from_env_misconfigured_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODEL", "m")
    assert completer_from_env(LLMSettings(_env_file=None)) is None
    monkeypatch.setenv("LLM_PROVIDER", "not-a-provider")
    monkeypatch.setenv("LLM_API_KEY", KEY)
    assert completer_from_env(LLMSettings(_env_file=None)) is None


def test_from_env_configured_returns_a_callable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_API_KEY", KEY)
    monkeypatch.setenv("LLM_MODEL", "m")
    assert callable(completer_from_env(LLMSettings(_env_file=None)))
