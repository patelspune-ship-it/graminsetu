"""
Deterministic MVP financial model.

Conventions
-----------
* All monetary inputs/outputs are integer paise.
* Rates and coefficients use integer basis points.
* Intermediate calculations use Fraction, never float.
* Half-up rounding is explicit.
* Monthly interest = opening balance * annual_rate_bps / 120000.
* Tenure includes moratorium months.
* Moratorium interest capitalizes.
* Step-up means 12 repayment months at 70% of ordinary EMI,
  followed by a recalculated level payment within original tenure.
* Working capital uses a 30-day month.
* Project cost = fixed investment + borrower WC margin.
* Total funding requirement = fixed investment + total WC.
* Cash credit is assumed fully drawn and interest-only throughout
  the projection. It remains an outstanding liability at horizon end.
* Tax is a simplified positive-PBT percentage, default zero.
  No loss carry-forward or entity-specific taxation is implemented.
* Depreciation defaults to 15% WDV on machinery only.
  This is a modelling assumption, not a universal tax rule.
"""

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from app.archetypes.schema import Archetype

BPS = 10_000


def require_int(
    name: str,
    value: int,
    minimum: int = 0,
    maximum: int | None = None,
) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")

    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")

    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")


def round_half_up(value: Fraction | int) -> int:
    if type(value) is int:
        return value

    if not isinstance(value, Fraction):
        raise TypeError("round_half_up accepts only int or Fraction")

    sign = -1 if value < 0 else 1
    numerator = abs(value.numerator)
    denominator = value.denominator

    rounded = (2 * numerator + denominator) // (2 * denominator)
    return sign * rounded


def ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def apply_bps(amount_paise: int, bps: int) -> int:
    require_int("amount_paise", amount_paise)
    require_int("bps", bps)
    return round_half_up(Fraction(amount_paise * bps, BPS))


def _allocate(total: int, periods: int) -> list[int]:
    """Allocate an integer amount exactly across periods."""
    require_int("total", total)
    require_int("periods", periods, 1)

    quotient, remainder = divmod(total, periods)

    return [
        quotient + (1 if index < remainder else 0)
        for index in range(periods)
    ]


@dataclass(frozen=True)
class WorkingCapital:
    inventory_paise: int
    receivables_paise: int
    payables_paise: int

    requirement_paise: int
    margin_paise: int
    cash_credit_paise: int


@dataclass(frozen=True)
class ProjectCost:
    machinery_paise: int
    civil_paise: int
    installation_paise: int

    preliminary_paise: int
    contingency_paise: int

    fixed_investment_paise: int
    working_capital: WorkingCapital

    # Fixed investment plus borrower-funded WC margin.
    project_cost_paise: int

    # Fixed investment plus the entire working-capital requirement.
    total_funding_paise: int


@dataclass(frozen=True)
class RevenueMonth:
    month: int
    year: int
    revenue_paise: int
    variable_cost_paise: int
    fixed_cost_paise: int
    capacity_bps: int
    seasonality_bps: int


@dataclass(frozen=True)
class LoanMonth:
    month: int
    phase: str

    opening_paise: int
    interest_accrued_paise: int
    interest_paid_paise: int
    capitalized_interest_paise: int

    principal_paid_paise: int
    payment_paise: int
    closing_paise: int


@dataclass(frozen=True)
class PnlMonth:
    month: int
    year: int

    revenue_paise: int
    variable_cost_paise: int
    fixed_cost_paise: int

    ebitda_paise: int
    depreciation_paise: int
    ebit_paise: int

    term_interest_paise: int
    cc_interest_paise: int

    profit_before_tax_paise: int
    tax_paise: int
    profit_after_tax_paise: int

    # Before debt service, before changes in WC, before owner drawings.
    cash_available_for_debt_service_paise: int


@dataclass(frozen=True)
class CashFlowMonth:
    month: int
    opening_cash_paise: int
    financing_inflow_paise: int
    investment_outflow_paise: int

    operating_cash_before_debt_paise: int
    debt_service_paise: int
    additional_wc_paise: int

    net_cash_paise: int
    closing_cash_paise: int


@dataclass(frozen=True)
class Breakeven:
    contribution_margin_bps: int
    revenue_paise: int | None
    units: int | None
    reason: str | None


@dataclass(frozen=True)
class DscrYear:
    year: int
    cash_available_paise: int
    debt_service_paise: int
    ratio: Fraction | None
    meets_1_25: bool | None


def working_capital(
    archetype: Archetype,
    scale_bps: int = BPS,
    margin_bps: int = 2_500,
) -> WorkingCapital:
    require_int("scale_bps", scale_bps, 1)
    require_int("margin_bps", margin_bps, 0, BPS)

    economics = archetype.unit_economics

    # Rated, unseasonal monthly turnover.
    # Seasonal peak WC must be validated separately.
    sales = round_half_up(
        Fraction(
            economics.revenue_per_unit_paise
            * economics.units_per_month
            * scale_bps,
            BPS,
        )
    )

    variable_cost = apply_bps(sales, economics.variable_cost_bps)
    inventory_cost = apply_bps(
        variable_cost,
        economics.inventory_eligible_cost_bps,
    )

    inventory = round_half_up(
        Fraction(inventory_cost * economics.inventory_days, 30)
    )
    receivables = round_half_up(
        Fraction(sales * economics.receivable_days, 30)
    )
    payables = round_half_up(
        Fraction(inventory_cost * economics.payable_days, 30)
    )

    requirement = max(inventory + receivables - payables, 0)

    # Round margin up, so rounding never underfunds the margin.
    margin = ceil_fraction(Fraction(requirement * margin_bps, BPS))
    cash_credit = requirement - margin

    return WorkingCapital(
        inventory_paise=inventory,
        receivables_paise=receivables,
        payables_paise=payables,
        requirement_paise=requirement,
        margin_paise=margin,
        cash_credit_paise=cash_credit,
    )


def project_cost(
    archetype: Archetype,
    scale_bps: int = BPS,
    preliminary_bps: int = 300,
    contingency_bps: int = 500,
    wc_margin_bps: int = 2_500,
) -> ProjectCost:
    require_int("scale_bps", scale_bps, 1)
    require_int("preliminary_bps", preliminary_bps, 0, BPS)
    require_int("contingency_bps", contingency_bps, 0, BPS)

    capex = {
        name: round_half_up(Fraction(amount * scale_bps, BPS))
        for name, amount in archetype.capex_paise.items()
    }

    base_capex = sum(capex.values())

    # Both percentages use base capex; not compounded.
    preliminary = apply_bps(base_capex, preliminary_bps)
    contingency = apply_bps(base_capex, contingency_bps)

    fixed = base_capex + preliminary + contingency

    wc = working_capital(
        archetype,
        scale_bps=scale_bps,
        margin_bps=wc_margin_bps,
    )

    return ProjectCost(
        machinery_paise=capex["machinery"],
        civil_paise=capex["civil"],
        installation_paise=capex["installation"],
        preliminary_paise=preliminary,
        contingency_paise=contingency,
        fixed_investment_paise=fixed,
        working_capital=wc,
        project_cost_paise=fixed + wc.margin_paise,
        total_funding_paise=fixed + wc.requirement_paise,
    )


def revenue_projection(
    archetype: Archetype,
    scale_bps: int = BPS,
    years: int = 5,
    yoy_growth_bps: int = 800,
    fixed_cost_growth_bps: int = 500,
    start_calendar_month: int = 1,
) -> list[RevenueMonth]:
    require_int("scale_bps", scale_bps, 1)
    require_int("years", years, 1, 30)
    require_int("yoy_growth_bps", yoy_growth_bps, 0, BPS)
    require_int("fixed_cost_growth_bps", fixed_cost_growth_bps, 0, BPS)
    require_int("start_calendar_month", start_calendar_month, 1, 12)

    economics = archetype.unit_economics
    rows: list[RevenueMonth] = []

    # Growth is a nominal price/mix assumption, not unlimited
    # physical production growth on fixed machinery.
    for month in range(1, years * 12 + 1):
        year = (month - 1) // 12 + 1
        capacity = 7_000 if year == 1 else 8_500 if year == 2 else 9_500

        calendar_index = (start_calendar_month + month - 2) % 12
        seasonality = archetype.seasonality_bps[calendar_index]

        price_factor = Fraction(BPS + yoy_growth_bps, BPS) ** (year - 1)
        fixed_factor = (
            Fraction(BPS + fixed_cost_growth_bps, BPS) ** (year - 1)
        )

        revenue = round_half_up(
            Fraction(
                economics.revenue_per_unit_paise
                * economics.units_per_month
                * scale_bps
                * capacity
                * seasonality,
                BPS ** 3,
            )
            * price_factor
        )

        fixed_cost = round_half_up(
            Fraction(economics.fixed_monthly_paise * scale_bps, BPS)
            * fixed_factor
        )

        rows.append(
            RevenueMonth(
                month=month,
                year=year,
                revenue_paise=revenue,
                variable_cost_paise=apply_bps(
                    revenue, economics.variable_cost_bps
                ),
                fixed_cost_paise=fixed_cost,
                capacity_bps=capacity,
                seasonality_bps=seasonality,
            )
        )

    return rows


def _monthly_interest(principal: int, annual_rate_bps: int) -> int:
    return round_half_up(Fraction(principal * annual_rate_bps, 120_000))


def _level_payment(
    principal: int,
    annual_rate_bps: int,
    months: int,
) -> int:
    """
    Find the minimum integer monthly payment that amortizes the loan.

    Integer binary search respects monthly paise rounding.
    The final instalment is capped at the actual remaining amount.
    """
    if principal == 0:
        return 0

    require_int("months", months, 1)

    def clears(payment: int) -> bool:
        balance = principal

        for _ in range(months):
            if balance == 0:
                return True

            interest = _monthly_interest(balance, annual_rate_bps)
            balance = max(0, balance + interest - payment)

        return balance == 0

    low = 0
    high = principal + _monthly_interest(principal, annual_rate_bps)

    while low < high:
        middle = (low + high) // 2

        if clears(middle):
            high = middle
        else:
            low = middle + 1

    return low


def repayment_schedule(
    principal_paise: int,
    annual_rate_bps: int,
    tenure_months: int,
    moratorium_months: int = 0,
    step_up: bool = False,
) -> list[LoanMonth]:
    require_int("principal_paise", principal_paise)
    require_int("annual_rate_bps", annual_rate_bps, 0, BPS)
    require_int("tenure_months", tenure_months, 1, 360)
    require_int(
        "moratorium_months",
        moratorium_months,
        0,
        tenure_months - 1,
    )

    if type(step_up) is not bool:
        raise TypeError("step_up must be bool")

    repayment_months = tenure_months - moratorium_months

    if principal_paise and step_up and repayment_months <= 12:
        raise ValueError(
            "Step-up requires more than 12 repayment months; "
            "tenure will not be extended automatically"
        )

    rows: list[LoanMonth] = []
    balance = principal_paise

    for month in range(1, moratorium_months + 1):
        interest = _monthly_interest(balance, annual_rate_bps)

        rows.append(
            LoanMonth(
                month=month,
                phase="moratorium",
                opening_paise=balance,
                interest_accrued_paise=interest,
                interest_paid_paise=0,
                capitalized_interest_paise=interest,
                principal_paid_paise=0,
                payment_paise=0,
                closing_paise=balance + interest,
            )
        )

        balance += interest

    ordinary_payment = _level_payment(
        balance, annual_rate_bps, repayment_months
    )
    reduced_payment = apply_bps(ordinary_payment, 7_000)
    later_payment = ordinary_payment

    for repayment_index in range(1, repayment_months + 1):
        if step_up and repayment_index == 13:
            later_payment = _level_payment(
                balance,
                annual_rate_bps,
                repayment_months - 12,
            )

        is_reduced = step_up and repayment_index <= 12
        target = reduced_payment if is_reduced else later_payment

        interest = _monthly_interest(balance, annual_rate_bps)
        payment = min(target, balance + interest)

        if payment < interest:
            raise ValueError(
                "Step-up payment does not cover monthly interest. "
                "Negative amortization outside moratorium is not allowed"
            )

        principal_paid = payment - interest
        closing = balance - principal_paid

        rows.append(
            LoanMonth(
                month=moratorium_months + repayment_index,
                phase="step_up_initial" if is_reduced else "repayment",
                opening_paise=balance,
                interest_accrued_paise=interest,
                interest_paid_paise=interest,
                capitalized_interest_paise=0,
                principal_paid_paise=principal_paid,
                payment_paise=payment,
                closing_paise=closing,
            )
        )

        balance = closing

    if balance != 0:
        raise ArithmeticError("Repayment schedule failed to amortize")

    return rows


def _loan_map(loan_rows: Sequence[LoanMonth]) -> dict[int, LoanMonth]:
    result = {row.month: row for row in loan_rows}

    if len(result) != len(loan_rows):
        raise ValueError("Duplicate months in loan schedule")

    if sorted(result) != list(range(1, len(loan_rows) + 1)):
        raise ValueError("Loan schedule months must be contiguous from 1")

    return result


def profit_and_loss(
    revenue_rows: Sequence[RevenueMonth],
    loan_rows: Sequence[LoanMonth],
    machinery_paise: int,
    cash_credit_paise: int = 0,
    cc_annual_rate_bps: int = 0,
    depreciation_bps: int = 1_500,
    tax_bps: int = 0,
) -> list[PnlMonth]:
    require_int("machinery_paise", machinery_paise)
    require_int("cash_credit_paise", cash_credit_paise)
    require_int("cc_annual_rate_bps", cc_annual_rate_bps, 0, BPS)
    require_int("depreciation_bps", depreciation_bps, 0, BPS)
    require_int("tax_bps", tax_bps, 0, BPS)

    if len(revenue_rows) == 0 or len(revenue_rows) % 12:
        raise ValueError("Revenue projection must contain complete years")

    for expected_month, row in enumerate(revenue_rows, start=1):
        if row.month != expected_month:
            raise ValueError("Revenue months must be contiguous from 1")

        if row.year != (row.month - 1) // 12 + 1:
            raise ValueError("Revenue year does not match project month")

    loans = _loan_map(loan_rows)
    cc_interest = _monthly_interest(cash_credit_paise, cc_annual_rate_bps)

    depreciation: list[int] = []
    written_down_value = machinery_paise

    for _ in range(len(revenue_rows) // 12):
        annual = apply_bps(written_down_value, depreciation_bps)
        annual = min(annual, written_down_value)

        depreciation.extend(_allocate(annual, 12))
        written_down_value -= annual

    output: list[PnlMonth] = []

    for revenue, monthly_depreciation in zip(revenue_rows, depreciation):
        loan = loans.get(revenue.month)
        term_interest = loan.interest_accrued_paise if loan else 0

        ebitda = (
            revenue.revenue_paise
            - revenue.variable_cost_paise
            - revenue.fixed_cost_paise
        )
        ebit = ebitda - monthly_depreciation
        pbt = ebit - term_interest - cc_interest
        tax = apply_bps(max(pbt, 0), tax_bps)
        pat = pbt - tax

        output.append(
            PnlMonth(
                month=revenue.month,
                year=revenue.year,
                revenue_paise=revenue.revenue_paise,
                variable_cost_paise=revenue.variable_cost_paise,
                fixed_cost_paise=revenue.fixed_cost_paise,
                ebitda_paise=ebitda,
                depreciation_paise=monthly_depreciation,
                ebit_paise=ebit,
                term_interest_paise=term_interest,
                cc_interest_paise=cc_interest,
                profit_before_tax_paise=pbt,
                tax_paise=tax,
                profit_after_tax_paise=pat,
                cash_available_for_debt_service_paise=ebitda - tax,
            )
        )

    return output


def cash_flow(
    pnl_rows: Sequence[PnlMonth],
    project: ProjectCost,
    loan_rows: Sequence[LoanMonth],
    own_contribution_paise: int,
    additional_wc_paise: Sequence[int] | None = None,
    owner_drawings_paise: Sequence[int] | None = None,
) -> list[CashFlowMonth]:
    """
    Month 0 contains initial sources and uses.

    Positive additional_wc_paise means a cash outflow.
    Negative additional_wc_paise means release of working capital.
    These are operating WC changes, not additional CC borrowing.

    No automatic rescue financing is inserted for negative cash balances.
    """
    require_int("own_contribution_paise", own_contribution_paise)

    loans = _loan_map(loan_rows)
    term_principal = loan_rows[0].opening_paise if loan_rows else 0

    if own_contribution_paise + term_principal != project.project_cost_paise:
        raise ValueError(
            "Own contribution + initial term loan must equal "
            "project cost exactly"
        )

    months = len(pnl_rows)

    wc_changes = (
        list(additional_wc_paise)
        if additional_wc_paise is not None
        else [0] * months
    )
    drawings = (
        list(owner_drawings_paise)
        if owner_drawings_paise is not None
        else [0] * months
    )

    if len(wc_changes) != months or len(drawings) != months:
        raise ValueError("WC changes and drawings must match P&L horizon")

    for amount in wc_changes:
        if type(amount) is not int:
            raise TypeError("WC changes must be integer paise")

    for amount in drawings:
        require_int("owner_drawings_paise", amount)

    funding = (
        own_contribution_paise
        + term_principal
        + project.working_capital.cash_credit_paise
    )

    if funding != project.total_funding_paise:
        raise ArithmeticError("Initial sources and uses do not reconcile")

    output = [
        CashFlowMonth(
            month=0,
            opening_cash_paise=0,
            financing_inflow_paise=funding,
            investment_outflow_paise=project.total_funding_paise,
            operating_cash_before_debt_paise=0,
            debt_service_paise=0,
            additional_wc_paise=0,
            net_cash_paise=0,
            closing_cash_paise=0,
        )
    ]

    cash = 0

    for index, pnl in enumerate(pnl_rows):
        if pnl.month != index + 1:
            raise ValueError("P&L months must be contiguous from 1")

        loan = loans.get(pnl.month)
        term_payment = loan.payment_paise if loan else 0

        operating_cash = (
            pnl.cash_available_for_debt_service_paise - drawings[index]
        )
        debt_service = term_payment + pnl.cc_interest_paise

        net = operating_cash - debt_service - wc_changes[index]

        output.append(
            CashFlowMonth(
                month=pnl.month,
                opening_cash_paise=cash,
                financing_inflow_paise=0,
                investment_outflow_paise=0,
                operating_cash_before_debt_paise=operating_cash,
                debt_service_paise=debt_service,
                additional_wc_paise=wc_changes[index],
                net_cash_paise=net,
                closing_cash_paise=cash + net,
            )
        )

        cash += net

    return output


def breakeven(
    archetype: Archetype,
    fixed_annual_paise: int,
) -> Breakeven:
    """
    Caller chooses the fixed-cost definition.

    Cash operating break-even:
        fixed operating expenses.

    Accounting break-even:
        fixed operating expenses + depreciation.

    Financing-inclusive break-even:
        explicitly add interest to fixed_annual_paise.
    """
    require_int("fixed_annual_paise", fixed_annual_paise)

    economics = archetype.unit_economics
    contribution_bps = BPS - economics.variable_cost_bps

    if contribution_bps <= 0:
        return Breakeven(
            contribution_margin_bps=contribution_bps,
            revenue_paise=None,
            units=None,
            reason="Non-positive contribution margin",
        )

    revenue = ceil_fraction(
        Fraction(fixed_annual_paise * BPS, contribution_bps)
    )
    units = ceil_fraction(
        Fraction(revenue, economics.revenue_per_unit_paise)
    )

    return Breakeven(
        contribution_margin_bps=contribution_bps,
        revenue_paise=revenue,
        units=units,
        reason=None,
    )


def dscr(
    pnl_rows: Sequence[PnlMonth],
    loan_rows: Sequence[LoanMonth],
    additional_wc_paise: Sequence[int] | None = None,
    owner_drawings_paise: Sequence[int] | None = None,
) -> list[DscrYear]:
    """
    Cash-based DSCR used by this model:

        CFADS / (term principal + cash term interest + CC interest)

    CFADS = EBITDA - tax - incremental WC - owner drawings.

    This is deliberately explicit. A lender's prescribed DSCR
    definition may differ.

    No-debt years return ratio=None, not infinity.
    """
    loans = _loan_map(loan_rows)
    months = len(pnl_rows)

    wc = list(additional_wc_paise) if additional_wc_paise is not None else [0] * months
    drawings = list(owner_drawings_paise) if owner_drawings_paise is not None else [0] * months

    if len(wc) != months or len(drawings) != months:
        raise ValueError("Adjustment arrays must match P&L horizon")

    totals: dict[int, list[int]] = defaultdict(lambda: [0, 0])

    for index, pnl in enumerate(pnl_rows):
        if type(wc[index]) is not int:
            raise TypeError("WC changes must be integer paise")

        require_int("owner_drawings_paise", drawings[index])

        loan = loans.get(pnl.month)

        numerator = (
            pnl.cash_available_for_debt_service_paise
            - wc[index]
            - drawings[index]
        )
        denominator = (
            (loan.payment_paise if loan else 0)
            + pnl.cc_interest_paise
        )

        totals[pnl.year][0] += numerator
        totals[pnl.year][1] += denominator

    return [
        DscrYear(
            year=year,
            cash_available_paise=numerator,
            debt_service_paise=denominator,
            ratio=Fraction(numerator, denominator) if denominator else None,
            meets_1_25=(
                numerator * 4 >= denominator * 5
                if denominator
                else None
            ),
        )
        for year, (numerator, denominator) in sorted(totals.items())
    ]