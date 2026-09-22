from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_RADIUS_M = 10_000

# village_amenities.markets facility keys treated as "market" facilities
# for this count (see app/data/amenities.py FACILITY_COLUMNS). Finance
# facilities (banks, SHGs, credit societies) are a different semantic
# category and are not counted here.
_MARKET_FACILITY_NAMES = (
    "mandis_regular_market",
    "weekly_haat",
    "agricultural_marketing_society",
    "pds_shop",
)

# Villages whose representative point falls within the radius of an
# arbitrary point (not necessarily a village centroid). Geography columns
# compare in metres directly, so ST_DWithin needs no unit conversion.
CATCHMENT_QUERY = text("""
SELECT village_lgd, population, village_amenities
FROM villages
WHERE geom IS NOT NULL
  AND ST_DWithin(
    geom,
    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
    :radius_m
  )
""")


@dataclass(frozen=True)
class LocationCatchment:
    radius_m: int
    village_count: int
    catchment_population: int
    market_facility_count: int


def compute_location_catchment(
    db: Session,
    latitude: float,
    longitude: float,
    radius_m: int = DEFAULT_RADIUS_M,
) -> LocationCatchment:
    """Read-only catchment context around an arbitrary point (e.g. a map
    pin), independent of and additive to the village_lgd scoring path.

    Never invents evidence: villages with no geom simply cannot appear in
    this radius, and a village with no village_amenities contributes 0 to
    the facility count rather than being skipped or estimated.
    """
    rows = db.execute(
        CATCHMENT_QUERY,
        {"latitude": latitude, "longitude": longitude, "radius_m": radius_m},
    ).mappings().all()

    catchment_population = sum(int(row["population"]) for row in rows)

    market_facility_count = 0
    for row in rows:
        markets = (row["village_amenities"] or {}).get("markets") or {}
        market_facility_count += sum(
            1
            for name in _MARKET_FACILITY_NAMES
            if (markets.get(name) or {}).get("available") is True
        )

    return LocationCatchment(
        radius_m=radius_m,
        village_count=len(rows),
        catchment_population=catchment_population,
        market_facility_count=market_facility_count,
    )
