from .financials import FinancialSnapshot, annual_tables
from .formatting import bps_percent, indian_currency
from .models import DprSessionData


DISCLAIMER = (
    "Figures are projections from stated assumptions. "
    "Illustrative capex, not verified quotations. "
    "Not lender-approved advice."
)


def build_context(
    data: DprSessionData,
    snapshot: FinancialSnapshot,
) -> dict:
    a = data.assumptions
    p = snapshot.project
    s = snapshot.stack
    promoter = data.promoter

    unknowns = [
        "Equipment specifications, quantities, supplier identities and "
        "written quotations have not been established by this report.",
        "Local demand, achieved milling fee, competitor capacity and "
        "customer commitments are not independently verified.",
        "Required registrations, site suitability, power connection "
        "and lender sanction require documentary verification.",
    ]

    for label, value in [
        ("Promoter address", promoter.address),
        ("Education", promoter.education),
        ("Relevant experience", promoter.experience),
        ("Premises arrangements", promoter.premises),
        ("Power availability", promoter.power),
    ]:
        if value is None:
            unknowns.append(f"{label}: not established.")

    if not promoter.skills:
        unknowns.append("Promoter skills: not established.")

    if data.finance.eligibility_confirmed is None:
        unknowns.append("Scheme/lender eligibility: not verified.")

    unknowns.extend(data.unknowns)
    unknowns = list(dict.fromkeys(unknowns))

    pnl_table, cash_table = annual_tables(snapshot, data)

    machinery = [
        ("Machinery — itemisation pending", p.machinery_paise),
        ("Civil works — not machinery", p.civil_paise),
        ("Installation — not machinery", p.installation_paise),
    ]

    costs = machinery + [
        ("Preliminary expenses", p.preliminary_paise),
        ("Contingency", p.contingency_paise),
        ("Working-capital margin", p.working_capital.margin_paise),
        ("TOTAL PROJECT COST", p.project_cost_paise),
    ]

    means = [
        ("Promoter contribution", s.own_contribution_paise),
        ("Proposed term loan", s.term_loan_paise),
        (
            "TOTAL MEANS OF FINANCE",
            s.own_contribution_paise + s.term_loan_paise,
        ),
    ]

    wc = p.working_capital
    wc_rows = [
        ("Inventory", wc.inventory_paise),
        ("Receivables", wc.receivables_paise),
        ("Less: payables", wc.payables_paise),
        ("Net working-capital requirement", wc.requirement_paise),
        ("Promoter / project WC margin", wc.margin_paise),
        ("Proposed cash-credit limit", wc.cash_credit_paise),
    ]

    capitalized_interest = sum(
        row.capitalized_interest_paise for row in s.schedule
    )
    negative_cash_months = [
        row.month
        for row in snapshot.cash
        if row.month and row.closing_cash_paise < 0
    ]

    finance_assumptions = [
        (
            "Projection: 60 project months; first calendar month "
            f"{a.start_calendar_month}; scale {bps_percent(a.scale_bps)}. "
            "Core utilisation: 70% in year 1, 85% in year 2, "
            "95% in years 3–5; archetype seasonality applied."
        ),
        (
            f"Nominal annual price/mix growth "
            f"{bps_percent(a.yoy_growth_bps)}; fixed-cost growth "
            f"{bps_percent(a.fixed_cost_growth_bps)}. "
            "Growth is not an assertion of increased physical capacity."
        ),
        (
            f"Preliminary expenses {bps_percent(a.preliminary_bps)} and "
            f"contingency {bps_percent(a.contingency_bps)} of base capex; "
            f"WC margin {bps_percent(a.wc_margin_bps)}. "
            "WC uses rated unseasonal sales; seasonal peaks are unverified."
        ),
        (
            f"Machinery depreciation: {bps_percent(a.depreciation_bps)} "
            f"annual written-down value. Cash tax: "
            f"{bps_percent(a.tax_bps)} of positive monthly PBT; "
            "not a determination of statutory tax liability."
        ),
        (
            f"Term rate {bps_percent(data.finance.annual_rate_bps)}; "
            f"CC rate {bps_percent(data.finance.cc_annual_rate_bps)}; "
            f"tenure {data.finance.tenure_months} months including "
            f"{data.finance.moratorium_months} moratorium months; "
            f"step-up {'yes' if data.finance.step_up else 'no'}."
        ),
        (
            "Moratorium interest is capitalised into debt and included "
            "in model P&L interest expense. If step-up is selected, the "
            "first 12 repayment payments are 70% of the ordinary payment; "
            "remaining payments are recalculated."
        ),
        (
            "CC is fully drawn at inception, interest-only and outstanding "
            "through the five-year projection; no automatic CC repayment "
            "or renewal approval is assumed."
        ),
        (
            "DSCR = (EBITDA − cash tax − incremental WC − drawings) / "
            "(term payments + CC interest). The lender's definition may "
            f"differ. Solver threshold: "
            f"{bps_percent(a.minimum_dscr_bps)} coverage; monthly debt "
            "service must not exceed 50% of pre-debt surplus."
        ),
        a.adjustment_basis,
    ]

    risks = list(dict.fromkeys([
        "Demand, throughput and input/service prices may differ materially "
        "from these illustrative assumptions.",
        "Power interruptions, machine downtime and repair costs can reduce "
        "cash generation; supplier warranty and service support are unverified.",
        "Seasonal working-capital peaks and household withdrawals can "
        "create cash deficits. No rescue financing is inserted.",
        "Financing rates, eligibility, CC renewal and any subsidy timing "
        "remain subject to independent lender verification.",
        *data.risk_factors,
    ]))

    return {
        "data": data,
        "f": snapshot,
        "disclaimer": DISCLAIMER,
        "unknowns": unknowns,
        "costs": costs,
        "means": means,
        "wc_rows": wc_rows,
        "machinery": machinery,
        "base_capex": sum(value for _, value in machinery),
        "pnl_table": pnl_table,
        "cash_table": cash_table,
        "capitalized_interest": capitalized_interest,
        "negative_cash_months": negative_cash_months,
        "finance_assumptions": finance_assumptions,
        "risks": risks,
        "status": (
            "MODEL CONSTRAINTS PASSED — NOT LENDER APPROVAL"
            if s.feasible
            else "INFEASIBLE / UNVERIFIED FINANCING SCENARIO"
        ),
        "source_funding": (
            s.own_contribution_paise
            + s.term_loan_paise
            + s.cash_credit_paise
        ),
        "unit_fee": indian_currency(
            data.archetype.unit_economics.revenue_per_unit_paise
        ),
    }