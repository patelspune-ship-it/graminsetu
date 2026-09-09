from fastapi import APIRouter, Query

from app.fixtures import DEMO_VILLAGES
from app.schemas import VillageOut

router = APIRouter(prefix="/api/villages", tags=["Geography"])


@router.get("", response_model=list[VillageOut])
def list_villages(
    district: str | None = Query(default=None, max_length=100),
    q: str = Query(default="", max_length=100),
):
    records = DEMO_VILLAGES

    if district:
        records = [
            item for item in records
            if item["district"].casefold() == district.casefold()
        ]

    if q.strip():
        term = q.strip().casefold()
        records = [
            item for item in records
            if term in item["name"].casefold()
        ]

    return records
