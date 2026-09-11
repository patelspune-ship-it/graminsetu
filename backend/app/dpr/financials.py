from dataclasses import dataclass, replace
from typing import Sequence

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

    # Scale actually used for revenue/cost/capex sizing this projection,
    # and a warning when a ps_scheme derivation had to be capped.
    scale_bps_used: int
    scale_warning: str | None

    # Assumption arrays as actually used (length matches the projection
    # horizon, which may exceed or fall short of the raw 60-month input).
    additional_wc_paise: tuple[int, ...]
    owner_drawings_paise: tuple[int, ...]


def _extend_monthly(
    values: Sequence[int],
    length: int,
    pad_with_last: bool,
) -> list[int]:
    """Fit a monthly assumption array to the actual projection horizon.

    Longer than needed: truncated. Shorter than needed (a scheme tenure
    exceeding the raw 60-month input, e.g. the 84-month Term Loan
    Scheme): padded with the last supplied value (pad_with_last=True,
    for assumptions like drawings that plausibly continue), or with
    zero (pad_with_last=False, for assumptions with no known
    continuation, like incremental working capital).
    """
    values = list(values)

    if len(values) >= length:
        return values[:length]

    pad_value = values[-1] if (pad_with_last and values) else 0
    return values + [pad_value] * (length - len(values))


def _ps_scheme_terms(
    data: DprSessionData,
) -> tuple[
    core.ProjectCost,
    int,
    int,
    FinanceOffer,
    ps_scheme.SchemeRoute,
    ps_scheme.ScaleDerivation,
]:
    """Primary path: PS-mandated project cost, loan sizing and scheme."""
    a = data.assumptions
    archetype = data.archetype
    margin = data.promoter.available_for_project_paise

    project_cost_paise = ps_scheme.project_cost_from_margin(margin)
    route = ps_scheme.route_scheme(project_cost_paise)

    if not route.in_scope:
        raise ps_scheme.SchemeOutOfScopeError(route.message)

    # The archetype's rated economics are scaled to match the PS-mandated
    # project cost, so revenue, costs, capex and WC all reflect the
    # actual business size implied by the borrower's margin.
    scale = ps_scheme.derive_scale_bps(archetype, project_cost_paise)

    reference = core.project_cost(
        archetype,
        scale_bps=scale.scale_bps,
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
        # Unlike an illustrative lender offer, scheme eligibility here is
        # a deterministic function of project cost that route_scheme has
        # already applied — there is no separate lender-discretion step
        # left to verify, so the caller's eligibility_confirmed input
        # (meant for the offer-comparison/custom-scale path) is not used.
        eligibility_confirmed=True,
        pending_backended_subsidy_paise=data.finance.pending_backended_subsidy_paise,
    )

    return project, own, term, offer, route, scale


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
    scale_warning: str | None

    if a.cost_model == "custom_scale":
        project, own, term, offer = _custom_scale_terms(data)
        scheme_route = None
        scale_bps_used = a.scale_bps
        scale_warning = None
        # Unchanged from the original fixed horizon.
        years = 5
    else:
        project, own, term, offer, scheme_route, scale = _ps_scheme_terms(data)
        scale_bps_used = scale.scale_bps
        scale_warning = scale.warning
        # The projection horizon matches the routed scheme's tenure
        # exactly, so DSCR and cash flow cover the full loan life.
        years = -(-offer.tenure_months // 12)

    months = years * 12

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
        scale_bps=scale_bps_used,
        years=years,
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

    # additional_wc_paise/owner_drawings_paise are validated as exactly 60
    # monthly entries; fit them to the actual projection horizon, which
    # may be shorter (Micro Finance, 36 months) or longer (Term Loan
    # Scheme, 84 months) than that raw input.
    additional_wc = _extend_monthly(
        a.additional_wc_paise, months, pad_with_last=False
    )
    owner_drawings = _extend_monthly(
        a.owner_drawings_paise, months, pad_with_last=True
    )

    # PRE-DEBT surplus. Do not subtract term payments or CC interest.
    surplus = [
        row.cash_available_for_debt_service_paise
        - additional_wc[index]
        - owner_drawings[index]
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
        additional_wc_paise=additional_wc,
        owner_drawings_paise=owner_drawings,
    )

    coverage = core.dscr(
        pnl,
        stack.schedule,
        additional_wc_paise=additional_wc,
        owner_drawings_paise=owner_drawings,
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
    # the archetype's rated operating-cost breakdown at the same scale
    # used for the P&L above.
    quarterly = tuple(ps_scheme.quarterly_schedule(stack.schedule))
    operational_costs = ps_scheme.operational_costs_breakdown(
        archetype, scale_bps=scale_bps_used
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
        scale_bps_used=scale_bps_used,
        scale_warning=scale_warning,
        additional_wc_paise=tuple(additional_wc),
        owner_drawings_paise=tuple(owner_drawings),
    )


def annual_tables(
    snapshot: FinancialSnapshot,
) -> tuple[list[tuple], list[tuple]]:
    """Aggregate flows; use first/last observations for cash balances.

    The number of years follows the actual projection horizon (which
    matches the routed scheme's tenure under cost_model="ps_scheme"),
    not a fixed 5.
    """
    years = len(snapshot.pnl) // 12

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
                for year in range(1, years + 1)
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
        for year in range(1, years + 1)
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
                sum(snapshot.owner_drawings_paise[start:start + 12])
                for start in range(0, years * 12, 12)
            ],
        ),
    ]

    return pnl_table, cash_table