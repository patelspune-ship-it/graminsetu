import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api_errors import install_error_handlers
from app.llm import LlmError, explain_result, extract_profile
from app.llm.gemini_client import GEMINI_URL
from app.routers import llm as llm_router


def _gemini_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _ok_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200, json=payload, request=httpx.Request("POST", GEMINI_URL)
    )


@pytest.fixture(autouse=True)
def gemini_api_key(monkeypatch):
    monkeypatch.setattr("app.llm.gemini_client.settings.gemini_api_key", "test-key")


def test_explain_result_returns_model_text(monkeypatch):
    captured = {}

    def fake_post(url, params=None, json=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["body"] = json
        return _ok_response(_gemini_response("Your project cost is as given."))

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    result = explain_result({"project_cost_paise": 500_000}, "en")

    assert result == "Your project cost is as given."
    assert captured["url"] == GEMINI_URL
    assert captured["params"] == {"key": "test-key"}
    assert "500000" in captured["body"]["contents"][0]["parts"][0]["text"]
    assert "English" in captured["body"]["systemInstruction"]["parts"][0]["text"]


def test_explain_result_raises_llm_error_without_api_key(monkeypatch):
    monkeypatch.setattr("app.llm.gemini_client.settings.gemini_api_key", None)

    with pytest.raises(LlmError):
        explain_result({}, "en")


def test_explain_result_raises_llm_error_on_http_failure(monkeypatch):
    def fake_post(*args, **kwargs):
        request = httpx.Request("POST", GEMINI_URL)
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    with pytest.raises(LlmError):
        explain_result({}, "hi")


def test_explain_result_raises_llm_error_on_empty_text(monkeypatch):
    def fake_post(*args, **kwargs):
        return _ok_response(_gemini_response("   "))

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    with pytest.raises(LlmError):
        explain_result({}, "mr")


def test_extract_profile_returns_only_stated_fields(monkeypatch):
    payload = {
        "own_capital_paise": 500_000,
        "skills": ["farming", "not_a_real_skill"],
        "premises": "owned",
        "power": None,
    }

    def fake_post(*args, **kwargs):
        return _ok_response(_gemini_response(json.dumps(payload)))

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    result = extract_profile("I have 5000 rupees and I farm on owned land.")

    assert result == {
        "own_capital_paise": 500_000,
        "skills": ["farming"],
        "premises": "owned",
        "power": None,
    }


def test_extract_profile_never_invents_unstated_fields(monkeypatch):
    payload = {
        "own_capital_paise": None,
        "skills": None,
        "premises": None,
        "power": None,
    }

    def fake_post(*args, **kwargs):
        return _ok_response(_gemini_response(json.dumps(payload)))

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    result = extract_profile("hello")

    assert result == {
        "own_capital_paise": None,
        "skills": None,
        "premises": None,
        "power": None,
    }


def test_extract_profile_rejects_out_of_range_or_invalid_model_output(monkeypatch):
    payload = {
        "own_capital_paise": -100,
        "skills": "farming",
        "premises": "made_up",
        "power": "three_phase",
    }

    def fake_post(*args, **kwargs):
        return _ok_response(_gemini_response(json.dumps(payload)))

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    result = extract_profile("some text")

    assert result == {
        "own_capital_paise": None,
        "skills": None,
        "premises": None,
        "power": "three_phase",
    }


def test_extract_profile_raises_llm_error_on_malformed_json(monkeypatch):
    def fake_post(*args, **kwargs):
        return _ok_response(_gemini_response("not json"))

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    with pytest.raises(LlmError):
        extract_profile("some text")


@pytest.fixture
def client():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(llm_router.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_explain_endpoint_returns_502_when_llm_unavailable(client, monkeypatch):
    def failing(*args, **kwargs):
        raise LlmError("boom")

    monkeypatch.setattr(llm_router, "explain_result", failing)

    response = client.post(
        "/api/llm/explain",
        json={"computed_data": {"a": 1}, "lang": "en"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"


def test_explain_endpoint_returns_text_on_success(client, monkeypatch):
    monkeypatch.setattr(
        llm_router, "explain_result", lambda data, lang: "plain language text"
    )

    response = client.post(
        "/api/llm/explain",
        json={"computed_data": {"a": 1}, "lang": "hi"},
    )

    assert response.status_code == 200
    assert response.json() == {"explanation": "plain language text"}


def test_extract_profile_endpoint_returns_502_when_llm_unavailable(client, monkeypatch):
    def failing(text):
        raise LlmError("boom")

    monkeypatch.setattr(llm_router, "extract_profile", failing)

    response = client.post("/api/llm/extract-profile", json={"text": "hello"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"


def test_extract_profile_endpoint_returns_fields_on_success(client, monkeypatch):
    monkeypatch.setattr(
        llm_router,
        "extract_profile",
        lambda text: {
            "own_capital_paise": 100,
            "skills": ["farming"],
            "premises": None,
            "power": None,
        },
    )

    response = client.post("/api/llm/extract-profile", json={"text": "hello"})

    assert response.status_code == 200
    assert response.json() == {
        "own_capital_paise": 100,
        "skills": ["farming"],
        "premises": None,
        "power": None,
    }
