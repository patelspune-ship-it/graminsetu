from fractions import Fraction

from app.viability.amenities import infrastructure_subscore, inputs_subscore


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
