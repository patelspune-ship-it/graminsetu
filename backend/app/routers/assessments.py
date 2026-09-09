from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.fixtures import VILLAGE_BY_ID
from app.models import Assessment
from app.schemas import AssessmentOut, ProfileCreate

router = APIRouter(prefix="/api/assessments", tags=["Assessments"])


def serialize(assessment: Assessment) -> AssessmentOut:
    village = VILLAGE_BY_ID.get(assessment.profile["village_id"])

    if village is None:
        raise HTTPException(
            status_code=409,
            detail="Assessment geography is no longer available.",
        )

    return AssessmentOut(
        id=assessment.id,
        created_at=assessment.created_at,
        status=assessment.status,
        profile=assessment.profile,
        village=village,
    )


@router.post("", response_model=AssessmentOut, status_code=201)
def create_assessment(
    payload: ProfileCreate,
    db: Session = Depends(get_db),
):
    if payload.village_id not in VILLAGE_BY_ID:
        raise HTTPException(
            status_code=422,
            detail="Choose a village from the available records.",
        )

    assessment = Assessment(profile=payload.model_dump())

    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    return serialize(assessment)


@router.get("/{assessment_id}", response_model=AssessmentOut)
def get_assessment(
    assessment_id: UUID,
    db: Session = Depends(get_db),
):
    assessment = db.get(Assessment, str(assessment_id))

    if assessment is None:
        raise HTTPException(
            status_code=404,
            detail="Assessment not found.",
        )

    return serialize(assessment)
