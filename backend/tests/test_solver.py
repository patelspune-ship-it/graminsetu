from app.fin.core import ProjectCost, WorkingCapital
from app.fin.solver import (
    BorrowerFunds,
    FinanceOffer,
    aligned_moratorium_months,
    capital_stack_solver,
)


def simple_project(cc_paise: int = 0) -> ProjectCost:
    wc = WorkingCapital(
        inventory_paise=cc_paise,
        receivables_paise=0,
        payables_paise=0,
        requirement_paise=cc_paise,
        margin_paise=0,
        cash_credit_paise=cc_paise,
    )

    return ProjectCost(
        machinery_paise=120_000,
        civil_paise=0,
        installation_paise=0,
        preliminary_paise=0,
        contingency_paise=0,
        fixed_investment_paise=120_000,
        working_capital=wc,
        project_cost_paise=120_000,
        total_funding_paise=120_000 + cc_paise,
    )


def zero_interest_offer(**overrides):
    values = {
        "id": "test_offer",
        "annual_rate_bps": 0,
        "tenure_months": 12,
        "cc_annual_rate_bps": 0,
    }
    return FinanceOffer(**(values | overrides))


def test_exact_50_percent_boundary_is_feasible():
    result = capital_stack_solver(
        simple_project(),
        BorrowerFunds(0),
        [zero_interest_offer()],
        [20_000] * 12,
    )[0]

    assert result.feasible
    assert result.max_monthly_debt_service_paise == 10_000


def test_one_paise_below_required_surplus_fails():
    result = capital_stack_solver(
        simple_project(),
        BorrowerFunds(0),
        [zero_interest_offer()],
        [19_999] * 12,
    )[0]

    assert not result.feasible
    assert any("50%" in reason for reason in result.reasons)


def test_good_annual_average_does_not_hide_bad_month():
    surplus = [100_000] * 12
    surplus[5] = 1_000

    result = capital_stack_solver(
        simple_project(),
        BorrowerFunds(0),
        [zero_interest_offer()],
        surplus,
    )[0]

    assert not result.feasible
    assert any("months: 6" in reason for reason in result.reasons)
    assert len(result.schedule) == 12


def test_cash_credit_interest_is_in_affordability():
    result = capital_stack_solver(
        simple_project(cc_paise=10_000),
        BorrowerFunds(0),
        [zero_interest_offer(cc_annual_rate_bps=1_200)],
        [20_000] * 12,
    )[0]

    assert not result.feasible
    assert result.max_monthly_debt_service_paise == 10_100
    assert result.cc_outstanding_at_horizon_paise == 10_000


def test_backended_subsidy_does_not_reduce_initial_loan():
    result = capital_stack_solver(
        simple_project(),
        BorrowerFunds(0),
        [zero_interest_offer(pending_backended_subsidy_paise=40_000)],
        [30_000] * 12,
    )[0]

    assert result.term_loan_paise == 120_000
    assert result.pending_backended_subsidy_paise == 40_000
    assert result.subsidy_applied_upfront_paise == 0


def test_insufficient_projection_horizon_is_infeasible():
    result = capital_stack_solver(
        simple_project(),
        BorrowerFunds(0),
        [zero_interest_offer(tenure_months=24)],
        [100_000] * 12,
    )[0]

    assert not result.feasible
    assert any("Projection covers" in reason for reason in result.reasons)
    assert len(result.schedule) == 24


def test_unverified_eligibility_is_not_approval():
    result = capital_stack_solver(
        simple_project(),
        BorrowerFunds(0),
        [zero_interest_offer(eligibility_confirmed=None)],
        [100_000] * 12,
    )[0]

    assert not result.feasible
    assert any("not been verified" in reason for reason in result.reasons)


def test_own_contribution_requirement_is_enforced():
    result = capital_stack_solver(
        simple_project(),
        BorrowerFunds(1_000),
        [zero_interest_offer(min_own_contribution_bps=1_000)],
        [100_000] * 12,
    )[0]

    assert not result.feasible
    assert any("shortfall" in reason for reason in result.reasons)


def test_moratorium_does_not_cure_operating_losses():
    result = capital_stack_solver(
        simple_project(),
        BorrowerFunds(0),
        [zero_interest_offer(moratorium_months=2)],
        [-100, -100] + [100_000] * 10,
    )[0]

    assert not result.feasible
    assert any("Negative pre-debt" in reason for reason in result.reasons)


def test_seasonality_alignment():
    seasonality = [
        0, 0, 6_000, 14_000, 18_000, 20_000,
        20_000, 18_000, 14_000, 6_000, 4_000, 0,
    ]

    assert aligned_moratorium_months(seasonality) == 3
    assert aligned_moratorium_months(
        seasonality, start_calendar_month=4
    ) == 0

    assert aligned_moratorium_months([10_000] * 12) == 0