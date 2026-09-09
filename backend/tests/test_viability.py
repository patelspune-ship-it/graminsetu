from dataclasses import replace
from fractions import Fraction

from app.viability.scoring import (
    ViabilityInputs,
    percentile_midrank,
    score_viability,
)


def complete_inputs() -> ViabilityInputs:
    return ViabilityInputs(
        local_competitors=1,
        catchment_population=1_000,
        district_competition_samples=(
            (2, 1_000),
            (2, 1_000),
            (2, 1_000),
        ),
        competition_coverage_verified=True,
        village_population=1_000,
        district_populations=(500, 1_000, 1_500),
        demand_coefficient_bps=8_500,
        requires_crop_inputs=True,
        crop_area_m2=100,
        district_crop_areas_m2=(50, 100, 150),
        distance_to_mandi_m=10_000,
        road_access_bps=5_000,
        power_availability_bps=5_000,
        distance_to_bank_m=5_000,
        user_skills=frozenset({"farming"}),
        required_skills=frozenset({"farming"}),
        user_capital_paise=100_000,
        required_own_contribution_paise=100_000,
    )


def find_score(result, name):
    return next(
        item for item in result.sub_scores if item.name == name
    )


def test_midrank_handles_ties():
    assert percentile_midrank(10, [10, 10, 10]) == Fraction(1, 2)
    assert percentile_midrank(5, [1, 2, 3]) == 1
    assert percentile_midrank(0, [1, 2, 3]) == 0


def test_six_weights_produce_expected_score():
    result = score_viability(complete_inputs())

    # First 80% of weights score 0.5.
    # Skills and capital, last 20%, score 1.
    assert result.score == 60
    assert result.verdict == "MODERATE"
    assert result.evidence_coverage_bps == 10_000
    assert len(result.top_drivers) == 3

    assert find_score(result, "market_gap").value == Fraction(1, 2)


def test_higher_competitor_density_means_no_market_gap():
    result = score_viability(
        replace(complete_inputs(), local_competitors=5)
    )

    assert find_score(result, "market_gap").value == 0


def test_zero_district_density_is_unknown_not_division_error():
    result = score_viability(
        replace(
            complete_inputs(),
            district_competition_samples=((0, 1_000), (0, 2_000)),
        )
    )

    assert result.score is None
    assert result.verdict == "INSUFFICIENT_DATA"
    assert find_score(result, "market_gap").value is None
    assert result.evidence_coverage_bps == 7_500


def test_unverified_osm_absence_does_not_create_opportunity():
    result = score_viability(
        replace(
            complete_inputs(),
            local_competitors=0,
            competition_coverage_verified=False,
        )
    )

    assert result.score is None
    assert find_score(result, "market_gap").value is None
    assert result.lower_bound_score <= result.upper_bound_score


def test_missing_crop_data_is_not_zero_crop():
    result = score_viability(
        replace(complete_inputs(), crop_area_m2=None)
    )

    assert result.score is None
    assert find_score(result, "inputs").value is None
    assert result.evidence_coverage_bps == 8_000


def test_missing_infrastructure_is_not_favourable_default():
    result = score_viability(
        replace(complete_inputs(), power_availability_bps=None)
    )

    assert result.score is None
    assert find_score(result, "infrastructure").value is None


def test_no_crop_dependency_is_explicit():
    result = score_viability(
        replace(
            complete_inputs(),
            requires_crop_inputs=False,
            crop_area_m2=None,
            district_crop_areas_m2=(),
        )
    )

    assert find_score(result, "inputs").value == 1
    assert result.score is not None


def test_zero_required_own_contribution_is_defined():
    result = score_viability(
        replace(
            complete_inputs(),
            user_capital_paise=0,
            required_own_contribution_paise=0,
        )
    )

    assert find_score(result, "capital").value == 1


def test_no_skills_on_either_side_is_defined():
    result = score_viability(
        replace(
            complete_inputs(),
            user_skills=frozenset(),
            required_skills=frozenset(),
        )
    )

    assert find_score(result, "skills").value == 1