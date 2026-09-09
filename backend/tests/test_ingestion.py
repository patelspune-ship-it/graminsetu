import json
from fractions import Fraction

import httpx
import pytest

from app.data.census import (
    choose_match,
    load_village_rows,
    match_rows,
)
from app.data.common import normalize_name, resolve_columns
from app.data.osm import (
    fetch_overpass,
    normalize_category,
    validate_response,
)
from app.data.precompute import midrank_lookup
from app.viability.cached import (
    personalize_cached_scores,
    serialize_subscore,
)
from app.viability.scoring import SubScore, WEIGHTS_BPS


def candidate(osm_id, *names):
    return {
        "osm_id": osm_id,
        "names": list(names),
        "normalized_names": [normalize_name(name) for name in names],
        "latitude": 20.0,
        "longitude": 74.0,
    }


def test_alias_resolution_is_case_and_separator_insensitive():
    result = resolve_columns(
        ["VILLAGE NAME", "Total_Population"],
        {
            "name": ["village_name"],
            "population": ["total population"],
        },
        required={"name", "population"},
    )

    assert result["name"] == "VILLAGE NAME"
    assert result["population"] == "Total_Population"


def test_missing_column_names_the_problem():
    with pytest.raises(ValueError, match="population"):
        resolve_columns(
            ["village"],
            {"population": ["population", "tot_p"]},
            required={"population"},
        )


def test_ambiguous_population_columns_fail():
    with pytest.raises(ValueError, match="Ambiguous"):
        resolve_columns(
            ["Population", "TOT_P"],
            {"population": ["population", "tot_p"]},
            required={"population"},
        )


def test_census_code_is_not_silently_used_as_lgd(tmp_path):
    source = tmp_path / "villages.csv"
    source.write_text(
        "Village Name,District,Population,Census Code\n"
        "Example,Nashik,1000,123456\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not LGD"):
        load_village_rows(source, "Nashik")


def test_census_loader_accepts_explicit_lgd(tmp_path):
    source = tmp_path / "villages.csv"
    source.write_text(
        "Village Name,District,TOT_P,LGD Village Code\n"
        "Example,Nashik,1000,123456\n",
        encoding="utf-8",
    )

    rows, columns = load_village_rows(source, "Nashik")

    assert rows[0]["population"] == 1000
    assert rows[0]["village_lgd"] == "123456"
    assert rows[0]["households"] is None
    assert columns["population"] == "TOT_P"


def test_blank_population_fails_with_column_name(tmp_path):
    source = tmp_path / "villages.csv"
    source.write_text(
        "Village Name,District,Population,LGD Village Code\n"
        "Example,Nashik,,123456\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Population"):
        load_village_rows(source, "Nashik")


def test_exact_duplicate_names_are_ambiguous():
    match, status, _, _ = choose_match(
        "Rampur",
        [
            candidate(1, "Rampur"),
            candidate(2, "Rampur"),
        ],
    )

    assert match is None
    assert status == "ambiguous_candidates"


def test_multilingual_alias_can_match():
    match, status, score, _ = choose_match(
        "रामपूर",
        [candidate(1, "Rampur", "रामपूर")],
    )

    assert status == "matched"
    assert score == 100
    assert match["osm_id"] == 1


def test_settlement_qualifiers_are_preserved():
    assert normalize_name("Example Bk.") != normalize_name("Example Kh.")


def test_one_place_cannot_match_two_census_villages():
    rows = [
        {"name": "Rampur", "village_lgd": "1"},
        {"name": "Rampur", "village_lgd": "2"},
    ]

    results = match_rows(
        rows,
        [candidate(10, "Rampur")],
        threshold=90,
        minimum_gap=8,
    )

    assert all(result["match"] is None for result in results)


def test_dairy_shop_is_not_collection_center():
    assert normalize_category({"shop": "dairy"}) == "dairy_retail"
    assert normalize_category(
        {"industrial": "dairy_collection"}
    ) == "dairy_collection"


def test_generic_mill_is_not_assumed_flour():
    assert normalize_category({"industrial": "mill"}) is None
    assert normalize_category({
        "industrial": "mill",
        "product": "flour",
    }) == "flour_mill"


def test_partial_overpass_response_is_rejected():
    with pytest.raises(ValueError, match="partial"):
        validate_response({
            "elements": [],
            "remark": "runtime error: Query timed out",
        })


def test_overpass_retries_and_uses_disk_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)

        if len(calls) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
            )

        if len(calls) == 2:
            return httpx.Response(504)

        return httpx.Response(
            200,
            json={"elements": [], "osm3s": {}},
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler)
    ) as client:
        payload, cache = fetch_overpass(
            "Nashik",
            "https://example.test/api",
            tmp_path,
            client=client,
            sleep=lambda _: None,
        )

        assert len(calls) == 3
        assert cache.exists()
        assert payload["elements"] == []

        second, same_cache = fetch_overpass(
            "Nashik",
            "https://example.test/api",
            tmp_path,
            client=client,
            offline=True,
        )

        assert len(calls) == 3
        assert same_cache == cache
        assert second == payload


def test_offline_mode_never_fetches_missing_cache(tmp_path):
    with pytest.raises(FileNotFoundError, match="Offline"):
        fetch_overpass(
            "Jalgaon",
            "https://example.test/api",
            tmp_path,
            offline=True,
        )


def test_midrank_batch_matches_expected_values():
    result = midrank_lookup([100, 200, 200, 300])

    assert result[100] == Fraction(1, 8)
    assert result[200] == Fraction(1, 2)
    assert result[300] == Fraction(7, 8)


def test_cached_personalization_needs_no_spatial_inputs():
    geographic = [
        serialize_subscore(
            SubScore(name, WEIGHTS_BPS[name], Fraction(1, 2), "Test")
        )
        for name in (
            "market_gap",
            "demand",
            "inputs",
            "infrastructure",
        )
    ]

    result = personalize_cached_scores(
        geographic_scores=geographic,
        user_skills={"farming"},
        required_skills={"farming"},
        user_capital_paise=10000,
        required_own_contribution_paise=10000,
    )

    assert result.score == 60
    assert result.verdict == "MODERATE"