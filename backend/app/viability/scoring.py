from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from app.fin.core import BPS, ceil_fraction, require_int, round_half_up


WEIGHTS_BPS = {
    "market_gap": 2_500,
    "demand": 2_000,
    "inputs": 2_000,
    "infrastructure": 1_500,
    "skills": 1_000,
    "capital": 1_000,
}


@dataclass(frozen=True)
class ViabilityInputs:
    local_competitors: int | None
    catchment_population: int | None

    # Each reference observation = (competitor count, population).
    district_competition_samples: tuple[tuple[int, int], ...]
    competition_coverage_verified: bool

    village_population: int | None
    district_populations: tuple[int, ...]
    demand_coefficient_bps: int

    requires_crop_inputs: bool
    crop_area_m2: int | None
    district_crop_areas_m2: tuple[int, ...]

    distance_to_mandi_m: int | None
    road_access_bps: int | None
    power_availability_bps: int | None
    distance_to_bank_m: int | None

    user_skills: frozenset[str]
    required_skills: frozenset[str]

    user_capital_paise: int
    required_own_contribution_paise: int


@dataclass(frozen=True)
class SubScore:
    name: str
    weight_bps: int
    value: Fraction | None
    note: str


@dataclass(frozen=True)
class ViabilityResult:
    score: int | None
    verdict: str

    lower_bound_score: int
    upper_bound_score: int

    # Available fraction of scoring weight, not a probability.
    evidence_coverage_bps: int

    sub_scores: tuple[SubScore, ...]
    top_drivers: tuple[SubScore, ...]
    warnings: tuple[str, ...]


def clamp01(value: Fraction) -> Fraction:
    return max(Fraction(0), min(Fraction(1), value))


def median(values: Sequence[Fraction]) -> Fraction:
    if not values:
        raise ValueError("Cannot calculate median of empty values")

    ordered = sorted(values)
    middle = len(ordered) // 2

    if len(ordered) % 2:
        return ordered[middle]

    return (ordered[middle - 1] + ordered[middle]) / 2


def percentile_midrank(
    value: Fraction | int,
    reference: Sequence[Fraction | int],
) -> Fraction:
    if not reference:
        raise ValueError("Percentile reference cannot be empty")

    less = sum(item < value for item in reference)
    equal = sum(item == value for item in reference)

    return Fraction(2 * less + equal, 2 * len(reference))


def distance_decay(
    distance_m: int,
    half_score_distance_m: int,
) -> Fraction:
    require_int("distance_m", distance_m)
    require_int("half_score_distance_m", half_score_distance_m, 1)

    return Fraction(
        half_score_distance_m,
        half_score_distance_m + distance_m,
    )


def _validate(inputs: ViabilityInputs) -> None:
    for name in (
        "local_competitors",
        "catchment_population",
        "village_population",
        "crop_area_m2",
        "distance_to_mandi_m",
        "distance_to_bank_m",
    ):
        value = getattr(inputs, name)
        if value is not None:
            require_int(name, value)

    for name in ("road_access_bps", "power_availability_bps"):
        value = getattr(inputs, name)
        if value is not None:
            require_int(name, value, 0, BPS)

    require_int("demand_coefficient_bps", inputs.demand_coefficient_bps, 1)
    require_int("user_capital_paise", inputs.user_capital_paise)
    require_int(
        "required_own_contribution_paise",
        inputs.required_own_contribution_paise,
    )

    for count, population in inputs.district_competition_samples:
        require_int("district competitor count", count)
        require_int("district catchment population", population, 1)

    for population in inputs.district_populations:
        require_int("district population", population, 1)

    for area in inputs.district_crop_areas_m2:
        require_int("district crop area", area)

    if type(inputs.competition_coverage_verified) is not bool:
        raise TypeError("competition_coverage_verified must be bool")

    if type(inputs.requires_crop_inputs) is not bool:
        raise TypeError("requires_crop_inputs must be bool")


def score_viability(inputs: ViabilityInputs) -> ViabilityResult:
    _validate(inputs)

    scores: list[SubScore] = []
    warnings: list[str] = []

    def add(name: str, value: Fraction | None, note: str):
        scores.append(
            SubScore(
                name=name,
                weight_bps=WEIGHTS_BPS[name],
                value=clamp01(value) if value is not None else None,
                note=note,
            )
        )

    # S1: market gap.
    market = None

    if not inputs.competition_coverage_verified:
        market_note = (
            "OSM category coverage is unverified; mapped absence "
            "cannot establish absence of competitors."
        )
    elif (
        inputs.local_competitors is None
        or not inputs.catchment_population
        or not inputs.district_competition_samples
    ):
        market_note = "Missing competition count, catchment population or references."
    else:
        district_densities = [
            Fraction(count * 1_000, population)
            for count, population in inputs.district_competition_samples
        ]
        district_median = median(district_densities)

        if district_median == 0:
            market_note = (
                "District median mapped density is zero; "
                "relative market gap is undefined."
            )
        else:
            local_density = Fraction(
                inputs.local_competitors * 1_000,
                inputs.catchment_population,
            )
            market = clamp01(1 - local_density / district_median)
            market_note = (
                f"{inputs.local_competitors} mapped competitors for "
                f"{inputs.catchment_population} catchment residents; "
                "compared with the median density of equivalent "
                "district catchments. This is not proof of demand."
            )

    add("market_gap", market, market_note)

    # S2: demand.
    if inputs.village_population and inputs.district_populations:
        coefficient = Fraction(inputs.demand_coefficient_bps, BPS)

        demand = percentile_midrank(
            inputs.village_population * coefficient,
            [
                population * coefficient
                for population in inputs.district_populations
            ],
        )
        add(
            "demand",
            demand,
            "Population-based district percentile; purchasing power "
            "and actual buying behaviour are not measured.",
        )
    else:
        add("demand", None, "Missing village population or district references.")

    # S3: input availability.
    if not inputs.requires_crop_inputs:
        add(
            "inputs",
            Fraction(1),
            "Not crop-input constrained under this archetype; "
            "non-crop procurement still requires verification.",
        )
    elif (
        inputs.crop_area_m2 is not None
        and inputs.district_crop_areas_m2
    ):
        if max(inputs.district_crop_areas_m2) == 0:
            add(
                "inputs",
                Fraction(0) if inputs.crop_area_m2 == 0 else None,
                "District crop reference contains no positive crop area; "
                "verify crop relevance and source coverage.",
            )
        else:
            add(
                "inputs",
                percentile_midrank(
                    inputs.crop_area_m2,
                    inputs.district_crop_areas_m2,
                ),
                "Crop-area percentile using comparable geographic catchments. "
                "District totals must not be presented as village acreage.",
            )
    else:
        add("inputs", None, "Missing crop area or comparable crop references.")

    # S4: infrastructure.
    infrastructure_values = (
        inputs.distance_to_mandi_m,
        inputs.road_access_bps,
        inputs.power_availability_bps,
        inputs.distance_to_bank_m,
    )

    if all(value is not None for value in infrastructure_values):
        infrastructure = (
            distance_decay(inputs.distance_to_mandi_m, 10_000)
            + Fraction(inputs.road_access_bps, BPS)
            + Fraction(inputs.power_availability_bps, BPS)
            + distance_decay(inputs.distance_to_bank_m, 5_000)
        ) / 4

        add(
            "infrastructure",
            infrastructure,
            "Mean of mandi-distance decay, road access, power availability "
            "and bank-distance decay. Distances must use a consistent method.",
        )
    else:
        add(
            "infrastructure",
            None,
            "One or more infrastructure inputs are missing; "
            "no automatic favourable default is applied.",
        )

    # S5: skill fit.
    union = inputs.user_skills | inputs.required_skills
    intersection = inputs.user_skills & inputs.required_skills

    skill_score = (
        Fraction(len(intersection), len(union))
        if union
        else Fraction(1)
    )

    add(
        "skills",
        skill_score,
        f"{len(intersection)} matching skills; Jaccard similarity "
        "is a heuristic, not a competency assessment.",
    )

    # S6: capital fit.
    required_own = inputs.required_own_contribution_paise

    capital_score = (
        min(Fraction(inputs.user_capital_paise, required_own), Fraction(1))
        if required_own
        else Fraction(1)
    )

    add(
        "capital",
        capital_score,
        "Own funds compared with an explicit contribution assumption. "
        "This is not repayment affordability or loan eligibility.",
    )

    available_weight = sum(
        score.weight_bps for score in scores if score.value is not None
    )

    weighted_known = sum(
        (
            Fraction(score.weight_bps, BPS) * score.value
            for score in scores
            if score.value is not None
        ),
        start=Fraction(0),
    )

    missing_weight = Fraction(BPS - available_weight, BPS)

    lower = (100 * weighted_known).numerator // (
        100 * weighted_known
    ).denominator
    upper = ceil_fraction(100 * (weighted_known + missing_weight))

    if available_weight == BPS:
        final_score = round_half_up(100 * weighted_known)

        verdict = (
            "STRONG"
            if final_score >= 70
            else "MODERATE"
            if final_score >= 45
            else "WEAK"
        )

        lower = upper = final_score
    else:
        final_score = None
        verdict = "INSUFFICIENT_DATA"
        warnings.append(
            "Incomplete evidence: the interval assigns unknown sub-scores "
            "their possible minimum and maximum. It is not a confidence interval."
        )

    if any(
        len(reference) < 10
        for reference in (
            inputs.district_competition_samples,
            inputs.district_populations,
            inputs.district_crop_areas_m2,
        )
        if reference
    ):
        warnings.append(
            "At least one district reference set has fewer than 10 observations; "
            "percentiles/medians are unstable."
        )

    warnings.append(
        "The index is an explainable heuristic, not a calibrated probability "
        "of business success."
    )

    drivers = sorted(
        (score for score in scores if score.value is not None),
        key=lambda score: score.weight_bps * score.value,
        reverse=True,
    )[:3]

    return ViabilityResult(
        score=final_score,
        verdict=verdict,
        lower_bound_score=lower,
        upper_bound_score=upper,
        evidence_coverage_bps=available_weight,
        sub_scores=tuple(scores),
        top_drivers=tuple(drivers),
        warnings=tuple(warnings),
    )