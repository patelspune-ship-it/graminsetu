from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from fractions import Fraction
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.advisory_schemas import (
    FinanceInput,
    NarrativeInput,
    ScenarioInput,
    SnapshotOut,
)
from app.api_errors import ApiError
from app.archetypes import get_archetype
from app.data.models import Village
from app.dpr.financials import (
    ReconciliationError,
    calculate_financials,
)
from app.dpr.models import DprSessionData
from app.fin.ps_scheme import SchemeOutOfScopeError
from app.models import Assessment
from app.schemas import ProfileCreate


def exact_json(value):
    """Convert domain results without converting Fraction or money to float."""
    if isinstance(value, Fraction):
        return {
            "numerator": value.numerator,
            "denominator": value.denominator,
        }

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: exact_json(getattr(value, field.name))
            for field in fields(value)
        }

    if isinstance(value, dict):
        return {key: exact_json(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [exact_json(item) for item in value]

    if isinstance(value, float):
        raise TypeError("Financial snapshots must not contain floats")

    return value


def load_archetype(archetype_id: str):
    try:
        return get_archetype(archetype_id)
    except KeyError:
        raise ApiError(
            404, "ARCHETYPE_NOT_FOUND", "Archetype not found."
        ) from None


def load_profile(db: Session, assessment_id):
    assessment = db.get(Assessment, str(assessment_id))
    if assessment is None:
        raise ApiError(
            404, "ASSESSMENT_NOT_FOUND", "Assessment not found."
        )

    raw = assessment.profile
    if not isinstance(raw, dict) or not {
        "own_capital_paise",
        "skills",
        "village_id",
    }.issubset(raw):
        raise ApiError(
            409,
            "ASSESSMENT_PROFILE_INCOMPLETE",
            "Complete the assessment profile before continuing.",
        )

    try:
        profile = ProfileCreate.model_validate(raw)
    except ValidationError:
        raise ApiError(
            409,
            "ASSESSMENT_PROFILE_INVALID",
            "The stored assessment profile needs to be updated.",
        ) from None

    return assessment, profile


def build_dpr_data(
    db: Session,
    payload: ScenarioInput,
    finance: FinanceInput,
    narrative: NarrativeInput | None = None,
) -> DprSessionData:
    _, profile = load_profile(db, payload.assessment_id)
    archetype = load_archetype(payload.archetype_id)

    village = db.get(Village, profile.village_id)
    if village is None:
        raise ApiError(
            409,
            "ASSESSMENT_GEOGRAPHY_UNAVAILABLE",
            "The assessment village is no longer in the imported dataset.",
        )

    if payload.available_for_project_paise > profile.own_capital_paise:
        raise ApiError(
            422,
            "PROJECT_FUNDS_EXCEED_PROFILE_CAPITAL",
            "Project funds cannot exceed the capital recorded in the assessment.",
        )

    narrative = narrative or NarrativeInput()

    return DprSessionData(
        report_id=f"GS-{uuid4()}",
        report_date=datetime.now(timezone.utc).date().isoformat(),
        promoter={
            "name": profile.applicant_name,
            "village": village.name,
            "district": village.district,
            "state": village.state,
            "available_for_project_paise": payload.available_for_project_paise,
            "skills": list(profile.skills),
            "premises": f"Applicant-reported: {profile.premises}; unverified",
            "power": f"Applicant-reported: {profile.power}; unverified",
        },
        archetype=archetype,
        finance=finance.model_dump(),
        assumptions=payload.assumptions,
        employment=narrative.employment,
        project_description=(
            narrative.project_description
            or f"Illustrative {archetype.name_en} scenario; local validation required."
        ),
        market_observations=narrative.market_observations,
        unknowns=[
            *narrative.unknowns,
            "Lender terms, eligibility and applicant-reported inputs require verification.",
            "No personalized geographic viability result is incorporated in this report.",
        ],
        risk_factors=narrative.risk_factors,
        additional_assumptions=narrative.additional_assumptions,
        data_sources=[
            {
                "name": "Archetype configuration snapshot",
                "reference": f"app/archetypes/configs/{archetype.id}.json",
                "status": "Illustrative, unverified costs and unit economics.",
            },
            {
                "name": "Assessment profile and scenario inputs",
                "reference": f"assessment:{payload.assessment_id}",
                "status": "Applicant-supplied information; not independently verified.",
            },
            {
                "name": "Imported village identity",
                "reference": f"village_lgd:{village.village_lgd}",
                "status": (
                    "Village identity only. No local market counts or "
                    "geographic viability findings are asserted."
                ),
            },
        ],
    )


def calculate_snapshot(data: DprSessionData) -> SnapshotOut:
    try:
        snapshot = calculate_financials(data)
    except ReconciliationError:
        # An internal invariant failure is NOT invalid user input.
        raise
    except SchemeOutOfScopeError as exc:
        # This message is PS-mandated and user-facing, not an internal detail.
        raise ApiError(
            422,
            "PROJECT_COST_OUT_OF_SCOPE",
            str(exc),
        ) from None
    except ValueError:
        # Do not leak internal exception messages to the client.
        raise ApiError(
            422,
            "INVALID_FINANCIAL_SCENARIO",
            "The financial engine rejected these scenario parameters.",
        ) from None

    return SnapshotOut.model_validate(exact_json(snapshot))