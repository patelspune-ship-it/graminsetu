"""
PS-mandated financial structuring logic.

This is the PRIMARY financing path. It replaces the bottom-up,
archetype-capex project-cost model (``app.fin.core.project_cost``,
kept available as the secondary "custom scale" option) with an exact
formula prescribed by the problem statement:

    project_cost_paise = available_margin_paise * 10   # margin is 10%
    max_loan_paise     = project_cost_paise * 90 / 100  # 90% loan

The computed project cost then routes to exactly one scheme:

    <= Rs 1,40,000              -> Micro Finance Scheme
    Rs 1,40,000 .. Rs 50,00,000 -> Term Loan Scheme
    > Rs 50,00,000              -> out of scope

Conventions match app.fin.core: integer paise, Fraction arithmetic,
explicit half-up rounding, no floats.
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from app.archetypes.schema import Archetype
from app.fin.core import (
    BPS,
    LoanMonth,
    apply_bps,
    repayment_schedule,
    require_int,
    round_half_up,
)

# Rupees are converted to paise (x100) throughout this module.
MICRO_FINANCE_CEILING_PAISE = 1_40_000 * 100
TERM_LOAN_CEILING_PAISE = 50_00_000 * 100


class SchemeOutOfScopeError(ValueError):
    """Raised when the computed project cost exceeds every scheme ceiling."""


@dataclass(frozen=True)
class Scheme:
    name: str
    annual_rate_bps: int
    tenure_months: int
    moratorium_months: int


MICRO_FINANCE_SCHEME = Scheme(
    name="Micro Finance Scheme",
    annual_rate_bps=650,
    tenure_months=36,
    moratorium_months=3,
)

TERM_LOAN_SCHEME = Scheme(
    name="Term Loan Scheme",
    annual_rate_bps=800,
    tenure_months=84,
    moratorium_months=6,
)


@dataclass(frozen=True)
class SchemeRoute:
    scheme: Scheme | None
    in_scope: bool
    message: str


# An archetype's rated unit economics are not a credible basis once the
# PS-mandated project cost implies a business many multiples larger than
# the archetype's own rated capex. Cap the derived scale here and flag it.
MAX_SCALE_BPS = 20 * BPS


@dataclass(frozen=True)
class ScaleDerivation:
    archetype_base_capex_paise: int
    raw_scale_bps: int
    scale_bps: int
    capped: bool
    warning: str | None


def _format_multiple(bps: int) -> str:
    tenths = round_half_up(Fraction(bps * 10, BPS))
    whole, frac = divmod(tenths, 10)
    return f"{whole}.{frac}x"


def derive_scale_bps(
    archetype: Archetype,
    project_cost_paise: int,
) -> ScaleDerivation:
    """Scale the archetype's rated economics to match the PS-mandated
    project cost: scale = project_cost / archetype_base_capex_total.

    This keeps revenue, variable cost, fixed cost, machinery/WC sizing
    all proportional to the actual project size implied by the
    borrower's margin, instead of always using the archetype's rated
    (1x) economics regardless of project cost.
    """
    require_int("project_cost_paise", project_cost_paise, 0)

    base_capex_paise = sum(archetype.capex_paise.values())
    if base_capex_paise <= 0:
        raise ValueError("Archetype base capex must be positive")

    raw_scale_bps = max(
        1,
        round_half_up(Fraction(project_cost_paise * BPS, base_capex_paise)),
    )
    capped = raw_scale_bps > MAX_SCALE_BPS
    scale_bps = min(raw_scale_bps, MAX_SCALE_BPS)

    warning = (
        f"Derived scale {_format_multiple(raw_scale_bps)} exceeds the "
        f"{_format_multiple(MAX_SCALE_BPS)} cap on this archetype's rated "
        "unit economics; capped at that multiple. Revenue and cost "
        "figures beyond this point are not a credible basis for this "
        "project size."
        if capped
        else None
    )

    return ScaleDerivation(
        archetype_base_capex_paise=base_capex_paise,
        raw_scale_bps=raw_scale_bps,
        scale_bps=scale_bps,
        capped=capped,
        warning=warning,
    )


def project_cost_from_margin(available_margin_paise: int) -> int:
    """project_cost_paise = available_margin_paise * 10 (margin is 10%)."""
    require_int("available_margin_paise", available_margin_paise, 0)
    return available_margin_paise * 10


def max_loan_from_project_cost(project_cost_paise: int) -> int:
    """max_loan_paise = project_cost_paise * 90 / 100 (90% loan)."""
    require_int("project_cost_paise", project_cost_paise, 0)
    return round_half_up(Fraction(project_cost_paise * 90, 100))


def route_scheme(project_cost_paise: int) -> SchemeRoute:
    require_int("project_cost_paise", project_cost_paise, 0)

    if project_cost_paise <= MICRO_FINANCE_CEILING_PAISE:
        return SchemeRoute(
            scheme=MICRO_FINANCE_SCHEME,
            in_scope=True,
            message=(
                f"Project cost {project_cost_paise} paise is within the "
                f"Rs 1,40,000 ceiling: routed to {MICRO_FINANCE_SCHEME.name}."
            ),
        )

    if project_cost_paise <= TERM_LOAN_CEILING_PAISE:
        return SchemeRoute(
            scheme=TERM_LOAN_SCHEME,
            in_scope=True,
            message=(
                f"Project cost {project_cost_paise} paise is within the "
                f"Rs 50,00,000 ceiling: routed to {TERM_LOAN_SCHEME.name}."
            ),
        )

    return SchemeRoute(
        scheme=None,
        in_scope=False,
        message=(
            f"Project cost {project_cost_paise} paise exceeds the "
            "Rs 50,00,000 ceiling for these schemes. Out of scope: no "
            "Micro Finance or Term Loan Scheme applies to this margin."
        ),
    )


@dataclass(frozen=True)
class QuarterlyInstalment:
    quarter: int
    opening_paise: int
    interest_accrued_paise: int
    interest_paid_paise: int
    capitalized_interest_paise: int
    principal_paid_paise: int
    payment_paise: int
    closing_paise: int


def quarterly_schedule(
    loan_rows: Sequence[LoanMonth],
) -> list[QuarterlyInstalment]:
    """Aggregate a monthly repayment schedule into quarters of 3 months.

    A trailing partial quarter (schedule length not a multiple of 3) is
    aggregated as-is rather than dropped or padded.
    """
    months = list(loan_rows)

    for index, row in enumerate(months, start=1):
        if row.month != index:
            raise ValueError("Loan schedule months must be contiguous from 1")

    quarters: list[QuarterlyInstalment] = []

    for start in range(0, len(months), 3):
        chunk = months[start:start + 3]

        quarters.append(
            QuarterlyInstalment(
                quarter=start // 3 + 1,
                opening_paise=chunk[0].opening_paise,
                interest_accrued_paise=sum(
                    row.interest_accrued_paise for row in chunk
                ),
                interest_paid_paise=sum(
                    row.interest_paid_paise for row in chunk
                ),
                capitalized_interest_paise=sum(
                    row.capitalized_interest_paise for row in chunk
                ),
                principal_paid_paise=sum(
                    row.principal_paid_paise for row in chunk
                ),
                payment_paise=sum(row.payment_paise for row in chunk),
                closing_paise=chunk[-1].closing_paise,
            )
        )

    return quarters


@dataclass(frozen=True)
class OperationalCostsBreakdown:
    monthly_revenue_paise: int
    monthly_variable_cost_paise: int
    monthly_fixed_cost_paise: int
    monthly_total_operating_cost_paise: int
    annual_total_operating_cost_paise: int


def operational_costs_breakdown(
    archetype: Archetype,
    scale_bps: int = BPS,
) -> OperationalCostsBreakdown:
    """Rated monthly operating-cost breakdown, before capacity ramp-up.

    Uses the same rated-sales basis as app.fin.core.working_capital, so
    the two outputs are computed on a consistent footing.
    """
    require_int("scale_bps", scale_bps, 1)

    economics = archetype.unit_economics

    monthly_revenue = round_half_up(
        Fraction(
            economics.revenue_per_unit_paise
            * economics.units_per_month
            * scale_bps,
            BPS,
        )
    )
    monthly_variable = apply_bps(monthly_revenue, economics.variable_cost_bps)
    monthly_fixed = round_half_up(
        Fraction(economics.fixed_monthly_paise * scale_bps, BPS)
    )
    monthly_total = monthly_variable + monthly_fixed

    return OperationalCostsBreakdown(
        monthly_revenue_paise=monthly_revenue,
        monthly_variable_cost_paise=monthly_variable,
        monthly_fixed_cost_paise=monthly_fixed,
        monthly_total_operating_cost_paise=monthly_total,
        annual_total_operating_cost_paise=monthly_total * 12,
    )


@dataclass(frozen=True)
class PSFinancingPlan:
    margin_paise: int
    project_cost_paise: int
    max_loan_paise: int
    loan_paise: int
    route: SchemeRoute
    schedule: tuple[LoanMonth, ...]
    quarterly_schedule: tuple[QuarterlyInstalment, ...]
    operational_costs: OperationalCostsBreakdown


def build_ps_financing_plan(
    archetype: Archetype,
    available_margin_paise: int,
    scale_bps: int = BPS,
    loan_paise: int | None = None,
) -> PSFinancingPlan:
    """Standalone, self-contained PS-mandated financing plan.

    Raises SchemeOutOfScopeError if the computed project cost exceeds
    every scheme ceiling. loan_paise defaults to the full eligible
    amount (max_loan_paise); pass an explicit value to model a
    borrower drawing less than their eligibility.
    """
    project_cost_paise = project_cost_from_margin(available_margin_paise)
    max_loan_paise = max_loan_from_project_cost(project_cost_paise)
    route = route_scheme(project_cost_paise)

    if not route.in_scope:
        raise SchemeOutOfScopeError(route.message)

    chosen_loan = max_loan_paise if loan_paise is None else loan_paise
    require_int("loan_paise", chosen_loan, 0, max_loan_paise)

    assert route.scheme is not None  # in_scope implies a scheme

    schedule = tuple(
        repayment_schedule(
            principal_paise=chosen_loan,
            annual_rate_bps=route.scheme.annual_rate_bps,
            tenure_months=route.scheme.tenure_months,
            moratorium_months=route.scheme.moratorium_months,
        )
    )

    return PSFinancingPlan(
        margin_paise=available_margin_paise,
        project_cost_paise=project_cost_paise,
        max_loan_paise=max_loan_paise,
        loan_paise=chosen_loan,
        route=route,
        schedule=schedule,
        quarterly_schedule=tuple(quarterly_schedule(schedule)),
        operational_costs=operational_costs_breakdown(
            archetype, scale_bps=scale_bps
        ),
    )
