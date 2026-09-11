import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.advisory_schemas import (
    CapitalStackOut,
    CapitalStackRequest,
    DprGenerateRequest,
    DprOut,
    ErrorOut,
    FinancialModelOut,
    FinancialModelRequest,
    RankedOptionOut,
    ViabilityItemOut,
    ViabilityOut,
    ViabilityResultOut,
)
from app.advisory_service import (
    build_dpr_data,
    calculate_snapshot,
    exact_json,
    load_profile,
)
from app.api_errors import ApiError
from app.archetypes import ARCHETYPES
from app.data.models import Village, ViabilityIndex
from app.db import get_db
from app.dpr import DprSessionData, generate_dpr
from app.fin.core import apply_bps, project_cost
from app.models import AdvisorySession
from app.viability.cached import personalize_cached_scores

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["Advisory"],
    responses={
        status: {"model": ErrorOut}
        for status in (404, 409, 422, 500)
    },
)

RANKING_POLICY = (
    "Feasible options first, then lower peak monthly debt service, "
    "then offer ID for deterministic ties. This is an affordability "
    "ordering, not a cheapest-credit recommendation. Interest totals "
    "across unequal offer horizons are not used for ranking."
)


def dpr_directory() -> Path:
    return Path(
        os.environ.get("DPR_OUTPUT_DIR", "artifacts/dpr")
    ).expanduser().resolve()


def artifact_path(artifact_id: str) -> Path:
    # Stored IDs must also pass validation. Never resolve arbitrary paths.
    canonical_id = str(UUID(artifact_id))
    return dpr_directory() / f"{canonical_id}.pdf"


def dpr_response(session_id: str) -> DprOut:
    return DprOut(
        session_id=session_id,
        status="dpr_ready",
        download_url=f"/api/dpr/{session_id}/download",
    )


@router.get(
    "/villages/{village_lgd}/viability",
    response_model=ViabilityOut,
)
def personalized_viability(
    village_lgd: str,
    assessment_id: UUID,
    contribution_assumption_bps: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    _, profile = load_profile(db, assessment_id)

    if profile.village_id != village_lgd:
        raise ApiError(
            409,
            "ASSESSMENT_VILLAGE_MISMATCH",
            "The assessment belongs to a different village.",
        )

    basis = (
        "Recorded profile capital divided by an illustrative own-contribution "
        "requirement at base scale. Profile capital is not assumed to be net "
        "of emergency reserves. This is not loan eligibility or affordability."
    )

    village = db.get(Village, village_lgd)
    rows = []
    if village is not None:
        rows = db.scalars(
            select(ViabilityIndex)
            .where(ViabilityIndex.village_lgd == village_lgd)
            .order_by(ViabilityIndex.archetype_id)
        ).all()

    known_rows = [
        row for row in rows if row.archetype_id in ARCHETYPES
    ]
    covered_ids = {row.archetype_id for row in known_rows}
    missing_ids = sorted(set(ARCHETYPES) - covered_ids)

    items = []
    for row in known_rows:
        archetype = ARCHETYPES[row.archetype_id]
        project = project_cost(archetype)

        required_own = apply_bps(
            project.project_cost_paise,
            contribution_assumption_bps,
        )

        warnings = [
            *row.warnings,
            "Capital contribution is an illustrative scenario assumption.",
        ]
        if not profile.skills:
            warnings.append(
                "No skills are recorded. Historical profiles cannot distinguish "
                "an omitted skill selection from an explicitly empty selection."
            )

        result = personalize_cached_scores(
            geographic_scores=row.geographic_scores,
            user_skills=set(profile.skills),
            required_skills=set(archetype.required_skills),
            user_capital_paise=profile.own_capital_paise,
            required_own_contribution_paise=required_own,
            warnings=warnings,
        )

        items.append(
            ViabilityItemOut(
                archetype_id=row.archetype_id,
                required_own_contribution_paise=required_own,
                result=ViabilityResultOut.model_validate(exact_json(result)),
                dataset_signature=row.dataset_signature,
                model_signature=row.model_signature,
                computed_at=row.computed_at,
            )
        )

    if not items:
        status = "OUT_OF_COVERAGE"
        message = (
            "No usable precomputed index is available for this village. "
            "Coordinates may be unavailable, or the index may need recomputation."
        )
    elif missing_ids:
        status = "PARTIAL_COVERAGE"
        message = "Precomputed results are available for only some archetypes."
    else:
        status = "OK"
        message = (
            "Cached geographic scores personalized with recorded skills "
            "and capital. Individual results may still be INSUFFICIENT_DATA."
        )

    return ViabilityOut(
        village_lgd=village_lgd,
        assessment_id=str(assessment_id),
        status=status,
        message=message,
        contribution_assumption_bps=contribution_assumption_bps,
        capital_fit_basis=basis,
        missing_archetype_ids=missing_ids,
        items=items,
    )


@router.post(
    "/financial-model",
    response_model=FinancialModelOut,
    status_code=201,
)
def financial_model(
    payload: FinancialModelRequest,
    db: Session = Depends(get_db),
):
    data = build_dpr_data(
        db, payload, payload.finance, payload.narrative,
        feasibility_report=payload.feasibility_report,
        tenure_override_months=payload.tenure_override_months,
        moratorium_override_months=payload.moratorium_override_months,
    )
    snapshot = calculate_snapshot(data)

    session_id = str(uuid4())
    _, profile = load_profile(db, payload.assessment_id)

    record = AdvisorySession(
        id=session_id,
        village_id=profile.village_id,
        status="modelled",
        payload_version=1,
        session_data={
            "kind": "financial_model",
            "request": payload.model_dump(mode="json"),
            "dpr": data.model_dump(mode="json"),
        },
        financial_model=snapshot.model_dump(mode="json"),
        capital_stack=exact_json(snapshot.stack),
    )
    db.add(record)
    db.commit()

    return FinancialModelOut(
        session_id=session_id,
        status="modelled",
        assumption_status="illustrative_unverified",
        snapshot=snapshot,
    )


@router.post(
    "/capital-stack",
    response_model=CapitalStackOut,
    status_code=201,
)
def capital_stack(
    payload: CapitalStackRequest,
    db: Session = Depends(get_db),
):
    scenarios = []
    options = []

    # Calculate each offer separately: its interest affects cash tax,
    # so pre-debt surplus can differ between offers.
    for offer in payload.offers:
        data = build_dpr_data(db, payload, offer)
        snapshot = calculate_snapshot(data)

        scenarios.append({
            "offer_id": offer.id,
            "dpr": data.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
        })
        options.append((offer, snapshot.stack))

    options.sort(
        key=lambda item: (
            not item[1].feasible,
            item[1].max_monthly_debt_service_paise,
            item[1].offer_id,
        )
    )

    session_id = str(uuid4())
    response = CapitalStackOut(
        session_id=session_id,
        status="capital_stack_calculated",
        assumption_status="illustrative_unverified",
        ranking_policy=RANKING_POLICY,
        options=[
            RankedOptionOut(
                rank=rank,
                tenure_months=offer.tenure_months,
                result=result,
            )
            for rank, (offer, result) in enumerate(options, start=1)
        ],
    )

    _, profile = load_profile(db, payload.assessment_id)
    db.add(
        AdvisorySession(
            id=session_id,
            village_id=profile.village_id,
            status="capital_stack_calculated",
            payload_version=1,
            session_data={
                "kind": "capital_stack",
                "request": payload.model_dump(mode="json"),
                "scenarios": scenarios,
            },
            capital_stack=response.model_dump(mode="json"),
        )
    )
    db.commit()
    return response


@router.post("/dpr/generate", response_model=DprOut)
def create_dpr(
    payload: DprGenerateRequest,
    db: Session = Depends(get_db),
):
    session_id = str(payload.session_id)
    record = db.get(AdvisorySession, session_id)

    if record is None:
        raise ApiError(404, "SESSION_NOT_FOUND", "Advisory session not found.")

    if record.status == "dpr_ready":
        if (
            record.dpr_artifact_id
            and artifact_path(record.dpr_artifact_id).is_file()
        ):
            return dpr_response(session_id)
        raise ApiError(
            409,
            "DPR_ARTIFACT_MISSING",
            "The generated report is no longer available.",
            session_id,
        )

    if (
        record.payload_version != 1
        or record.session_data.get("kind") != "financial_model"
    ):
        raise ApiError(
            409,
            "FINANCIAL_MODEL_REQUIRED",
            "Create a financial model for the selected offer before generating a DPR.",
            session_id,
        )

    if record.status not in {"modelled", "dpr_failed"}:
        raise ApiError(
            409,
            "SESSION_NOT_READY",
            "This session is not ready for PDF generation.",
            session_id,
        )

    # Stored-data validation failures are internal errors, not malformed
    # HTTP request errors.
    data = DprSessionData.model_validate(record.session_data["dpr"])

    # Refuse to silently generate a PDF using changed calculation behavior.
    current = calculate_snapshot(data).model_dump(mode="json")
    if current != record.financial_model:
        raise ApiError(
            409,
            "MODEL_CHANGED",
            "Recreate the financial model before generating this report.",
            session_id,
        )

    artifact_id = str(uuid4())

    # Atomic claim prevents simultaneous generation for the same session.
    claim = db.execute(
        update(AdvisorySession)
        .where(
            AdvisorySession.id == session_id,
            AdvisorySession.status.in_(["modelled", "dpr_failed"]),
        )
        .values(
            status="dpr_generating",
            dpr_artifact_id=artifact_id,
            dpr_generated_at=None,
            last_error_code=None,
        )
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        db.rollback()
        raise ApiError(
            409,
            "DPR_ALREADY_GENERATING",
            "Another request is already generating this report.",
            session_id,
        )
    db.commit()

    target = artifact_path(artifact_id)

    try:
        # Existing generator already performs temporary-write + atomic replace.
        generate_dpr(data, target)
        if not target.is_file():
            raise RuntimeError("Generator did not publish a PDF")
    except Exception:
        logger.exception("DPR generation failed for session %s", session_id)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not clean failed DPR artifact")

        db.rollback()
        db.execute(
            update(AdvisorySession)
            .where(
                AdvisorySession.id == session_id,
                AdvisorySession.dpr_artifact_id == artifact_id,
            )
            .values(
                status="dpr_failed",
                dpr_artifact_id=None,
                dpr_generated_at=None,
                last_error_code="DPR_GENERATION_FAILED",
            )
        )
        db.commit()

        raise ApiError(
            500,
            "DPR_GENERATION_FAILED",
            "The report could not be generated. You may retry this session.",
            session_id,
        ) from None

    db.execute(
        update(AdvisorySession)
        .where(
            AdvisorySession.id == session_id,
            AdvisorySession.dpr_artifact_id == artifact_id,
            AdvisorySession.status == "dpr_generating",
        )
        .values(
            status="dpr_ready",
            dpr_generated_at=datetime.now(timezone.utc),
            last_error_code=None,
        )
    )
    db.commit()

    return dpr_response(session_id)


@router.get(
    "/dpr/{session_id}/download",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_dpr(
    session_id: UUID,
    db: Session = Depends(get_db),
):
    record = db.get(AdvisorySession, str(session_id))
    if record is None:
        raise ApiError(404, "SESSION_NOT_FOUND", "Advisory session not found.")

    if record.status != "dpr_ready" or not record.dpr_artifact_id:
        raise ApiError(
            409, "DPR_NOT_READY", "A generated PDF is not ready for this session."
        )

    path = artifact_path(record.dpr_artifact_id)
    if not path.is_file():
        raise ApiError(
            404, "DPR_ARTIFACT_MISSING", "The generated PDF is unavailable."
        )

    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename=f"GraminSetu-{session_id}.pdf",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )