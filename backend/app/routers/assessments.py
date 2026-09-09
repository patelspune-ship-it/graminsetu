from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.data.models import Village
from app.fixtures import VILLAGE_BY_ID
from app.models import Assessment
from app.routers.villages import village_response
from app.schemas import AssessmentOut, ProfileCreate, VillageOut

router = APIRouter(prefix="/api/assessments", tags=["Assessments"])


def serialize(assessment: Assessment, db: Session) -> AssessmentOut:
    village_id = assessment.profile["village_id"]
    village = db.get(Village, village_id)

    if village:
        output_village = village_response(village)
    elif village_id in VILLAGE_BY_ID:
        # Historical development profiles only.
        output_village = VillageOut(**VILLAGE_BY_ID[village_id])
    else:
        raise HTTPException(
            status_code=409,
            detail="Assessment geography is no longer present in the dataset",
        )

    return AssessmentOut(
        id=assessment.id,
        created_at=assessment.created_at,
        status=assessment.status,
        profile=assessment.profile,
        village=output_village,
    )


@router.post("", response_model=AssessmentOut, status_code=201)
def create_assessment(
    payload: ProfileCreate,
    db: Session = Depends(get_db),
):
    village = db.get(Village, payload.village_id)

    if village is None:
        raise HTTPException(
            status_code=422,
            detail="Choose a village from the imported geography dataset",
        )

    assessment = Assessment(profile=payload.model_dump())

    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    return serialize(assessment, db)


@router.get("/{assessment_id}", response_model=AssessmentOut)
def get_assessment(
    assessment_id: UUID,
    db: Session = Depends(get_db),
):
    assessment = db.get(Assessment, str(assessment_id))

    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")

    return serialize(assessment, db)