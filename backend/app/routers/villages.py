from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.data.models import Village, ViabilityIndex
from app.schemas import VillageOut

router = APIRouter(prefix="/api/villages", tags=["Geography"])


def village_response(village: Village) -> VillageOut:
    return VillageOut(
        id=village.village_lgd,
        name=village.name,
        district=village.district,
        state=village.state,
        lgd_code=village.village_lgd,
        is_demo=False,
        source=(
            "Imported Census 2011 population + explicit LGD mapping; "
            f"coordinates: {village.coordinate_method}"
        ),
    )


@router.get("", response_model=list[VillageOut])
def list_villages(
    district: str | None = Query(default=None, max_length=100),
    q: str = Query(default="", max_length=100),
    geocoded_only: bool = True,
    limit: int = Query(default=5000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    statement = select(Village)

    if district:
        statement = statement.where(Village.district == district)

    if q.strip():
        # Escape LIKE wildcard characters entered by a user.
        term = (
            q.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        statement = statement.where(
            Village.name.ilike(f"%{term}%", escape="\\")
        )

    if geocoded_only:
        statement = statement.where(Village.geom.is_not(None))

    rows = db.scalars(
        statement.order_by(Village.district, Village.name).limit(limit)
    ).all()

    return [village_response(village) for village in rows]


@router.get("/{village_lgd}/geographic-index")
def geographic_index(
    village_lgd: str,
    db: Session = Depends(get_db),
):
    village = db.get(Village, village_lgd)

    if village is None:
        raise HTTPException(status_code=404, detail="Village not found")

    rows = db.scalars(
        select(ViabilityIndex)
        .where(ViabilityIndex.village_lgd == village_lgd)
        .order_by(ViabilityIndex.archetype_id)
    ).all()

    if not rows:
        raise HTTPException(
            status_code=409,
            detail=(
                "Geographic index unavailable. The village may lack "
                "coordinates, or ingestion invalidated the index. "
                "Run the precompute job."
            ),
        )

    return {
        "village": village_response(village),
        "personalised": False,
        "items": [
            {
                "archetype_id": row.archetype_id,
                "geographic_scores": row.geographic_scores,
                "features": row.features,
                "warnings": row.warnings,
                "known_contribution_bps": row.known_contribution_bps,
                "known_weight_bps": row.known_weight_bps,
                "dataset_signature": row.dataset_signature,
                "model_signature": row.model_signature,
                "computed_at": row.computed_at,
            }
            for row in rows
        ],
    }