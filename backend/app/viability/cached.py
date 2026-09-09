from fractions import Fraction

from app.fin.core import BPS, ceil_fraction, require_int, round_half_up
from app.viability.scoring import (
    SubScore,
    ViabilityResult,
    WEIGHTS_BPS,
)


GEOGRAPHIC_NAMES = (
    "market_gap",
    "demand",
    "inputs",
    "infrastructure",
)


def serialize_subscore(score: SubScore) -> dict:
    return {
        "name": score.name,
        "weight_bps": score.weight_bps,
        "value": (
            {
                "numerator": score.value.numerator,
                "denominator": score.value.denominator,
            }
            if score.value is not None
            else None
        ),
        "note": score.note,
    }


def deserialize_subscore(raw: dict) -> SubScore:
    value = raw["value"]

    return SubScore(
        name=raw["name"],
        weight_bps=raw["weight_bps"],
        value=(
            Fraction(value["numerator"], value["denominator"])
            if value is not None
            else None
        ),
        note=raw["note"],
    )


def personalize_cached_scores(
    geographic_scores: list[dict],
    user_skills: set[str] | frozenset[str],
    required_skills: set[str] | frozenset[str],
    user_capital_paise: int,
    required_own_contribution_paise: int,
    warnings: list[str] | tuple[str, ...] = (),
) -> ViabilityResult:
    require_int("user_capital_paise", user_capital_paise)
    require_int(
        "required_own_contribution_paise",
        required_own_contribution_paise,
    )

    scores = [
        deserialize_subscore(score)
        for score in geographic_scores
    ]

    if (
        len(scores) != 4
        or {score.name for score in scores} != set(GEOGRAPHIC_NAMES)
    ):
        raise ValueError("Cache must contain exactly four geographic sub-scores")

    for score in scores:
        if score.weight_bps != WEIGHTS_BPS[score.name]:
            raise ValueError("Cached scoring weights do not match current model")

        if score.value is not None and not 0 <= score.value <= 1:
            raise ValueError("Cached score must be between 0 and 1")

    user_skills = set(user_skills)
    required_skills = set(required_skills)

    union = user_skills | required_skills
    intersection = user_skills & required_skills

    skill_score = (
        Fraction(len(intersection), len(union))
        if union else Fraction(1)
    )

    capital_score = (
        min(
            Fraction(user_capital_paise, required_own_contribution_paise),
            Fraction(1),
        )
        if required_own_contribution_paise else Fraction(1)
    )

    scores.extend([
        SubScore(
            name="skills",
            weight_bps=WEIGHTS_BPS["skills"],
            value=skill_score,
            note=(
                f"{len(intersection)} matching skills; Jaccard similarity "
                "is a heuristic, not a competency assessment."
            ),
        ),
        SubScore(
            name="capital",
            weight_bps=WEIGHTS_BPS["capital"],
            value=capital_score,
            note=(
                "Available own capital compared with an explicit contribution "
                "assumption; not loan eligibility or repayment affordability."
            ),
        ),
    ])

    available_weight = sum(
        score.weight_bps for score in scores
        if score.value is not None
    )

    weighted = sum(
        (
            Fraction(score.weight_bps, BPS) * score.value
            for score in scores
            if score.value is not None
        ),
        start=Fraction(0),
    )

    missing = Fraction(BPS - available_weight, BPS)
    lower_value = 100 * weighted

    lower = lower_value.numerator // lower_value.denominator
    upper = ceil_fraction(100 * (weighted + missing))

    output_warnings = list(warnings)

    if available_weight == BPS:
        score = round_half_up(100 * weighted)
        lower = upper = score

        verdict = (
            "STRONG" if score >= 70
            else "MODERATE" if score >= 45
            else "WEAK"
        )
    else:
        score = None
        verdict = "INSUFFICIENT_DATA"
        output_warnings.append(
            "Unknown sub-scores produce a possible score interval, "
            "not a statistical confidence interval."
        )

    drivers = sorted(
        (
            item for item in scores
            if item.value is not None
        ),
        key=lambda item: item.weight_bps * item.value,
        reverse=True,
    )[:3]

    return ViabilityResult(
        score=score,
        verdict=verdict,
        lower_bound_score=lower,
        upper_bound_score=upper,
        evidence_coverage_bps=available_weight,
        sub_scores=tuple(scores),
        top_drivers=tuple(drivers),
        warnings=tuple(output_warnings),
    )