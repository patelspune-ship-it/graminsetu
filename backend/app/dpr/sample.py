from pathlib import Path

from .generator import generate_dpr
from .models import DprSessionData


def sample_session() -> DprSessionData:
    return DprSessionData.model_validate({
        "report_id": "GS-DEMO-FLOUR-001",
        "report_date": "2026-01-15",
        "promoter": {
            "name": "Demo Promoter — Not a Real Applicant",
            "village": "Demo village",
            "district": "Pune",
            "state": "Maharashtra",
            "available_for_project_paise": 12_000_000,
            "address": None,
            "education": None,
            "experience": None,
            "skills": ["basic_machine_operation"],
            "premises": "Own premises assumed for this example; unverified",
            "power": "Three-phase connection required; availability unverified",
        },
        "archetype": {
            "id": "flour_mill",
            "name_en": "Small Flour Mill",
            "name_mr": "लघु पीठ गिरणी",
            "category": "agri_processing",
            "catchment_m": 4000,
            "competition_categories": ["flour_mill"],
            "capex_paise": {
                "machinery": 14_500_000,
                "civil": 4_000_000,
                "installation": 1_500_000,
            },
            "required_skills": ["basic_machine_operation"],
            "inputs_required": ["wheat", "gram"],
            "demand_coefficient_bps": 8500,
            "seasonality_bps": [
                9000, 9000, 11000, 13000, 12000, 8000,
                7000, 7000, 9000, 12000, 13000, 10000,
            ],
            "unit_economics": {
                "unit_label": "kg of customer grain milled",
                "revenue_per_unit_paise": 350,
                "units_per_month": 12000,
                "variable_cost_bps": 3500,
                "inventory_eligible_cost_bps": 1000,
                "fixed_monthly_paise": 1_400_000,
                "inventory_days": 15,
                "receivable_days": 2,
                "payable_days": 7,
            },
            "power_requirement": "three_phase",
            "potential_scheme_families": ["PMEGP", "MUDRA"],
            "assumption_status": "illustrative_unverified",
            "assumptions": [
                "Customer-owned grain milling service, not packaged flour manufacturing.",
                "Rated monthly throughput and milling fee require local validation.",
                "Variable costs include electricity and operating consumables.",
                "Own premises assumed; owner drawings are not included in fixed expenses.",
                "Peak throughput implied by seasonality must be checked against machine capacity.",
            ],
        },
        "finance": {
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
        },
        "assumptions": {
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
                "Demo assumes drawings of ₹3,000/month, zero incremental "
                "WC and zero cash tax. These are explicit unverified inputs, "
                "not findings about household needs, WC sufficiency or tax exemption."
            ),
        },
        "employment": {
            "proprietor_roles": 1,
            "paid_full_time_jobs": None,
            "paid_part_time_jobs": None,
            "wage_cost_basis": (
                "Archetype fixed costs are not itemised into wages. "
                "No additional paid jobs are assumed as established."
            ),
        },
        "project_description": (
            "Illustrative small milling service for customer-owned wheat "
            "and gram. Customers retain ownership of grain; revenue is "
            "a milling service fee, not packaged flour sales."
        ),
        "market_observations": [],
        "unknowns": [
            "Household drawings adequacy and initial cash buffer are unverified.",
        ],
        "risk_factors": [],
        "additional_assumptions": [],
        "data_sources": [
            {
                "name": "Hardcoded flour-mill archetype snapshot",
                "reference": "app/dpr/sample.py; mirrors supplied flour_mill.json",
                "status": "Illustrative, unverified costs and unit economics.",
            },
            {
                "name": "Hardcoded demonstration inputs",
                "reference": "app/dpr/sample.py",
                "status": (
                    "Fictional promoter and financing scenario. "
                    "No lender terms or eligibility verified."
                ),
            },
            {
                "name": "Local market evidence",
                "reference": "Not supplied for this demo",
                "status": (
                    "No Census, OSM or village precomputed rows were consumed "
                    "by this sample; no local counts are asserted."
                ),
            },
        ],
    })


def make_sample_dpr(
    out_path: str | Path = "artifacts/graminsetu_sample_dpr.pdf",
) -> str:
    return generate_dpr(sample_session(), out_path)


if __name__ == "__main__":
    print(make_sample_dpr())