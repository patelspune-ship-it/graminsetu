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
from app.fin.ps_scheme import (
    MICRO_FINANCE_SCHEME,
    TERM_LOAN_SCHEME,
    SchemeOutOfScopeError,
    quarterly_schedule,
)


def ps_scheme_payload(available_for_project_paise: int) -> dict:
    payload = sample_session().model_dump()
    payload["assumptions"]["cost_model"] = "ps_scheme"
    payload["promoter"]["available_for_project_paise"] = (
        available_for_project_paise
    )
    return payload


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
    pnl_rows, cash_rows = annual_tables(f)

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


def test_absurd_tenure_is_rejected_not_truncated():
    # tenure_months now goes up to 360 (a PS scheme like Term Loan Scheme
    # runs 84 months), but there is still a hard ceiling.
    payload = sample_session().model_dump()
    payload["finance"]["tenure_months"] = 361

    with pytest.raises(ValidationError):
        DprSessionData.model_validate(payload)


def test_custom_scale_tenure_beyond_projection_window_is_infeasible_not_truncated():
    # custom_scale's projection is fixed at 60 months; a tenure beyond
    # that must be flagged as an explicit infeasibility reason, not
    # silently truncated or ignored.
    payload = sample_session().model_dump()
    payload["finance"]["tenure_months"] = 84
    payload["finance"]["moratorium_months"] = 6

    data = DprSessionData.model_validate(payload)
    f = calculate_financials(data)

    assert len(f.stack.schedule) == 84
    assert f.stack.feasible is False
    assert any("Generate a longer projection" in reason for reason in f.stack.reasons)


def test_html_escapes_promoter_input():
    payload = sample_session().model_dump()
    payload["promoter"]["name"] = '<img src="https://example.com/tracker">'
    data = DprSessionData.model_validate(payload)

    html = render_html(data)

    assert '<img src="https://example.com/tracker">' not in html
    assert "&lt;img" in html


def test_ps_scheme_is_the_default_cost_model():
    payload = sample_session().model_dump()
    del payload["assumptions"]["cost_model"]

    data = DprSessionData.model_validate(payload)
    assert data.assumptions.cost_model == "ps_scheme"


def test_ps_scheme_routes_to_micro_finance_and_reconciles():
    data = DprSessionData.model_validate(ps_scheme_payload(1_000_000))
    f = calculate_financials(data)

    assert f.cost_model == "ps_scheme"
    assert f.scheme_route.scheme is MICRO_FINANCE_SCHEME
    assert f.project.project_cost_paise == 10_000_000
    assert f.stack.term_loan_paise == 9_000_000
    assert f.stack.own_contribution_paise == 1_000_000
    assert f.finance_offer.annual_rate_bps == MICRO_FINANCE_SCHEME.annual_rate_bps
    assert f.finance_offer.tenure_months == MICRO_FINANCE_SCHEME.tenure_months
    assert len(f.stack.schedule) == MICRO_FINANCE_SCHEME.tenure_months

    assert_reconciled(f.project, f.stack)


def test_ps_scheme_routes_to_term_loan():
    data = DprSessionData.model_validate(ps_scheme_payload(10_000_000))
    f = calculate_financials(data)

    assert f.scheme_route.scheme is TERM_LOAN_SCHEME
    assert f.project.project_cost_paise == 100_000_000
    assert f.stack.term_loan_paise == 90_000_000
    assert len(f.stack.schedule) == TERM_LOAN_SCHEME.tenure_months

    assert_reconciled(f.project, f.stack)


def test_ps_scheme_out_of_scope_raises_clear_error():
    data = DprSessionData.model_validate(ps_scheme_payload(60_000_000))

    with pytest.raises(SchemeOutOfScopeError, match="50,00,000"):
        calculate_financials(data)


def test_quarterly_schedule_and_operational_costs_appear_in_snapshot():
    data = DprSessionData.model_validate(ps_scheme_payload(1_000_000))
    f = calculate_financials(data)

    assert f.quarterly_schedule == tuple(quarterly_schedule(f.stack.schedule))
    assert f.operational_costs.monthly_total_operating_cost_paise == (
        f.operational_costs.monthly_variable_cost_paise
        + f.operational_costs.monthly_fixed_cost_paise
    )


def test_custom_scale_still_available_as_secondary_path():
    f = calculate_financials(sample_session())

    assert f.cost_model == "custom_scale"
    assert f.scheme_route is None
    # Quarterly schedule and operating costs are still produced.
    assert f.quarterly_schedule == tuple(quarterly_schedule(f.stack.schedule))
    assert f.operational_costs.annual_total_operating_cost_paise > 0


# ---------------------------------------------------------------------------
# Bug fix 1: revenue/costs must scale with the PS-derived project cost,
# not stay pinned at the archetype's rated (1x) economics.
# ---------------------------------------------------------------------------


def test_ps_scheme_revenue_scales_with_project_cost():
    small = calculate_financials(
        DprSessionData.model_validate(ps_scheme_payload(200_000))
    )
    large = calculate_financials(
        DprSessionData.model_validate(ps_scheme_payload(2_000_000))
    )

    # 10x the margin means 10x the project cost and 10x the archetype scale,
    # so rated monthly revenue should also be ~10x, not identical.
    assert large.scale_bps_used == small.scale_bps_used * 10
    assert large.operational_costs.monthly_revenue_paise == (
        small.operational_costs.monthly_revenue_paise * 10
    )
    assert large.pnl[0].revenue_paise == small.pnl[0].revenue_paise * 10


def test_ps_scheme_scale_used_is_not_the_rated_default():
    data = DprSessionData.model_validate(ps_scheme_payload(1_000_000))
    f = calculate_financials(data)

    # flour_mill base capex is Rs 2,00,000; project cost here is
    # Rs 1,00,000 -> scale should be 0.5x (5000 bps), not the 10000 bps
    # (1x rated) default used before this was wired through.
    assert f.scale_bps_used == 5_000


def test_ps_scheme_scale_warning_when_capped():
    # 25x flour_mill's base capex (Rs 2,00,000) is Rs 50,00,000 project
    # cost, right at the Term Loan Scheme ceiling.
    data = DprSessionData.model_validate(ps_scheme_payload(50_000_000))
    f = calculate_financials(data)

    assert f.scale_warning is not None
    assert "20.0x" in f.scale_warning
    from app.fin.ps_scheme import MAX_SCALE_BPS
    assert f.scale_bps_used == MAX_SCALE_BPS


def test_custom_scale_scale_warning_is_never_set():
    f = calculate_financials(sample_session())
    assert f.scale_warning is None


# ---------------------------------------------------------------------------
# Bug fix 2: the projection horizon must match the routed scheme's tenure,
# so the DSCR table (and cash flow) cover the full loan life.
# ---------------------------------------------------------------------------


def test_ps_scheme_micro_finance_projection_is_36_months():
    data = DprSessionData.model_validate(ps_scheme_payload(1_000_000))
    f = calculate_financials(data)

    assert len(f.pnl) == 36
    assert len(f.dscr) == 3


def test_ps_scheme_term_loan_projection_is_84_months():
    data = DprSessionData.model_validate(ps_scheme_payload(10_000_000))
    f = calculate_financials(data)

    assert len(f.pnl) == 84
    assert len(f.dscr) == 7
    # Every accrued month of interest is captured in the P&L/cash flow;
    # none of the loan's later months are silently dropped.
    assert sum(row.term_interest_paise for row in f.pnl) == sum(
        row.interest_accrued_paise for row in f.stack.schedule
    )


def test_custom_scale_projection_is_still_60_months():
    f = calculate_financials(sample_session())
    assert len(f.pnl) == 60
    assert len(f.dscr) == 5


def test_ps_scheme_assumption_arrays_extend_to_loan_tenure():
    payload = ps_scheme_payload(10_000_000)
    # Give owner drawings a distinctive last value to confirm it's carried
    # forward into the extra 24 months (84 - 60) beyond the raw input.
    payload["assumptions"]["owner_drawings_paise"] = [500_000] * 60
    payload["assumptions"]["additional_wc_paise"] = [7_000] * 60

    data = DprSessionData.model_validate(payload)
    f = calculate_financials(data)

    assert len(f.owner_drawings_paise) == 84
    assert len(f.additional_wc_paise) == 84
    assert f.owner_drawings_paise[60:] == (500_000,) * 24
    # Incremental WC has no known continuation; pads with zero, not the
    # last supplied value.
    assert f.additional_wc_paise[60:] == (0,) * 24


# ---------------------------------------------------------------------------
# Demo scenario: Rs 1,00,000 margin on a Milk Collection Service Point
# (dairy_collection) must be feasible with DSCR >= 1.25 every year.
# ---------------------------------------------------------------------------


def test_dairy_collection_ps_scheme_demo_is_feasible():
    from app.archetypes import get_archetype

    payload = ps_scheme_payload(100_000 * 100)  # Rs 1,00,000 margin
    payload["archetype"] = get_archetype("dairy_collection").model_dump()

    data = DprSessionData.model_validate(payload)
    f = calculate_financials(data)

    assert f.scheme_route.scheme is TERM_LOAN_SCHEME
    assert f.stack.feasible is True
    assert f.stack.reasons == ()
    assert len(f.dscr) == 7

    for row in f.dscr:
        assert row.meets_1_25 is True


# ---------------------------------------------------------------------------
# Applicant-chosen tenure/moratorium, overriding the routed scheme default.
# ---------------------------------------------------------------------------


def test_ps_scheme_uses_scheme_default_when_no_override_given():
    data = DprSessionData.model_validate(ps_scheme_payload(1_000_000))
    f = calculate_financials(data)

    assert f.finance_offer.tenure_months == MICRO_FINANCE_SCHEME.tenure_months
    assert f.finance_offer.moratorium_months == MICRO_FINANCE_SCHEME.moratorium_months


def test_ps_scheme_honours_tenure_and_moratorium_override():
    payload = ps_scheme_payload(1_000_000)
    payload["tenure_override_months"] = 24
    payload["moratorium_override_months"] = 1

    data = DprSessionData.model_validate(payload)
    f = calculate_financials(data)

    assert f.finance_offer.tenure_months == 24
    assert f.finance_offer.moratorium_months == 1
    # The rate is not applicant-adjustable — it stays fixed to the scheme.
    assert f.finance_offer.annual_rate_bps == MICRO_FINANCE_SCHEME.annual_rate_bps

    assert len(f.stack.schedule) == 24
    assert f.stack.schedule[-1].closing_paise == 0
    # The projection horizon follows the chosen tenure, not the default.
    assert len(f.pnl) == 24


def test_ps_scheme_override_can_use_only_tenure_or_only_moratorium():
    base = ps_scheme_payload(1_000_000)

    tenure_only = {**base, "tenure_override_months": 48}
    f = calculate_financials(DprSessionData.model_validate(tenure_only))
    assert f.finance_offer.tenure_months == 48
    assert f.finance_offer.moratorium_months == MICRO_FINANCE_SCHEME.moratorium_months

    moratorium_only = {**base, "moratorium_override_months": 0}
    f = calculate_financials(DprSessionData.model_validate(moratorium_only))
    assert f.finance_offer.tenure_months == MICRO_FINANCE_SCHEME.tenure_months
    assert f.finance_offer.moratorium_months == 0


def test_ps_scheme_override_rejects_moratorium_at_or_above_tenure():
    payload = ps_scheme_payload(1_000_000)
    payload["tenure_override_months"] = 12
    payload["moratorium_override_months"] = 12

    data = DprSessionData.model_validate(payload)
    with pytest.raises(ValueError, match="moratorium_override_months"):
        calculate_financials(data)


def test_ps_scheme_short_tenure_can_break_the_fifty_percent_constraint():
    # A margin that's comfortably feasible on the scheme default tenure
    # (84 months) should be able to become infeasible if the applicant
    # chooses an aggressively short tenure instead, since the same
    # principal must now be repaid much faster.
    from app.archetypes import get_archetype

    payload = ps_scheme_payload(100_000 * 100)  # Rs 1,00,000 margin
    payload["archetype"] = get_archetype("dairy_collection").model_dump()
    payload["tenure_override_months"] = 7
    payload["moratorium_override_months"] = 0

    data = DprSessionData.model_validate(payload)
    f = calculate_financials(data)

    assert f.finance_offer.tenure_months == 7
    assert f.stack.feasible is False
    assert any(
        "exceeds 50% of monthly surplus" in reason for reason in f.stack.reasons
    )


def test_ps_scheme_override_ignored_under_custom_scale():
    payload = sample_session().model_dump()
    payload["tenure_override_months"] = 12
    payload["moratorium_override_months"] = 0

    data = DprSessionData.model_validate(payload)
    f = calculate_financials(data)

    # custom_scale takes its tenure from `finance`, unaffected by the
    # ps_scheme-only override fields.
    assert f.finance_offer.tenure_months == sample_session().finance.tenure_months