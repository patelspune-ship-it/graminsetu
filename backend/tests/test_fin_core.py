from dataclasses import fields
from fractions import Fraction

import pytest

from app.archetypes import ARCHETYPES, get_archetype
from app.archetypes.schema import Archetype
from app.fin.core import (
    breakeven,
    cash_flow,
    dscr,
    profit_and_loss,
    project_cost,
    repayment_schedule,
    revenue_projection,
    round_half_up,
    working_capital,
)


def sample_archetype() -> Archetype:
    data = get_archetype("flour_mill").model_dump()

    data["seasonality_bps"] = [10_000] * 12
    data["capex_paise"] = {
        "machinery": 100_000,
        "civil": 0,
        "installation": 0,
    }
    data["unit_economics"] = {
        "unit_label": "test unit",
        "revenue_per_unit_paise": 1_000,
        "units_per_month": 100,
        "variable_cost_bps": 4_000,
        "inventory_eligible_cost_bps": 10_000,
        "fixed_monthly_paise": 10_000,
        "inventory_days": 15,
        "receivable_days": 6,
        "payable_days": 9,
    }

    return Archetype.model_validate(data)


def assert_monetary_fields_are_int(rows):
    for row in rows:
        for field in fields(row):
            if field.name.endswith("_paise"):
                assert type(getattr(row, field.name)) is int


def test_six_configs_load():
    assert set(ARCHETYPES) == {
        "onion_storage",
        "flour_mill",
        "dal_mill",
        "tailoring_unit",
        "dairy_collection",
        "kirana_store",
    }


def test_rounding_is_explicit_half_up():
    assert round_half_up(Fraction(1, 2)) == 1
    assert round_half_up(Fraction(3, 2)) == 2
    assert round_half_up(Fraction(-1, 2)) == -1

    with pytest.raises(TypeError):
        round_half_up(0.5)


def test_working_capital_uses_correct_bases():
    wc = working_capital(sample_archetype())

    # Monthly sales = 100000 paise.
    # Variable purchases = 40000 paise.
    assert wc.inventory_paise == 20_000
    assert wc.receivables_paise == 20_000
    assert wc.payables_paise == 12_000

    assert wc.requirement_paise == 28_000
    assert wc.margin_paise == 7_000
    assert wc.cash_credit_paise == 21_000

    assert wc.margin_paise + wc.cash_credit_paise == wc.requirement_paise


def test_project_cost_has_no_wc_double_counting():
    cost = project_cost(sample_archetype())

    assert cost.preliminary_paise == 3_000
    assert cost.contingency_paise == 5_000
    assert cost.fixed_investment_paise == 108_000

    assert cost.project_cost_paise == 115_000
    assert cost.total_funding_paise == 136_000

    assert (
        cost.project_cost_paise
        + cost.working_capital.cash_credit_paise
        == cost.total_funding_paise
    )


def test_revenue_capacity_ramp_and_no_float_money():
    rows = revenue_projection(
        sample_archetype(),
        years=5,
        yoy_growth_bps=0,
        fixed_cost_growth_bps=0,
    )

    assert len(rows) == 60
    assert rows[0].revenue_paise == 70_000
    assert rows[12].revenue_paise == 85_000
    assert rows[24].revenue_paise == 95_000
    assert rows[48].revenue_paise == 95_000

    assert rows[0].variable_cost_paise == 28_000
    assert rows[0].fixed_cost_paise == 10_000

    assert_monetary_fields_are_int(rows)


def test_seasonality_rotates_with_start_month():
    archetype = get_archetype("onion_storage")

    january = revenue_projection(archetype, years=1)
    april = revenue_projection(
        archetype,
        years=1,
        start_calendar_month=4,
    )

    assert january[0].seasonality_bps == 0
    assert january[0].revenue_paise == 0

    assert april[0].seasonality_bps == 14_000
    assert april[0].revenue_paise > 0


@pytest.mark.parametrize("principal", [1, 101, 100_000, 12_345_678])
@pytest.mark.parametrize("rate", [0, 1_200])
@pytest.mark.parametrize("moratorium", [0, 3])
@pytest.mark.parametrize("step_up", [False, True])
def test_loan_reconciles(principal, rate, moratorium, step_up):
    rows = repayment_schedule(
        principal,
        rate,
        36,
        moratorium_months=moratorium,
        step_up=step_up,
    )

    assert len(rows) == 36
    assert rows[-1].closing_paise == 0
    assert rows[0].opening_paise == principal

    for index, row in enumerate(rows):
        assert row.closing_paise >= 0

        assert (
            row.interest_paid_paise
            + row.capitalized_interest_paise
            == row.interest_accrued_paise
        )
        assert (
            row.principal_paid_paise + row.interest_paid_paise
            == row.payment_paise
        )
        assert (
            row.opening_paise
            + row.capitalized_interest_paise
            - row.principal_paid_paise
            == row.closing_paise
        )

        if index:
            assert row.opening_paise == rows[index - 1].closing_paise

    capitalized = sum(row.capitalized_interest_paise for row in rows)
    principal_paid = sum(row.principal_paid_paise for row in rows)
    interest = sum(row.interest_accrued_paise for row in rows)
    payments = sum(row.payment_paise for row in rows)

    assert principal_paid == principal + capitalized
    assert payments == principal + interest
    assert_monetary_fields_are_int(rows)


def test_moratorium_capitalizes_exactly():
    rows = repayment_schedule(
        100_000,
        1_200,
        24,
        moratorium_months=2,
    )

    assert rows[0].payment_paise == 0
    assert rows[0].capitalized_interest_paise == 1_000
    assert rows[0].closing_paise == 101_000

    assert rows[1].capitalized_interest_paise == 1_010
    assert rows[1].closing_paise == 102_010


def test_step_up_uses_original_tenure():
    rows = repayment_schedule(
        1_200_000,
        0,
        24,
        step_up=True,
    )

    assert len(rows) == 24

    # Ordinary payment = 50000; 70% = 35000.
    assert all(row.payment_paise == 35_000 for row in rows[:12])
    assert all(row.payment_paise == 65_000 for row in rows[12:])

    assert rows[-1].closing_paise == 0


def test_invalid_step_up_does_not_extend_tenure():
    with pytest.raises(ValueError, match="more than 12"):
        repayment_schedule(100_000, 1_200, 12, step_up=True)


def test_float_money_is_rejected():
    with pytest.raises(TypeError):
        repayment_schedule(100_000.0, 1_200, 12)

    with pytest.raises(TypeError):
        repayment_schedule(True, 1_200, 12)


def test_zero_interest_rounding_has_no_balloon():
    rows = repayment_schedule(100, 0, 3)

    assert [row.payment_paise for row in rows] == [34, 34, 32]
    assert rows[-1].closing_paise == 0


def test_pnl_depreciation_and_cashflow_reconcile():
    archetype = sample_archetype()
    project = project_cost(archetype)
    own = 20_000

    loan = repayment_schedule(
        project.project_cost_paise - own,
        1_200,
        24,
        moratorium_months=2,
    )
    revenue = revenue_projection(
        archetype,
        years=2,
        yoy_growth_bps=0,
        fixed_cost_growth_bps=0,
    )
    pnl = profit_and_loss(
        revenue,
        loan,
        machinery_paise=project.machinery_paise,
        cash_credit_paise=project.working_capital.cash_credit_paise,
        cc_annual_rate_bps=1_200,
    )

    assert sum(row.depreciation_paise for row in pnl[:12]) == 15_000
    assert sum(row.depreciation_paise for row in pnl[12:]) == 12_750

    cf = cash_flow(pnl, project, loan, own)

    assert len(cf) == 25
    assert cf[0].financing_inflow_paise == project.total_funding_paise
    assert cf[0].closing_cash_paise == 0

    for index, row in enumerate(cf[1:]):
        p = pnl[index]
        debt = loan[index]

        # PAT + depreciation + non-cash capitalized interest
        # - term principal = cash after debt, including CC interest.
        expected_net = (
            p.profit_after_tax_paise
            + p.depreciation_paise
            + debt.capitalized_interest_paise
            - debt.principal_paid_paise
        )

        assert row.net_cash_paise == expected_net
        assert row.closing_cash_paise == (
            row.opening_cash_paise + row.net_cash_paise
        )

    assert_monetary_fields_are_int(pnl)
    assert_monetary_fields_are_int(cf)


def test_cashflow_rejects_unbalanced_funding():
    archetype = sample_archetype()
    project = project_cost(archetype)
    revenue = revenue_projection(archetype, years=1)
    loan = repayment_schedule(50_000, 0, 12)
    pnl = profit_and_loss(revenue, loan, project.machinery_paise)

    with pytest.raises(ValueError, match="equal"):
        cash_flow(pnl, project, loan, own_contribution_paise=1)


def test_dscr_uses_exact_fraction():
    archetype = sample_archetype()
    revenue = revenue_projection(archetype, years=1)
    loan = repayment_schedule(120_000, 0, 12)
    pnl = profit_and_loss(revenue, loan, 100_000)

    result = dscr(pnl, loan)[0]

    assert result.cash_available_paise == 384_000
    assert result.debt_service_paise == 120_000
    assert result.ratio == Fraction(16, 5)
    assert result.meets_1_25 is True


def test_no_debt_dscr_is_none_not_infinity():
    revenue = revenue_projection(sample_archetype(), years=1)
    pnl = profit_and_loss(revenue, [], 100_000)

    result = dscr(pnl, [])[0]

    assert result.ratio is None
    assert result.meets_1_25 is None


def test_breakeven_rounds_up():
    result = breakeven(sample_archetype(), 120_000)

    assert result.contribution_margin_bps == 6_000
    assert result.revenue_paise == 200_000
    assert result.units == 200


def test_zero_contribution_has_no_finite_breakeven():
    data = sample_archetype().model_dump()
    data["unit_economics"]["variable_cost_bps"] = 10_000

    result = breakeven(Archetype.model_validate(data), 120_000)

    assert result.revenue_paise is None
    assert result.reason == "Non-positive contribution margin"