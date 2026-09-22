from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api_errors import install_error_handlers
from app.data.models import ViabilityIndex, Village
from app.db import get_db
from app.llm import LlmError
from app.llm import feasibility_report_cache
from app.llm.feasibility_report_cache import cache_key, get_or_generate_feasibility_report
from app.models import FeasibilityReportCache
from app.routers import llm as llm_router


def _archetype():
    from app.archetypes import get_archetype
    return get_archetype("flour_mill")


def _village_data():
    return {
        "name": "Test Village",
        "district": "Nashik",
        "state": "Maharashtra",
        "catchment_population_proxy": 18_500,
        "nearest_town_name": "Sinnar",
        "nearest_town_distance_km": 12,
        "reported_crops": ["Wheat"],
    }


def _computed_financials():
    return {
        "project_cost_paise": 20_000_000,
        "available_for_project_paise": 2_000_000,
        "population_percentile_bps": 5_000,
        "market_gap_sub_score": {
            "name": "market_gap",
            "weight_bps": 2_500,
            "value": {"numerator": 3, "denominator": 4},
            "note": "note",
        },
    }


def _fake_report():
    return {
        "market_reach": "reach text",
        "opportunity_analysis": "opportunity text",
        "swot": {
            "strengths": "s", "weaknesses": "w", "opportunities": "o", "threats": "t",
        },
        "threats": "threats text",
        "competitor_mapping": {"value_percent": "75%", "note": "verbatim note"},
        "product_market_value": "pricing text",
    }


class FakeSession:
    """Minimal in-memory stand-in for the two calls the cache wrapper
    makes: db.get(Model, key) and db.add(record) + db.commit(). No real
    SQL — this proves the wrapper's own caching logic, independent of
    the database engine."""

    def __init__(self):
        self.store = {}

    def get(self, model, key):
        assert model is FeasibilityReportCache
        return self.store.get(key)

    def add(self, record):
        self.store[record.cache_key] = record

    def commit(self):
        pass

    def rollback(self):
        pass


# --- cache_key ---------------------------------------------------------


def test_cache_key_is_stable_for_identical_inputs():
    key1 = cache_key("550134", "dairy_collection", _village_data(), _computed_financials(), "en")
    key2 = cache_key("550134", "dairy_collection", _village_data(), _computed_financials(), "en")
    assert key1 == key2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda kwargs: kwargs.update(village_lgd="550104"),
        lambda kwargs: kwargs.update(archetype_id="onion_storage"),
        lambda kwargs: kwargs.update(lang="hi"),
    ],
)
def test_cache_key_changes_with_village_archetype_or_lang(mutate):
    base = dict(
        village_lgd="550134",
        archetype_id="dairy_collection",
        village_data=_village_data(),
        computed_financials=_computed_financials(),
        lang="en",
    )
    original = cache_key(**base)
    mutate(base)
    assert cache_key(**base) != original


def test_cache_key_changes_with_financials():
    financials_a = _computed_financials()
    financials_b = {**_computed_financials(), "project_cost_paise": 30_000_000}

    key_a = cache_key("550134", "dairy_collection", _village_data(), financials_a, "en")
    key_b = cache_key("550134", "dairy_collection", _village_data(), financials_b, "en")
    assert key_a != key_b


# --- get_or_generate_feasibility_report ---------------------------------


def test_miss_calls_gemini_and_stores_the_result(monkeypatch):
    db = FakeSession()
    calls = []

    def fake_generate(village_data, archetype, computed_financials, lang):
        calls.append(lang)
        return _fake_report()

    monkeypatch.setattr(feasibility_report_cache, "generate_feasibility_report", fake_generate)

    report = get_or_generate_feasibility_report(
        db, "550134", _archetype(), _village_data(), _computed_financials(), "en"
    )

    assert report == _fake_report()
    assert calls == ["en"]
    assert len(db.store) == 1


def test_hit_returns_cached_report_without_calling_gemini(monkeypatch):
    db = FakeSession()

    monkeypatch.setattr(
        feasibility_report_cache, "generate_feasibility_report", lambda *a: _fake_report()
    )
    get_or_generate_feasibility_report(
        db, "550134", _archetype(), _village_data(), _computed_financials(), "en"
    )

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("cache hit must not call Gemini")

    monkeypatch.setattr(feasibility_report_cache, "generate_feasibility_report", must_not_be_called)

    report = get_or_generate_feasibility_report(
        db, "550134", _archetype(), _village_data(), _computed_financials(), "en"
    )

    assert report == _fake_report()


def test_different_language_is_a_separate_cache_entry(monkeypatch):
    db = FakeSession()
    calls = []

    def fake_generate(village_data, archetype, computed_financials, lang):
        calls.append(lang)
        return {**_fake_report(), "market_reach": f"reach in {lang}"}

    monkeypatch.setattr(feasibility_report_cache, "generate_feasibility_report", fake_generate)

    en_report = get_or_generate_feasibility_report(
        db, "550134", _archetype(), _village_data(), _computed_financials(), "en"
    )
    hi_report = get_or_generate_feasibility_report(
        db, "550134", _archetype(), _village_data(), _computed_financials(), "hi"
    )

    assert calls == ["en", "hi"]
    assert en_report["market_reach"] == "reach in en"
    assert hi_report["market_reach"] == "reach in hi"
    assert len(db.store) == 2


def test_a_failed_cache_write_still_returns_the_generated_report(monkeypatch):
    db = FakeSession()
    db.commit = lambda: (_ for _ in ()).throw(RuntimeError("db unavailable"))

    monkeypatch.setattr(
        feasibility_report_cache, "generate_feasibility_report", lambda *a: _fake_report()
    )

    report = get_or_generate_feasibility_report(
        db, "550134", _archetype(), _village_data(), _computed_financials(), "en"
    )

    assert report == _fake_report()


# --- End-to-end through the real HTTP endpoint --------------------------


def _village():
    return SimpleNamespace(
        village_lgd="550134",
        name="Chaugaon",
        district="Nashik",
        state="Maharashtra",
        village_amenities={
            "crops": {"agricultural_commodities": {"c1": "Wheat"}},
            "connectivity": {
                "nearest_town_name": "Sinnar",
                "nearest_town_distance_km": 12,
            },
        },
    )


def _viability_index():
    return SimpleNamespace(
        features={"catchment_population_proxy": 18_500},
        geographic_scores=[
            {
                "name": "market_gap", "weight_bps": 2_500,
                "value": {"numerator": 3, "denominator": 4}, "note": "note",
            },
            {
                "name": "demand", "weight_bps": 2_000,
                "value": {"numerator": 1, "denominator": 2}, "note": "note",
            },
        ],
    )


class RouterFakeSession(FakeSession):
    """Extends FakeSession with the Village/ViabilityIndex lookups the
    /feasibility-report endpoint also performs, so a full request can run
    against it end to end."""

    def get(self, model, key):
        if model is Village:
            return _village() if key == "550134" else None
        if model is ViabilityIndex:
            return _viability_index() if key == ("550134", "flour_mill") else None
        return self.store.get(key)


@pytest.fixture
def endpoint_client():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(llm_router.router)

    db = RouterFakeSession()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _request_payload():
    return {
        "village_lgd": "550134",
        "archetype_id": "flour_mill",
        "project_cost_paise": 20_000_000,
        "available_for_project_paise": 2_000_000,
        "lang": "en",
    }


def test_second_identical_request_is_a_cache_hit_and_skips_gemini(
    endpoint_client, monkeypatch
):
    monkeypatch.setattr(
        feasibility_report_cache, "generate_feasibility_report", lambda *a: _fake_report()
    )

    first = endpoint_client.post("/api/llm/feasibility-report", json=_request_payload())
    assert first.status_code == 200, first.text

    def must_not_be_called(*args, **kwargs):
        raise LlmError("Gemini must not be called on a cache hit")

    monkeypatch.setattr(feasibility_report_cache, "generate_feasibility_report", must_not_be_called)

    second = endpoint_client.post("/api/llm/feasibility-report", json=_request_payload())

    assert second.status_code == 200, second.text
    assert second.json() == first.json()
