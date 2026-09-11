import logging
from fractions import Fraction
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.archetypes import get_archetype
from app.data.models import Village, ViabilityIndex
from app.db import get_db
from app.dpr.models import FeasibilityReport
from app.fin.core import BPS, round_half_up
from app.llm import (
    LlmError,
    LlmRateLimitedError,
    explain_result,
    extract_profile,
    generate_feasibility_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["LLM"])


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    computed_data: dict
    lang: Literal["en", "hi", "mr"] = "en"


class ExplainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str


class ExtractProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


class ExtractProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    own_capital_paise: int | None = None
    skills: list[str] | None = None
    premises: str | None = None
    power: str | None = None


def _unavailable(exc: Exception) -> ApiError:
    logger.warning("LLM request failed: %s", exc)

    if isinstance(exc, LlmRateLimitedError):
        return ApiError(
            429,
            "LLM_RATE_LIMITED",
            "The language assistant has reached its usage limit for now "
            "(the Gemini API key's request quota is exhausted). Try again "
            "later, or fill in the fields yourself in the meantime.",
        )

    return ApiError(
        502,
        "LLM_UNAVAILABLE",
        "The language assistant is unavailable right now. Try again later.",
    )


@router.post("/explain", response_model=ExplainResponse)
def explain(payload: ExplainRequest):
    try:
        text = explain_result(payload.computed_data, payload.lang)
    except LlmError as exc:
        raise _unavailable(exc) from None

    return ExplainResponse(explanation=text)


@router.post("/extract-profile", response_model=ExtractProfileResponse)
def extract(payload: ExtractProfileRequest):
    try:
        fields = extract_profile(payload.text)
    except LlmError as exc:
        raise _unavailable(exc) from None

    return ExtractProfileResponse(**fields)


class FeasibilityReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    village_lgd: str = Field(min_length=1, max_length=20)
    archetype_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)

    # Already computed by /financial-model; restated here, not recomputed.
    project_cost_paise: int = Field(ge=0)
    available_for_project_paise: int = Field(ge=0)

    lang: Literal["en", "hi", "mr"] = "en"


def _feasibility_report_inputs(
    db: Session,
    village_lgd: str,
    archetype_id: str,
) -> tuple[dict, object]:
    """Gather already-computed village/viability facts for the narrative
    layer. Raises ApiError for a village or archetype that doesn't exist.
    """
    village = db.get(Village, village_lgd)
    if village is None:
        raise ApiError(404, "VILLAGE_NOT_FOUND", "Village not found.")

    try:
        archetype = get_archetype(archetype_id)
    except KeyError:
        raise ApiError(404, "ARCHETYPE_NOT_FOUND", "Archetype not found.") from None

    amenities = village.village_amenities or {}
    crops = sorted({
        value
        for value in (
            (amenities.get("crops") or {}).get("agricultural_commodities") or {}
        ).values()
        if value
    })
    connectivity = amenities.get("connectivity") or {}

    index_row = db.get(ViabilityIndex, (village.village_lgd, archetype_id))

    market_gap_sub_score = None
    population_percentile_bps = None
    catchment_population_proxy = None

    if index_row is not None:
        catchment_population_proxy = index_row.features.get(
            "catchment_population_proxy"
        )

        for score in index_row.geographic_scores:
            if score["name"] == "market_gap":
                market_gap_sub_score = score
            elif score["name"] == "demand" and score["value"] is not None:
                ratio = Fraction(
                    score["value"]["numerator"], score["value"]["denominator"]
                )
                population_percentile_bps = round_half_up(ratio * BPS)

    village_data = {
        "name": village.name,
        "district": village.district,
        "state": village.state,
        "catchment_population_proxy": catchment_population_proxy,
        "nearest_town_name": connectivity.get("nearest_town_name"),
        "nearest_town_distance_km": connectivity.get("nearest_town_distance_km"),
        "reported_crops": crops,
    }

    return {
        "village_data": village_data,
        "archetype": archetype,
        "market_gap_sub_score": market_gap_sub_score,
        "population_percentile_bps": population_percentile_bps,
    }


@router.post("/feasibility-report", response_model=FeasibilityReport)
def feasibility_report(payload: FeasibilityReportRequest, db: Session = Depends(get_db)):
    inputs = _feasibility_report_inputs(
        db, payload.village_lgd, payload.archetype_id
    )

    computed_financials = {
        "project_cost_paise": payload.project_cost_paise,
        "available_for_project_paise": payload.available_for_project_paise,
        "population_percentile_bps": inputs["population_percentile_bps"],
        "market_gap_sub_score": inputs["market_gap_sub_score"],
    }

    try:
        report = generate_feasibility_report(
            inputs["village_data"],
            inputs["archetype"],
            computed_financials,
            payload.lang,
        )
    except LlmError as exc:
        raise _unavailable(exc) from None

    return FeasibilityReport(**report)
