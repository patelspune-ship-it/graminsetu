import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api_errors import install_error_handlers
from app.data.models import ViabilityIndex, Village
from app.db import get_db
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


# ---------------------------------------------------------------------------
# /feasibility-report
# ---------------------------------------------------------------------------


def _fake_report():
    return {
        "market_reach": "reach text",
        "opportunity_analysis": "opportunity text",
        "swot": {
            "strengths": "s",
            "weaknesses": "w",
            "opportunities": "o",
            "threats": "t",
        },
        "threats": "threats text",
        "competitor_mapping": {"value_percent": "75%", "note": "verbatim note"},
        "product_market_value": "pricing text",
    }


@pytest.fixture
def db_client():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(llm_router.router)

    db = Mock()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client, db


def _village(amenities=None):
    return SimpleNamespace(
        village_lgd="TEST-LGD",
        name="Test Village",
        district="Nashik",
        state="Maharashtra",
        village_amenities=amenities,
    )


def _viability_index(market_gap_value=None, demand_value=None):
    return SimpleNamespace(
        features={"catchment_population_proxy": 18_500},
        geographic_scores=[
            {
                "name": "market_gap",
                "weight_bps": 2_500,
                "value": market_gap_value,
                "note": "market gap note",
            },
            {
                "name": "demand",
                "weight_bps": 2_000,
                "value": demand_value,
                "note": "demand note",
            },
        ],
    )


def test_feasibility_report_endpoint_returns_report_on_success(db_client, monkeypatch):
    client, db = db_client

    db.get.side_effect = lambda model, key: {
        (Village, "TEST-LGD"): _village(
            amenities={
                "crops": {"agricultural_commodities": {"c1": "Wheat"}},
                "connectivity": {
                    "nearest_town_name": "Sinnar",
                    "nearest_town_distance_km": 12,
                },
            }
        ),
        (ViabilityIndex, ("TEST-LGD", "flour_mill")): _viability_index(
            market_gap_value={"numerator": 3, "denominator": 4},
            demand_value={"numerator": 1, "denominator": 2},
        ),
    }.get((model, key))

    captured = {}

    def fake_generate(village_data, archetype, computed_financials, lang):
        captured["village_data"] = village_data
        captured["computed_financials"] = computed_financials
        captured["lang"] = lang
        return _fake_report()

    monkeypatch.setattr(llm_router, "generate_feasibility_report", fake_generate)

    response = client.post(
        "/api/llm/feasibility-report",
        json={
            "village_lgd": "TEST-LGD",
            "archetype_id": "flour_mill",
            "project_cost_paise": 20_000_000,
            "available_for_project_paise": 2_000_000,
            "lang": "en",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == _fake_report()

    assert captured["village_data"]["nearest_town_name"] == "Sinnar"
    assert captured["village_data"]["reported_crops"] == ["Wheat"]
    assert captured["computed_financials"]["market_gap_sub_score"]["value"] == {
        "numerator": 3, "denominator": 4,
    }
    # demand 1/2 -> 5000 bps.
    assert captured["computed_financials"]["population_percentile_bps"] == 5_000
    assert captured["lang"] == "en"


def test_feasibility_report_endpoint_404_when_village_missing(db_client):
    client, db = db_client
    db.get.side_effect = lambda model, key: None

    response = client.post(
        "/api/llm/feasibility-report",
        json={
            "village_lgd": "MISSING",
            "archetype_id": "flour_mill",
            "project_cost_paise": 1,
            "available_for_project_paise": 1,
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VILLAGE_NOT_FOUND"


def test_feasibility_report_endpoint_404_when_archetype_missing(db_client):
    client, db = db_client
    db.get.side_effect = lambda model, key: (
        _village() if (model, key) == (Village, "TEST-LGD") else None
    )

    response = client.post(
        "/api/llm/feasibility-report",
        json={
            "village_lgd": "TEST-LGD",
            "archetype_id": "not_a_real_archetype",
            "project_cost_paise": 1,
            "available_for_project_paise": 1,
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARCHETYPE_NOT_FOUND"


def test_feasibility_report_endpoint_502_when_llm_unavailable(db_client, monkeypatch):
    client, db = db_client
    db.get.side_effect = lambda model, key: (
        _village() if (model, key) == (Village, "TEST-LGD") else None
    )

    def failing(*args, **kwargs):
        raise LlmError("boom")

    monkeypatch.setattr(llm_router, "generate_feasibility_report", failing)

    response = client.post(
        "/api/llm/feasibility-report",
        json={
            "village_lgd": "TEST-LGD",
            "archetype_id": "flour_mill",
            "project_cost_paise": 1,
            "available_for_project_paise": 1,
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"


def test_feasibility_report_endpoint_handles_missing_amenities_and_index(db_client, monkeypatch):
    client, db = db_client
    db.get.side_effect = lambda model, key: (
        _village(amenities=None) if (model, key) == (Village, "TEST-LGD") else None
    )

    captured = {}

    def fake_generate(village_data, archetype, computed_financials, lang):
        captured["village_data"] = village_data
        captured["computed_financials"] = computed_financials
        return _fake_report()

    monkeypatch.setattr(llm_router, "generate_feasibility_report", fake_generate)

    response = client.post(
        "/api/llm/feasibility-report",
        json={
            "village_lgd": "TEST-LGD",
            "archetype_id": "flour_mill",
            "project_cost_paise": 1,
            "available_for_project_paise": 1,
        },
    )

    assert response.status_code == 200, response.text
    assert captured["village_data"]["reported_crops"] == []
    assert captured["village_data"]["nearest_town_name"] is None
    assert captured["village_data"]["catchment_population_proxy"] is None
    assert captured["computed_financials"]["market_gap_sub_score"] is None
    assert captured["computed_financials"]["population_percentile_bps"] is None
