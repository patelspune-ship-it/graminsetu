from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.dpr.financials import (
    ReconciliationError,
    annual_tables,
    assert_reconciled,
    calculate_financials,
)
from app.dpr.generator import render_html
from app.dpr.models import DprSessionData
from app.dpr.sample import sample_session


def test_means_of_finance_equals_project_cost_exactly():
    f = calculate_financials(sample_session())

    means_of_finance_total = (
        f.stack.own_contribution_paise + f.stack.term_loan_paise
    )
    project_cost_total = f.project.project_cost_paise

    assert type(means_of_finance_total) is int
    assert means_of_finance_total == project_cost_total
    assert (
        means_of_finance_total + f.stack.cash_credit_paise
        == f.project.total_funding_paise
    )

    assert_reconciled(f.project, f.stack)


def test_one_paisa_mismatch_is_rejected():
    f = calculate_financials(sample_session())
    broken = replace(
        f.stack,
        term_loan_paise=f.stack.term_loan_paise + 1,
    )

    with pytest.raises(ReconciliationError):
        assert_reconciled(f.project, broken)


def test_infeasibility_is_preserved():
    f = calculate_financials(sample_session())

    assert f.stack.feasible is False
    assert any(
        "eligibility has not been verified" in reason
        for reason in f.stack.reasons
    )
    assert len(f.stack.schedule) == 60
    assert f.stack.schedule[-1].closing_paise == 0


def test_solver_surplus_is_pre_debt_and_after_adjustments():
    data = sample_session()
    f = calculate_financials(data)

    for index, row in enumerate(f.pnl):
        assert f.surplus[index] == (
            row.cash_available_for_debt_service_paise
            - data.assumptions.additional_wc_paise[index]
            - data.assumptions.owner_drawings_paise[index]
        )


def test_annual_cash_uses_balances_not_balance_sums():
    data = sample_session()
    f = calculate_financials(data)
    pnl_rows, cash_rows = annual_tables(f, data)

    pnl = dict(pnl_rows)
    cash = dict(cash_rows)

    assert pnl["Revenue"][0] == sum(
        row.revenue_paise for row in f.pnl[:12]
    )
    assert cash["Opening cash"][0] == f.cash[1].opening_cash_paise
    assert cash["Closing cash"][0] == f.cash[12].closing_cash_paise

    for year in range(5):
        assert (
            cash["Opening cash"][year] + cash["Net cash movement"][year]
            == cash["Closing cash"][year]
        )


@pytest.mark.parametrize("invalid", [True, 100.0, "100"])
def test_input_money_is_strict(invalid):
    payload = sample_session().model_dump()
    payload["promoter"]["available_for_project_paise"] = invalid

    with pytest.raises(ValidationError):
        DprSessionData.model_validate(payload)


def test_long_tenure_is_rejected_not_truncated():
    payload = sample_session().model_dump()
    payload["finance"]["tenure_months"] = 61

    with pytest.raises(ValidationError):
        DprSessionData.model_validate(payload)


def test_html_escapes_promoter_input():
    payload = sample_session().model_dump()
    payload["promoter"]["name"] = '<img src="https://example.com/tracker">'
    data = DprSessionData.model_validate(payload)

    html = render_html(data)

    assert '<img src="https://example.com/tracker">' not in html
    assert "&lt;img" in html