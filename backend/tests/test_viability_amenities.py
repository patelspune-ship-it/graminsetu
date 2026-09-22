from fractions import Fraction

from app.viability.amenities import (
    infrastructure_subscore,
    inputs_subscore,
    market_context_component,
)


def facility(available, distance_code=None):
    return {
        "available": available,
        "raw_status": "1" if available else "2",
        "distance_code": distance_code,
        "distance_range_km": {"a": "<5km", "b": "5-10km", "c": "10km+"}.get(
            distance_code
        ),
    }


def power(available, summer=None, winter=None):
    return {
        "available": available,
        "raw_status": "1" if available else "2",
        "hours_summer": summer,
        "hours_winter": winter,
    }


def full_amenities(**overrides):
    base = {
        "power": {"commercial": power(True, 12, 12)},
        "roads": {
            "all_weather": facility(True),
            "black_topped": facility(False, "c"),
            "national_highway": facility(False, "c"),
            "state_highway": facility(False, "c"),
            "major_district_road": facility(False, "c"),
            "gravel": facility(False, "c"),
        },
        "finance": {
            "commercial_bank": facility(True),
            "cooperative_bank": facility(False, "c"),
            "atm": facility(False, "c"),
        },
        "markets": {"mandis_regular_market": facility(True)},
        "crops": {
            "agricultural_commodities": {
                "first": "Onion",
                "second": None,
                "third": "Wheat",
            }
        },
    }
    base.update(overrides)
    return base


def find_value(score):
    return score.value


def test_infrastructure_unknown_without_amenities():
    score = infrastructure_subscore(None)
    assert score.value is None
    assert "No Village Directory amenities" in score.note


def test_infrastructure_known_when_all_components_present():
    score = infrastructure_subscore(full_amenities())

    # power=12/24=0.5, road(all_weather)=1, bank(commercial_bank)=1,
    # mandi=1 -> mean (0.5+1+1+1)/4 = 7/8.
    assert score.value == Fraction(7, 8)
    assert score.weight_bps == 1_500


def test_infrastructure_unknown_when_power_missing():
    amenities = full_amenities(power={})
    score = infrastructure_subscore(amenities)

    assert score.value is None
    assert "commercial power hours" in score.note


def test_infrastructure_uses_distance_decay_when_facility_absent():
    amenities = full_amenities(
        roads={
            "all_weather": facility(False, "a"),
            "black_topped": facility(False, "a"),
            "national_highway": facility(False, "c"),
            "state_highway": facility(False, "c"),
            "major_district_road": facility(False, "c"),
            "gravel": facility(False, "c"),
        },
        markets={"mandis_regular_market": facility(False, "c")},
        finance={
            "commercial_bank": facility(False, "c"),
            "cooperative_bank": facility(False, "c"),
            "atm": facility(False, "a"),
        },
    )
    score = infrastructure_subscore(amenities)

    assert score.value is not None
    assert 0 <= score.value <= 1
    # Best available signal wins: ATM at <5km beats bank at 10+km.
    assert score.value < Fraction(1)


def test_infrastructure_road_all_missing_is_unknown_not_zero():
    amenities = full_amenities(
        roads={
            "all_weather": {"available": None},
            "black_topped": {"available": None},
        }
    )
    score = infrastructure_subscore(amenities)

    assert score.value is None
    assert "road quality" in score.note


def test_inputs_full_credit_when_not_crop_constrained():
    score = inputs_subscore(None, [])
    assert score.value == Fraction(1)


def test_inputs_unknown_without_amenities():
    score = inputs_subscore(None, ["wheat"])
    assert score.value is None
    assert "cannot be checked" in score.note


def test_inputs_full_match():
    score = inputs_subscore(full_amenities(), ["onion", "wheat"])
    assert score.value == Fraction(1)


def test_inputs_partial_match_is_case_insensitive():
    score = inputs_subscore(full_amenities(), ["Onion", "Gram"])
    assert score.value == Fraction(1, 2)
    assert "onion" in score.note


def test_inputs_no_match_is_zero_not_unknown():
    score = inputs_subscore(full_amenities(), ["gram", "tur"])
    assert score.value == Fraction(0)


def test_market_context_unknown_without_amenities():
    value, note = market_context_component(None, "kirana_store")
    assert value is None
    assert "Not a competitor census." in note


def test_market_context_unknown_for_unmapped_archetype():
    value, note = market_context_component(full_amenities(), "unmapped_archetype")
    assert value is None
    assert "Not a competitor census." in note


def test_market_context_in_village_facility_is_strongest_signal():
    amenities = full_amenities(
        markets={
            "pds_shop": facility(True),
            "weekly_haat": facility(False, "c"),
        }
    )
    value, note = market_context_component(amenities, "kirana_store")

    assert value == Fraction(1)
    assert "PDS shop" in note
    assert "Not a competitor census." in note


def test_market_context_uses_distance_code_when_not_in_village():
    amenities = full_amenities(
        markets={
            "pds_shop": facility(False, "a"),
            "weekly_haat": facility(False, "c"),
        }
    )
    value, note = market_context_component(amenities, "kirana_store")

    # Best of the two facilities wins: "a" (<5km) beats "c" (10km+).
    assert value == Fraction(7, 10)
    assert "PDS shop" in note


def test_market_context_dairy_uses_finance_facilities():
    amenities = full_amenities(
        finance={
            "commercial_bank": facility(True),
            "cooperative_bank": facility(False, "c"),
            "atm": facility(False, "c"),
            "agricultural_credit_society": facility(False, "c"),
            "shg": facility(True),
        }
    )
    value, note = market_context_component(amenities, "dairy_collection")

    assert value == Fraction(1)
    assert "SHG presence" in note


def test_market_context_falls_back_to_nearest_town_distance():
    amenities = full_amenities(
        markets={
            "pds_shop": {"available": None},
            "weekly_haat": {"available": None},
        },
        connectivity={"nearest_town_distance_km": 5},
    )
    value, note = market_context_component(amenities, "kirana_store")

    assert value == Fraction(15_000, 20_000)
    assert "nearest-town distance only" in note


def test_market_context_blends_facility_and_town_distance():
    amenities = full_amenities(
        markets={
            "pds_shop": facility(True),
            "weekly_haat": facility(False, "c"),
        },
        connectivity={"nearest_town_distance_km": 5},
    )
    value, note = market_context_component(amenities, "kirana_store")

    facility_value = Fraction(1)
    town_value = Fraction(15_000, 20_000)
    assert value == (3 * facility_value + town_value) / 4
    assert "Combines" in note


def test_market_context_no_evidence_is_unknown_not_zero():
    amenities = full_amenities(
        markets={
            "pds_shop": {"available": None},
            "weekly_haat": {"available": None},
        },
    )
    value, note = market_context_component(amenities, "kirana_store")

    assert value is None
    assert "Not a competitor census." in note
    assert "No relevant facility" in note
