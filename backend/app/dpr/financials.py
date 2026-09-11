from dataclasses import dataclass, replace

from app.fin import core, ps_scheme
from app.fin.solver import (
    BorrowerFunds,
    FinanceOffer,
    StackResult,
    capital_stack_solver,
)

from .models import DprSessionData


class ReconciliationError(ValueError):
    pass


def assert_reconciled(
    project: core.ProjectCost,
    stack: StackResult,
) -> None:
    values = (
        project.project_cost_paise,
        project.total_funding_paise,
        stack.own_contribution_paise,
        stack.term_loan_paise,
        stack.cash_credit_paise,
    )

    if any(type(value) is not int for value in values):
        raise TypeError("Reconciliation requires integer paise")

    means_of_finance = (
        stack.own_contribution_paise + stack.term_loan_paise
    )
    total_sources = means_of_finance + stack.cash_credit_paise

    if means_of_finance != project.project_cost_paise:
        raise ReconciliationError(
            "Own contribution + term loan does not equal project cost"
        )

    if stack.cash_credit_paise != project.working_capital.cash_credit_paise:
        raise ReconciliationError(
            "Financing cash credit does not match working capital"
        )

    if total_sources != project.total_funding_paise:
        raise ReconciliationError(
            "Total initial sources do not equal total funding requirement"
        )

    # Explicit exceptions above remain active under python -O.
    assert means_of_finance == project.project_cost_paise
    assert total_sources == project.total_funding_paise


@dataclass(frozen=True)
class FinancialSnapshot:
    project: core.ProjectCost
    stack: StackResult
    pnl: tuple[core.PnlMonth, ...]
    cash: tuple[core.CashFlowMonth, ...]
    dscr: tuple[core.DscrYear, ...]
    breakeven: core.Breakeven
    surplus: tuple[int, ...]

    # PS-mandated financial structuring outputs (primary path). See
    # module docstring in app.fin.ps_scheme for the mandated formula.
    cost_model: str
    finance_offer: FinanceOffer
    scheme_route: ps_scheme.SchemeRoute | None
    quarterly_schedule: tuple[ps_scheme.QuarterlyInstalment, ...]
    operational_costs: ps_scheme.OperationalCostsBreakdown


def _ps_scheme_terms(
    data: DprSessionData,
) -> tuple[core.ProjectCost, int, int, FinanceOffer, ps_scheme.SchemeRoute]:
    """Primary path: PS-mandated project cost, loan sizing and scheme."""
    a = data.assumptions
    archetype = data.archetype
    margin = data.promoter.available_for_project_paise

    project_cost_paise = ps_scheme.project_cost_from_margin(margin)
    route = ps_scheme.route_scheme(project_cost_paise)

    if not route.in_scope:
        raise ps_scheme.SchemeOutOfScopeError(route.message)

    # Archetype capex/WC still describe the underlying business; only the
    # top-level project-cost and total-funding figures are PS-mandated.
    reference = core.project_cost(
        archetype,
        scale_bps=a.scale_bps,
        preliminary_bps=a.preliminary_bps,
        contingency_bps=a.contingency_bps,
        wc_margin_bps=a.wc_margin_bps,
    )
    project = replace(
        reference,
        project_cost_paise=project_cost_paise,
        total_funding_paise=(
            project_cost_paise + reference.working_capital.cash_credit_paise
        ),
    )

    own = margin
    term = project.project_cost_paise - own

    assert route.scheme is not None  # in_scope implies a scheme
    offer = FinanceOffer(
        id=data.finance.id,
        annual_rate_bps=route.scheme.annual_rate_bps,
        tenure_months=route.scheme.tenure_months,
        moratorium_months=route.scheme.moratorium_months,
        step_up=False,
        cc_annual_rate_bps=data.finance.cc_annual_rate_bps,
        min_own_contribution_bps=0,
        max_term_loan_paise=None,
        eligibility_confirmed=data.finance.eligibility_confirmed,
        pending_backended_subsidy_paise=data.finance.pending_backended_subsidy_paise,
    )

    return project, own, term, offer, route


def _custom_scale_terms(
    data: DprSessionData,
) -> tuple[core.ProjectCost, int, int, FinanceOffer]:
    """Secondary path: the pre-existing archetype-capex model."""
    a = data.assumptions
    archetype = data.archetype

    project = core.project_cost(
        archetype,
        scale_bps=a.scale_bps,
        preliminary_bps=a.preliminary_bps,
        contingency_bps=a.contingency_bps,
        wc_margin_bps=a.wc_margin_bps,
    )

    own = min(
        data.promoter.available_for_project_paise,
        project.project_cost_paise,
    )
    term = project.project_cost_paise - own
    offer = FinanceOffer(**data.finance.model_dump())

    return project, own, term, offer


def calculate_financials(data: DprSessionData) -> FinancialSnapshot:
    a = data.assumptions
    archetype = data.archetype

    scheme_route: ps_scheme.SchemeRoute | None
    if a.cost_model == "custom_scale":
        project, own, term, offer = _custom_scale_terms(data)
        scheme_route = None
    else:
        project, own, term, offer, scheme_route = _ps_scheme_terms(data)

    # The actual schedule is needed before calculating P&L cash tax.
    # Invalid schedule parameters fail explicitly; no fictional schedule.
    schedule = core.repayment_schedule(
        principal_paise=term,
        annual_rate_bps=offer.annual_rate_bps,
        tenure_months=offer.tenure_months,
        moratorium_months=offer.moratorium_months,
        step_up=offer.step_up,
    )

    revenue = core.revenue_projection(
        archetype,
        scale_bps=a.scale_bps,
        years=5,
        yoy_growth_bps=a.yoy_growth_bps,
        fixed_cost_growth_bps=a.fixed_cost_growth_bps,
        start_calendar_month=a.start_calendar_month,
    )

    pnl = core.profit_and_loss(
        revenue,
        schedule,
        machinery_paise=project.machinery_paise,
        cash_credit_paise=project.working_capital.cash_credit_paise,
        cc_annual_rate_bps=offer.cc_annual_rate_bps,
        depreciation_bps=a.depreciation_bps,
        tax_bps=a.tax_bps,
    )

    # PRE-DEBT surplus. Do not subtract term payments or CC interest.
    surplus = [
        row.cash_available_for_debt_service_paise
        - a.additional_wc_paise[index]
        - a.owner_drawings_paise[index]
        for index, row in enumerate(pnl)
    ]

    stack = capital_stack_solver(
        project=project,
        borrower=BorrowerFunds(
            available_for_project_paise=(
                data.promoter.available_for_project_paise
            )
        ),
        offers=[offer],
        monthly_surplus_paise=surplus,
        minimum_dscr_bps=a.minimum_dscr_bps,
    )[0]

    if stack.schedule != tuple(schedule):
        raise ArithmeticError("DPR and solver loan schedules differ")

    assert_reconciled(project, stack)

    cash = core.cash_flow(
        pnl,
        project,
        stack.schedule,
        own_contribution_paise=stack.own_contribution_paise,
        additional_wc_paise=a.additional_wc_paise,
        owner_drawings_paise=a.owner_drawings_paise,
    )

    coverage = core.dscr(
        pnl,
        stack.schedule,
        additional_wc_paise=a.additional_wc_paise,
        owner_drawings_paise=a.owner_drawings_paise,
    )

    first_year_fixed = sum(
        row.fixed_cost_paise for row in pnl if row.year == 1
    )
    operating_be = core.breakeven(
        archetype,
        fixed_annual_paise=first_year_fixed,
    )

    # Required PS outputs, computed uniformly regardless of cost model:
    # the quarterly view of whichever schedule was actually financed, and
    # the archetype's rated operating-cost breakdown.
    quarterly = tuple(ps_scheme.quarterly_schedule(stack.schedule))
    operational_costs = ps_scheme.operational_costs_breakdown(
        archetype, scale_bps=a.scale_bps
    )

    return FinancialSnapshot(
        project=project,
        stack=stack,
        pnl=tuple(pnl),
        cash=tuple(cash),
        dscr=tuple(coverage),
        breakeven=operating_be,
        surplus=tuple(surplus),
        cost_model=a.cost_model,
        finance_offer=offer,
        scheme_route=scheme_route,
        quarterly_schedule=quarterly,
        operational_costs=operational_costs,
    )


def annual_tables(
    snapshot: FinancialSnapshot,
    data: DprSessionData,
) -> tuple[list[tuple], list[tuple]]:
    """Aggregate flows; use first/last observations for cash balances."""

    pnl_fields = [
        ("Revenue", "revenue_paise"),
        ("Variable operating costs", "variable_cost_paise"),
        ("Fixed operating costs", "fixed_cost_paise"),
        ("EBITDA", "ebitda_paise"),
        ("Machinery depreciation", "depreciation_paise"),
        ("EBIT", "ebit_paise"),
        ("Term interest accrued", "term_interest_paise"),
        ("Cash-credit interest", "cc_interest_paise"),
        ("Profit before tax", "profit_before_tax_paise"),
        ("Cash tax", "tax_paise"),
        ("Profit after tax", "profit_after_tax_paise"),
    ]

    pnl_table = [
        (
            label,
            [
                sum(
                    getattr(row, field)
                    for row in snapshot.pnl
                    if row.year == year
                )
                for year in range(1, 6)
            ],
        )
        for label, field in pnl_fields
    ]

    cash_groups = [
        [
            row
            for row in snapshot.cash
            if (year - 1) * 12 < row.month <= year * 12
        ]
        for year in range(1, 6)
    ]

    cash_table = [
        ("Opening cash", [rows[0].opening_cash_paise for rows in cash_groups]),
        (
            "Operating cash after drawings, before debt",
            [
                sum(row.operating_cash_before_debt_paise for row in rows)
                for rows in cash_groups
            ],
        ),
        (
            "Term payments + CC interest",
            [
                sum(row.debt_service_paise for row in rows)
                for rows in cash_groups
            ],
        ),
        (
            "Incremental WC outflow / (release)",
            [
                sum(row.additional_wc_paise for row in rows)
                for rows in cash_groups
            ],
        ),
        (
            "Net cash movement",
            [sum(row.net_cash_paise for row in rows) for rows in cash_groups],
        ),
        ("Closing cash", [rows[-1].closing_cash_paise for rows in cash_groups]),
        (
            "Owner drawings — included above",
            [
                sum(data.assumptions.owner_drawings_paise[start:start + 12])
                for start in range(0, 60, 12)
            ],
        ),
    ]

    return pnl_table, cash_table