from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from app.fin.core import (
    BPS,
    LoanMonth,
    ProjectCost,
    ceil_fraction,
    repayment_schedule,
    require_int,
    round_half_up,
)


@dataclass(frozen=True)
class BorrowerFunds:
    # Already net of household emergency reserves.
    available_for_project_paise: int

    def __post_init__(self):
        require_int(
            "available_for_project_paise",
            self.available_for_project_paise,
        )


@dataclass(frozen=True)
class FinanceOffer:
    id: str
    annual_rate_bps: int
    tenure_months: int

    moratorium_months: int = 0
    step_up: bool = False

    cc_annual_rate_bps: int = 1_200
    min_own_contribution_bps: int = 0
    max_term_loan_paise: int | None = None

    # None means scheme/lender eligibility has not been established.
    eligibility_confirmed: bool | None = True

    # Informational only. NOT subtracted from initial borrowing.
    pending_backended_subsidy_paise: int = 0

    def __post_init__(self):
        if not self.id:
            raise ValueError("Offer id is required")

        require_int("annual_rate_bps", self.annual_rate_bps, 0, BPS)
        require_int("tenure_months", self.tenure_months, 1, 360)
        require_int(
            "moratorium_months",
            self.moratorium_months,
            0,
            self.tenure_months - 1,
        )
        require_int("cc_annual_rate_bps", self.cc_annual_rate_bps, 0, BPS)
        require_int(
            "min_own_contribution_bps",
            self.min_own_contribution_bps,
            0,
            BPS,
        )
        require_int(
            "pending_backended_subsidy_paise",
            self.pending_backended_subsidy_paise,
        )

        if type(self.step_up) is not bool:
            raise TypeError("step_up must be bool")

        if (
            self.eligibility_confirmed is not None
            and type(self.eligibility_confirmed) is not bool
        ):
            raise TypeError("eligibility_confirmed must be bool or None")

        if self.max_term_loan_paise is not None:
            require_int("max_term_loan_paise", self.max_term_loan_paise)


@dataclass(frozen=True)
class StackResult:
    offer_id: str
    feasible: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    own_contribution_paise: int
    term_loan_paise: int
    cash_credit_paise: int

    pending_backended_subsidy_paise: int

    # Explicitly zero until an actual subsidy-adjustment model is used.
    subsidy_applied_upfront_paise: int

    schedule: tuple[LoanMonth, ...]

    term_interest_total_paise: int
    cc_interest_over_offer_horizon_paise: int
    total_interest_over_offer_horizon_paise: int

    max_monthly_debt_service_paise: int

    # Remaining CC principal is not silently assumed to disappear.
    cc_outstanding_at_horizon_paise: int


def aligned_moratorium_months(
    seasonality_bps: Sequence[int],
    start_calendar_month: int = 1,
    cap_months: int = 6,
) -> int:
    """
    Months before the first above-average seasonal month.

    This is a scenario-generation heuristic, NOT proof that a lender
    offers a moratorium or that the business has no cash deficit.
    """
    if len(seasonality_bps) != 12:
        raise ValueError("Expected 12 seasonality values")

    for value in seasonality_bps:
        require_int("seasonality value", value)

    require_int("start_calendar_month", start_calendar_month, 1, 12)
    require_int("cap_months", cap_months, 0, 6)

    for offset in range(12):
        index = (start_calendar_month - 1 + offset) % 12

        if seasonality_bps[index] > BPS:
            return min(offset, cap_months)

    return 0


def capital_stack_solver(
    project: ProjectCost,
    borrower: BorrowerFunds,
    offers: Sequence[FinanceOffer],
    monthly_surplus_paise: Sequence[int],
    minimum_dscr_bps: int = 12_500,
) -> list[StackResult]:
    """
    monthly_surplus_paise must be PRE-DEBT cash available after:
        operating expenses,
        applicable cash tax,
        incremental WC,
        essential owner drawings.

    It must NOT already subtract term payments or CC interest.

    HARD RULE, every month:
        term payment + CC interest <= 50% of monthly surplus.

    This is stricter than checking term EMI alone.

    The surplus horizon must cover each offer's full tenure.
    No automatic tenure extension, grant insertion or balloon payment.

    Results preserve input order. Compare feasible offers over identical
    horizons before ranking their interest totals.
    """
    require_int("minimum_dscr_bps", minimum_dscr_bps, 1)

    for surplus in monthly_surplus_paise:
        if type(surplus) is not int:
            raise TypeError("monthly_surplus_paise must contain integers")

    own = min(
        borrower.available_for_project_paise,
        project.project_cost_paise,
    )
    term = project.project_cost_paise - own
    cc = project.working_capital.cash_credit_paise

    results: list[StackResult] = []

    for offer in offers:
        reasons: list[str] = []
        warnings = [
            "Conditional projection, not a lender approval.",
            "CC is modelled as interest-only and remains outstanding.",
            "Interest comparisons require a common comparison horizon.",
        ]

        if offer.eligibility_confirmed is None:
            reasons.append("Scheme/lender eligibility has not been verified")
        elif offer.eligibility_confirmed is False:
            reasons.append("Applicant is not eligible for this offer")

        required_own = ceil_fraction(
            Fraction(
                project.project_cost_paise
                * offer.min_own_contribution_bps,
                BPS,
            )
        )

        if own < required_own:
            reasons.append(
                f"Own contribution shortfall: "
                f"{required_own - own} paise"
            )

        if (
            offer.max_term_loan_paise is not None
            and term > offer.max_term_loan_paise
        ):
            reasons.append(
                f"Required term loan exceeds offer limit by "
                f"{term - offer.max_term_loan_paise} paise"
            )

        if len(monthly_surplus_paise) < offer.tenure_months:
            reasons.append(
                f"Projection covers {len(monthly_surplus_paise)} months; "
                f"offer requires {offer.tenure_months}. "
                "Generate a longer projection; tenure was not changed"
            )

        if offer.pending_backended_subsidy_paise:
            warnings.append(
                "Pending back-ended subsidy is excluded from upfront "
                "funding and repayment reduction until adjustment "
                "timing and conditions are verified."
            )

        try:
            schedule = repayment_schedule(
                principal_paise=term,
                annual_rate_bps=offer.annual_rate_bps,
                tenure_months=offer.tenure_months,
                moratorium_months=offer.moratorium_months,
                step_up=offer.step_up,
            )
        except (TypeError, ValueError) as exc:
            schedule = []
            reasons.append(str(exc))

        cc_interest = round_half_up(
            Fraction(cc * offer.cc_annual_rate_bps, 120_000)
        )

        affordability_failures: list[int] = []
        negative_surplus_months: list[int] = []

        for row in schedule:
            if row.month > len(monthly_surplus_paise):
                break

            surplus = monthly_surplus_paise[row.month - 1]
            debt_service = row.payment_paise + cc_interest

            if surplus < 0:
                negative_surplus_months.append(row.month)

            # Integer comparison: avoids percentage rounding ambiguity.
            if debt_service * 2 > surplus:
                affordability_failures.append(row.month)

        if negative_surplus_months:
            reasons.append(
                "Negative pre-debt cash surplus in months: "
                + ", ".join(map(str, negative_surplus_months))
            )

        if affordability_failures:
            reasons.append(
                "Debt service exceeds 50% of monthly surplus in months: "
                + ", ".join(map(str, affordability_failures))
            )

        if schedule and len(monthly_surplus_paise) >= offer.tenure_months:
            for start in range(0, offer.tenure_months, 12):
                end = min(start + 12, offer.tenure_months)

                available = sum(monthly_surplus_paise[start:end])
                debt = sum(
                    row.payment_paise + cc_interest
                    for row in schedule[start:end]
                )

                if debt and available * BPS < debt * minimum_dscr_bps:
                    reasons.append(
                        f"DSCR below required threshold in project year "
                        f"{start // 12 + 1}"
                    )

        term_interest = sum(
            row.interest_accrued_paise for row in schedule
        )
        cc_interest_total = cc_interest * offer.tenure_months

        results.append(
            StackResult(
                offer_id=offer.id,
                feasible=not reasons,
                reasons=tuple(reasons),
                warnings=tuple(warnings),
                own_contribution_paise=own,
                term_loan_paise=term,
                cash_credit_paise=cc,
                pending_backended_subsidy_paise=(
                    offer.pending_backended_subsidy_paise
                ),
                subsidy_applied_upfront_paise=0,
                schedule=tuple(schedule),
                term_interest_total_paise=term_interest,
                cc_interest_over_offer_horizon_paise=cc_interest_total,
                total_interest_over_offer_horizon_paise=(
                    term_interest + cc_interest_total
                ),
                max_monthly_debt_service_paise=max(
                    (
                        row.payment_paise + cc_interest
                        for row in schedule
                    ),
                    default=0,
                ),
                cc_outstanding_at_horizon_paise=cc,
            )
        )

    return results