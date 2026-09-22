"""Persistent cache in front of app.llm.feasibility_report.

A demo/recording must never depend on live Gemini quota: once a
(village, archetype, language) combination has been generated for a
given set of computed financials, every later identical request is
served from the database and never calls Gemini.

The cache key covers everything that can change the generated
narrative (village data, computed financials, language) — never just
village_lgd/archetype_id/lang — so a changed input is always a miss,
never a stale hit.
"""

import hashlib
import json
import logging

from sqlalchemy.orm import Session

from app.archetypes.schema import Archetype
from app.llm.feasibility_report import generate_feasibility_report
from app.models import FeasibilityReportCache

logger = logging.getLogger(__name__)


def cache_key(
    village_lgd: str,
    archetype_id: str,
    village_data: dict,
    computed_financials: dict,
    lang: str,
) -> str:
    canonical = json.dumps(
        {
            "village_lgd": village_lgd,
            "archetype_id": archetype_id,
            "village_data": village_data,
            "computed_financials": computed_financials,
            "lang": lang,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_or_generate_feasibility_report(
    db: Session,
    village_lgd: str,
    archetype: Archetype,
    village_data: dict,
    computed_financials: dict,
    lang: str,
) -> dict:
    """Cache-aware wrapper around generate_feasibility_report.

    A cache hit returns the stored report and never calls Gemini. A miss
    generates once, then best-effort persists it — a failed cache write
    must never turn a successful generation into an error response.
    """
    key = cache_key(
        village_lgd, archetype.id, village_data, computed_financials, lang
    )

    cached = db.get(FeasibilityReportCache, key)
    if cached is not None:
        return cached.report

    report = generate_feasibility_report(
        village_data, archetype, computed_financials, lang
    )

    try:
        db.add(
            FeasibilityReportCache(
                cache_key=key,
                village_lgd=village_lgd,
                archetype_id=archetype.id,
                lang=lang,
                report=report,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "Failed to persist feasibility report cache entry", exc_info=True
        )

    return report
