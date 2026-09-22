"""Pre-generate and cache feasibility reports for the demo villages.

Populates app.llm.feasibility_report_cache for a fixed set of
(village, archetype, language) combinations, using a persistent demo
Assessment per village and the exact same financial-model computation
the live UI runs on first "Generate" (PRIMARY_FINANCE_OFFER-equivalent
finance terms, default ps_scheme assumptions, full own capital as the
project contribution) — so a live demo that follows the same steps
without editing the capital field lands on the same cache key.

Usage:
    python -m app.data.pregenerate_demo_cache
    python -m app.data.pregenerate_demo_cache --verify-only

--verify-only skips generation and only re-checks that every combination
is already cached and that a cache hit does not call Gemini.
"""

import argparse
import time
import uuid

from sqlalchemy.orm import Session

import app.llm.gemini_client as gemini_client
from app.advisory_schemas import FinancialModelRequest
from app.advisory_service import build_dpr_data, calculate_snapshot
from app.data.common import initialize_database
from app.db import engine
from app.llm import LlmError, LlmRateLimitedError
from app.llm import feasibility_report_cache
from app.llm.feasibility_report_cache import (
    cache_key,
    get_or_generate_feasibility_report,
)
from app.models import Assessment, FeasibilityReportCache
from app.routers.llm import _feasibility_report_inputs

# LGD codes confirmed against the imported Nashik dataset.
DEMO_VILLAGES = {
    "550134": "Chaugaon",
    "550104": "Bhawade",
    "550150": "Ajmir Saundane",
}

DEMO_ARCHETYPES = ["dairy_collection", "onion_storage"]
DEMO_LANGUAGES = ["en", "hi", "mr"]

# Round demo figure -> ps_scheme project cost of Rs 20,00,000 (margin x10),
# comfortably inside the Term Loan Scheme band. Skills cover both demo
# archetypes' required_skills so the Viability screen also looks sane.
DEMO_OWN_CAPITAL_PAISE = 20_000_000
DEMO_SKILLS = ["animal_husbandry", "farming", "bookkeeping"]

# Matches frontend/src/financeOffers.js PRIMARY_FINANCE_OFFER exactly —
# the terms the Financing screen submits before any customization.
PRIMARY_FINANCE_OFFER = {
    "id": "ILLUSTRATIVE-TERM-60M",
    "annual_rate_bps": 1100,
    "tenure_months": 60,
    "moratorium_months": 3,
    "step_up": True,
    "cc_annual_rate_bps": 1200,
    "min_own_contribution_bps": 1000,
    "max_term_loan_paise": None,
    "eligibility_confirmed": None,
    "pending_backended_subsidy_paise": 0,
}

# Matches frontend/src/financeOffers.js defaultAssumptions() exactly.
DEFAULT_ASSUMPTIONS = {
    "cost_model": "ps_scheme",
    "scale_bps": 10_000,
    "preliminary_bps": 300,
    "contingency_bps": 500,
    "wc_margin_bps": 2500,
    "yoy_growth_bps": 800,
    "fixed_cost_growth_bps": 500,
    "start_calendar_month": 1,
    "depreciation_bps": 1500,
    "tax_bps": 0,
    "minimum_dscr_bps": 12_500,
    "additional_wc_paise": [0] * 60,
    "owner_drawings_paise": [300_000] * 60,
    "adjustment_basis": (
        "Default scenario assumes drawings of Rs 3,000/month, zero "
        "incremental working capital and zero cash tax. These are "
        "explicit unverified inputs, not findings about household "
        "needs or tax exemption."
    ),
}

# Fixed namespace so re-running this script resolves to the SAME
# assessment id per village instead of creating duplicates.
_DEMO_NAMESPACE = uuid.UUID("f3b5b8b0-3e9e-4b7a-8b7a-3e9e4b7a8b7a")


def demo_assessment_id(village_lgd: str) -> str:
    return str(uuid.uuid5(_DEMO_NAMESPACE, f"graminsetu-demo-{village_lgd}"))


def ensure_demo_assessment(db: Session, village_lgd: str, village_name: str) -> Assessment:
    assessment_id = demo_assessment_id(village_lgd)
    assessment = db.get(Assessment, assessment_id)

    if assessment is not None:
        return assessment

    assessment = Assessment(
        id=assessment_id,
        profile={
            "applicant_name": f"Demo Applicant — {village_name}",
            "village_id": village_lgd,
            "preferred_language": "en",
            "own_capital_paise": DEMO_OWN_CAPITAL_PAISE,
            "skills": DEMO_SKILLS,
            "premises": "owned",
            "power": "single_phase",
        },
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def compute_financials(db: Session, assessment_id: str, archetype_id: str) -> dict:
    """Exactly replicates the live /financial-model call the Financing
    screen makes on first "Generate" (see FinancingStep.jsx runQuery),
    so the cache key this produces matches what a live demo click-through
    produces."""
    payload = FinancialModelRequest.model_validate({
        "assessment_id": assessment_id,
        "archetype_id": archetype_id,
        "available_for_project_paise": DEMO_OWN_CAPITAL_PAISE,
        "finance": PRIMARY_FINANCE_OFFER,
        "assumptions": DEFAULT_ASSUMPTIONS,
    })

    data = build_dpr_data(db, payload, payload.finance, payload.narrative)
    snapshot = calculate_snapshot(data)

    return {
        "project_cost_paise": snapshot.project.project_cost_paise,
        "available_for_project_paise": snapshot.stack.own_contribution_paise,
    }


def generate_with_retry(db, village_lgd, archetype, village_data, computed_financials, lang):
    # Retries both quota (429) and transient upstream failures (502/503) —
    # Gemini's own service hiccups are exactly as retryable as a rate
    # limit for a batch pre-generation run like this one.
    delays = [5, 20, 60, 120, 120]
    attempt_is_rate_limited = [False]
    for attempt, delay in enumerate([0, *delays]):
        if delay:
            reason = "rate limited" if attempt_is_rate_limited[0] else "upstream error"
            print(f"    {reason}; retrying in {delay}s…")
            time.sleep(delay)
        try:
            return get_or_generate_feasibility_report(
                db, village_lgd, archetype, village_data, computed_financials, lang
            )
        except LlmError as exc:
            attempt_is_rate_limited[0] = isinstance(exc, LlmRateLimitedError)
            if attempt == len(delays):
                raise


def run_generation(db: Session) -> list[dict]:
    rows = []

    for village_lgd, village_name in DEMO_VILLAGES.items():
        assessment = ensure_demo_assessment(db, village_lgd, village_name)

        for archetype_id in DEMO_ARCHETYPES:
            financials_base = compute_financials(db, assessment.id, archetype_id)
            inputs = _feasibility_report_inputs(db, village_lgd, archetype_id)

            computed_financials = {
                **financials_base,
                "population_percentile_bps": inputs["population_percentile_bps"],
                "market_gap_sub_score": inputs["market_gap_sub_score"],
            }

            for lang in DEMO_LANGUAGES:
                key = cache_key(
                    village_lgd, archetype_id, inputs["village_data"],
                    computed_financials, lang,
                )
                already_cached = db.get(FeasibilityReportCache, key) is not None

                print(
                    f"{village_name} ({village_lgd}) / {archetype_id} / {lang}: "
                    + ("cached" if already_cached else "generating…")
                )

                start = time.monotonic()
                try:
                    generate_with_retry(
                        db, village_lgd, inputs["archetype"], inputs["village_data"],
                        computed_financials, lang,
                    )
                except LlmError as exc:
                    print(f"    FAILED: {exc}")
                    rows.append({
                        "village": village_name, "village_lgd": village_lgd,
                        "archetype_id": archetype_id, "lang": lang,
                        "status": "failed", "error": str(exc),
                    })
                    continue

                elapsed = time.monotonic() - start
                rows.append({
                    "village": village_name, "village_lgd": village_lgd,
                    "archetype_id": archetype_id, "lang": lang,
                    "status": "cached" if already_cached else "generated",
                    "elapsed_s": round(elapsed, 2),
                    "project_cost_paise": computed_financials["project_cost_paise"],
                    "available_for_project_paise": computed_financials["available_for_project_paise"],
                    "assessment_id": assessment.id,
                })

                # Real Gemini calls only — stay well clear of rate limits
                # while warming 18 combinations in one run.
                if not already_cached:
                    time.sleep(2)

    return rows


def verify_cache_hits_skip_gemini(db: Session, rows: list[dict]) -> bool:
    """Blocks the Gemini client entirely, then re-requests every
    successfully cached combination — proving each is served from the
    database, never the network, and that it is fast."""
    original_post = gemini_client.httpx.post

    def blocked(*args, **kwargs):
        raise AssertionError("Gemini was called during a cache-hit verification pass")

    gemini_client.httpx.post = blocked
    ok = True

    try:
        for row in rows:
            if row["status"] == "failed":
                continue

            inputs = _feasibility_report_inputs(db, row["village_lgd"], row["archetype_id"])
            computed_financials = {
                "project_cost_paise": row["project_cost_paise"],
                "available_for_project_paise": row["available_for_project_paise"],
                "population_percentile_bps": inputs["population_percentile_bps"],
                "market_gap_sub_score": inputs["market_gap_sub_score"],
            }

            start = time.monotonic()
            try:
                get_or_generate_feasibility_report(
                    db, row["village_lgd"], inputs["archetype"], inputs["village_data"],
                    computed_financials, row["lang"],
                )
            except Exception as exc:  # noqa: BLE001 — report, don't crash the verify pass
                ok = False
                print(
                    f"  MISS/ERROR {row['village']}/{row['archetype_id']}/{row['lang']}: {exc}"
                )
                continue

            elapsed_ms = (time.monotonic() - start) * 1000
            print(
                f"  OK {row['village']}/{row['archetype_id']}/{row['lang']}: "
                f"{elapsed_ms:.1f} ms, no Gemini call"
            )
    finally:
        gemini_client.httpx.post = original_post

    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Skip generation; only verify existing cache entries never call Gemini.",
    )
    args = parser.parse_args()

    initialize_database()

    with Session(engine) as db:
        if args.verify_only:
            rows = []
            for village_lgd, village_name in DEMO_VILLAGES.items():
                assessment_id = demo_assessment_id(village_lgd)
                for archetype_id in DEMO_ARCHETYPES:
                    financials_base = compute_financials(db, assessment_id, archetype_id)
                    for lang in DEMO_LANGUAGES:
                        rows.append({
                            "village": village_name, "village_lgd": village_lgd,
                            "archetype_id": archetype_id, "lang": lang,
                            "status": "generated", **financials_base,
                        })
        else:
            print("=== Generating (real Gemini calls on cache misses) ===")
            rows = run_generation(db)

        print("\n=== Verifying cache hits never call Gemini ===")
        ok = verify_cache_hits_skip_gemini(db, rows)

        failed = [row for row in rows if row["status"] == "failed"]
        print(f"\n{len(rows) - len(failed)}/{len(rows)} combinations cached.")
        if failed:
            print(f"{len(failed)} FAILED to generate:")
            for row in failed:
                print(f"  {row['village']}/{row['archetype_id']}/{row['lang']}: {row['error']}")

        print("All cache hits served without a Gemini call." if ok else "VERIFICATION FAILED.")


if __name__ == "__main__":
    main()
