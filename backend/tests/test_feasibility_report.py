import json

import httpx
import pytest

from app.archetypes import get_archetype
from app.llm import LlmError
from app.llm.feasibility_report import (
    _low_season_months,
    generate_feasibility_report,
)
from app.llm.gemini_client import GEMINI_URL


def _gemini_response(payload: dict) -> httpx.Response:
    body = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(payload)}]}}
        ]
    }
    return httpx.Response(200, json=body, request=httpx.Request("POST", GEMINI_URL))


def _valid_sections(**overrides) -> dict:
    sections = {
        "market_reach": "Catchment population as given; nearest town as given.",
        "opportunity_analysis": "Underserved niche narrative; evidence gaps stated.",
        "swot": {
            "strengths": "Strength text referencing project cost.",
            "weaknesses": "Weakness text referencing own capital.",
            "opportunities": "Opportunity text.",
            "threats": "Threat text.",
        },
        "threats": "Supply chain, seasonal and single-buyer narrative.",
        "product_market_value": "Pricing guidance narrative.",
    }
    sections.update(overrides)
    return sections


@pytest.fixture(autouse=True)
def gemini_api_key(monkeypatch):
    monkeypatch.setattr("app.llm.gemini_client.settings.gemini_api_key", "test-key")


def sample_archetype():
    return get_archetype("flour_mill")


def sample_village_data():
    return {
        "name": "Demo Village",
        "district": "Nashik",
        "state": "Maharashtra",
        "catchment_population_proxy": 18_500,
        "nearest_town_name": "Sinnar",
        "nearest_town_distance_km": 12,
        "reported_crops": ["wheat", "onion"],
        "reported_amenities": ["Mandi: available"],
    }


def sample_computed_financials(market_gap_sub_score=None):
    return {
        "project_cost_paise": 20_000_000,
        "available_for_project_paise": 2_000_000,
        "population_percentile_bps": 6_234,
        "market_gap_sub_score": market_gap_sub_score,
    }


# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


def test_generate_feasibility_report_returns_all_six_sections(monkeypatch):
    def fake_post(*args, **kwargs):
        return _gemini_response(_valid_sections())

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    report = generate_feasibility_report(
        sample_village_data(),
        sample_archetype(),
        sample_computed_financials(),
        "en",
    )

    assert set(report) == {
        "market_reach",
        "opportunity_analysis",
        "swot",
        "threats",
        "competitor_mapping",
        "product_market_value",
    }
    assert report["market_reach"] == "Catchment population as given; nearest town as given."
    assert set(report["swot"]) == {"strengths", "weaknesses", "opportunities", "threats"}


def test_feasibility_report_passes_facts_and_language_in_prompt(monkeypatch):
    captured = {}

    def fake_post(url, params=None, json=None, timeout=None):
        captured["body"] = json
        return _gemini_response(_valid_sections())

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    generate_feasibility_report(
        sample_village_data(),
        sample_archetype(),
        sample_computed_financials(),
        "mr",
    )

    system_prompt = captured["body"]["systemInstruction"]["parts"][0]["text"]
    user_prompt = captured["body"]["contents"][0]["parts"][0]["text"]

    assert "Marathi" in system_prompt
    assert "never introduce a number" not in system_prompt  # sanity: not literal echo
    assert "18,500" in user_prompt or "18500" in user_prompt
    assert "Sinnar" in user_prompt


# ---------------------------------------------------------------------------
# competitor_mapping: verbatim pass-through, never touched by the LLM.
# ---------------------------------------------------------------------------


def test_competitor_mapping_passes_through_verbatim(monkeypatch):
    market_gap = {
        "name": "market_gap",
        "weight_bps": 2_500,
        "value": {"numerator": 3, "denominator": 4},
        "note": "2 mapped competitors for 18500 catchment residents; exact note text.",
    }

    def fake_post(*args, **kwargs):
        return _gemini_response(_valid_sections())

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    report = generate_feasibility_report(
        sample_village_data(),
        sample_archetype(),
        sample_computed_financials(market_gap_sub_score=market_gap),
        "en",
    )

    assert report["competitor_mapping"]["note"] == market_gap["note"]
    assert report["competitor_mapping"]["value_percent"] == "75%"


def test_competitor_mapping_states_absence_when_no_evidence(monkeypatch):
    def fake_post(*args, **kwargs):
        return _gemini_response(_valid_sections())

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    report = generate_feasibility_report(
        sample_village_data(),
        sample_archetype(),
        sample_computed_financials(market_gap_sub_score=None),
        "en",
    )

    assert report["competitor_mapping"]["value_percent"] is None
    assert "No market-gap evidence" in report["competitor_mapping"]["note"]


def test_competitor_mapping_ignores_llm_output_even_if_present(monkeypatch):
    """The LLM's response schema has no competitor_mapping key at all, but
    even if a rogue response included one, it must never be used."""
    market_gap = {
        "name": "market_gap",
        "weight_bps": 2_500,
        "value": None,
        "note": "Authoritative note.",
    }

    def fake_post(*args, **kwargs):
        sections = _valid_sections()
        sections["competitor_mapping"] = "LLM-invented text that must be ignored."
        return _gemini_response(sections)

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    report = generate_feasibility_report(
        sample_village_data(),
        sample_archetype(),
        sample_computed_financials(market_gap_sub_score=market_gap),
        "en",
    )

    assert report["competitor_mapping"]["note"] == "Authoritative note."


# ---------------------------------------------------------------------------
# Low-season months: computed in Python, never left to the LLM.
# ---------------------------------------------------------------------------


def test_low_season_months_below_average_only():
    seasonality = [9000, 9000, 11000, 13000, 12000, 8000, 7000, 7000, 9000, 12000, 13000, 10000]
    assert sum(seasonality) == 120_000

    assert _low_season_months(seasonality) == [
        "January", "February", "June", "July", "August", "September",
    ]


def test_low_season_months_uses_flour_mill_archetype(monkeypatch):
    captured = {}

    def fake_post(url, params=None, json=None, timeout=None):
        captured["body"] = json
        return _gemini_response(_valid_sections())

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    archetype = sample_archetype()
    generate_feasibility_report(
        sample_village_data(), archetype, sample_computed_financials(), "en"
    )

    user_prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    expected = _low_season_months(archetype.seasonality_bps)
    for month in expected:
        assert month in user_prompt


# ---------------------------------------------------------------------------
# Hard rule: no invented numbers.
# ---------------------------------------------------------------------------


def test_rejects_output_with_a_number_not_in_the_facts(monkeypatch):
    def fake_post(*args, **kwargs):
        sections = _valid_sections(
            market_reach="This catchment could support 45000 customers a year.",
        )
        return _gemini_response(sections)

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    with pytest.raises(LlmError, match="45000"):
        generate_feasibility_report(
            sample_village_data(),
            sample_archetype(),
            sample_computed_financials(),
            "en",
        )


def test_accepts_output_that_only_restates_given_numbers(monkeypatch):
    def fake_post(*args, **kwargs):
        sections = _valid_sections(
            market_reach="The catchment population is 18500 residents near Sinnar.",
        )
        return _gemini_response(sections)

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    report = generate_feasibility_report(
        sample_village_data(),
        sample_archetype(),
        sample_computed_financials(),
        "en",
    )
    assert "18500" in report["market_reach"]


def test_comma_formatted_numbers_still_validate(monkeypatch):
    def fake_post(*args, **kwargs):
        sections = _valid_sections(
            market_reach="The catchment population is 18,500 residents.",
        )
        return _gemini_response(sections)

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    report = generate_feasibility_report(
        sample_village_data(),
        sample_archetype(),
        sample_computed_financials(),
        "en",
    )
    assert "18,500" in report["market_reach"]


def test_single_digit_numbers_do_not_trigger_false_positive(monkeypatch):
    def fake_post(*args, **kwargs):
        sections = _valid_sections(
            threats="There are 3 main risks to consider for this business.",
        )
        return _gemini_response(sections)

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    report = generate_feasibility_report(
        sample_village_data(),
        sample_archetype(),
        sample_computed_financials(),
        "en",
    )
    assert "3 main risks" in report["threats"]


# ---------------------------------------------------------------------------
# Missing evidence is stated, not guessed — enforced structurally by the
# facts payload; here we confirm null village facts don't crash and are
# passed through as null rather than a guessed placeholder.
# ---------------------------------------------------------------------------


def test_missing_village_facts_are_passed_as_null(monkeypatch):
    captured = {}

    def fake_post(url, params=None, json=None, timeout=None):
        captured["body"] = json
        return _gemini_response(_valid_sections())

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    incomplete_village = {
        "name": "Demo Village",
        "district": "Nashik",
        "state": "Maharashtra",
        "catchment_population_proxy": None,
        "nearest_town_name": None,
        "nearest_town_distance_km": None,
        "reported_crops": [],
    }

    generate_feasibility_report(
        incomplete_village, sample_archetype(), sample_computed_financials(), "en"
    )

    user_prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    facts = json.loads(user_prompt.removeprefix("FACTS:\n"))
    assert facts["nearest_town_name"] is None
    assert facts["catchment_population"] is None


# ---------------------------------------------------------------------------
# Malformed model output.
# ---------------------------------------------------------------------------


def test_raises_on_invalid_json(monkeypatch):
    def fake_post(*args, **kwargs):
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
            request=httpx.Request("POST", GEMINI_URL),
        )

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    with pytest.raises(LlmError):
        generate_feasibility_report(
            sample_village_data(), sample_archetype(), sample_computed_financials(), "en"
        )


def test_raises_when_a_required_section_is_missing(monkeypatch):
    def fake_post(*args, **kwargs):
        sections = _valid_sections()
        del sections["threats"]
        return _gemini_response(sections)

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    with pytest.raises(LlmError, match="threats"):
        generate_feasibility_report(
            sample_village_data(), sample_archetype(), sample_computed_financials(), "en"
        )


def test_raises_when_swot_shape_is_wrong(monkeypatch):
    def fake_post(*args, **kwargs):
        sections = _valid_sections(swot="not an object")
        return _gemini_response(sections)

    monkeypatch.setattr("app.llm.gemini_client.httpx.post", fake_post)

    with pytest.raises(LlmError, match="swot"):
        generate_feasibility_report(
            sample_village_data(), sample_archetype(), sample_computed_financials(), "en"
        )


# ---------------------------------------------------------------------------
# Module boundary: app.fin and app.viability must never import app.llm.
# ---------------------------------------------------------------------------


def test_fin_and_viability_never_import_llm():
    import ast
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"

    for package in ("fin", "viability"):
        for path in (app_dir / package).glob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue

                for name in names:
                    assert name is None or not name.startswith("app.llm"), (
                        f"{path} imports {name}; app.{package} must never "
                        "depend on app.llm"
                    )
