from dataclasses import fields
from fractions import Fraction

import pytest

from app.archetypes import get_archetype
from app.fin.core import BPS, repayment_schedule
from app.fin.ps_scheme import (
    MAX_SCALE_BPS,
    MICRO_FINANCE_CEILING_PAISE,
    MICRO_FINANCE_SCHEME,
    TERM_LOAN_CEILING_PAISE,
    TERM_LOAN_SCHEME,
    SchemeOutOfScopeError,
    build_ps_financing_plan,
    derive_scale_bps,
    max_loan_from_project_cost,
    operational_costs_breakdown,
    project_cost_from_margin,
    quarterly_schedule,
    route_scheme,
)


def sample_archetype():
    return get_archetype("flour_mill")


def assert_monetary_fields_are_int(rows):
    for row in rows:
        for field in fields(row):
            if field.name.endswith("_paise"):
                assert type(getattr(row, field.name)) is int


# ---------------------------------------------------------------------------
# Formula: project_cost = margin * 10, max_loan = project_cost * 0.9.
# Tested as a property, not a hardcoded worked example, across margins
# spanning both scheme branches and the out-of-scope region.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "margin_paise",
    [
        1,
        500_000,          # micro finance branch
        10_000_000,       # term loan branch
        60_000_000,       # out-of-scope branch
        123_456_789,
    ],
)
def test_project_cost_and_max_loan_follow_the_formula_exactly(margin_paise):
    project_cost = project_cost_from_margin(margin_paise)
    max_loan = max_loan_from_project_cost(project_cost)

    assert type(project_cost) is int
    assert type(max_loan) is int
    assert project_cost == margin_paise * 10
    assert max_loan == Fraction(project_cost * 90, 100)
    assert max_loan == margin_paise * 9


def test_project_cost_and_max_loan_reject_non_int():
    with pytest.raises(TypeError):
        project_cost_from_margin(100.0)

    with pytest.raises(TypeError):
        max_loan_from_project_cost(100.0)


# ---------------------------------------------------------------------------
# Scheme router: both branches and the exact Rs 1.40 Lakh boundary.
# ---------------------------------------------------------------------------


def test_micro_finance_scheme_terms():
    assert MICRO_FINANCE_SCHEME.annual_rate_bps == 650
    assert MICRO_FINANCE_SCHEME.tenure_months == 36
    assert MICRO_FINANCE_SCHEME.moratorium_months == 3


def test_term_loan_scheme_terms():
    assert TERM_LOAN_SCHEME.annual_rate_bps == 800
    assert TERM_LOAN_SCHEME.tenure_months == 84
    assert TERM_LOAN_SCHEME.moratorium_months == 6


def test_routes_to_micro_finance_below_ceiling():
    route = route_scheme(MICRO_FINANCE_CEILING_PAISE - 1)
    assert route.in_scope is True
    assert route.scheme is MICRO_FINANCE_SCHEME


def test_routes_to_micro_finance_at_exact_boundary():
    # Rs 1,40,000 project cost, exactly at the ceiling, is still Micro Finance.
    assert MICRO_FINANCE_CEILING_PAISE == 140_000 * 100

    route = route_scheme(MICRO_FINANCE_CEILING_PAISE)
    assert route.in_scope is True
    assert route.scheme is MICRO_FINANCE_SCHEME


def test_routes_to_term_loan_one_paisa_above_micro_boundary():
    route = route_scheme(MICRO_FINANCE_CEILING_PAISE + 1)
    assert route.in_scope is True
    assert route.scheme is TERM_LOAN_SCHEME


def test_routes_to_term_loan_at_exact_upper_boundary():
    assert TERM_LOAN_CEILING_PAISE == 50_00_000 * 100

    route = route_scheme(TERM_LOAN_CEILING_PAISE)
    assert route.in_scope is True
    assert route.scheme is TERM_LOAN_SCHEME


def test_out_of_scope_one_paisa_above_term_loan_boundary():
    route = route_scheme(TERM_LOAN_CEILING_PAISE + 1)

    assert route.in_scope is False
    assert route.scheme is None
    assert "out of scope" in route.message.lower()
    assert "50,00,000" in route.message


def test_route_scheme_rejects_non_int():
    with pytest.raises(TypeError):
        route_scheme(100.0)


# ---------------------------------------------------------------------------
# Quarterly schedule.
# ---------------------------------------------------------------------------


def test_quarterly_schedule_aggregates_full_quarters_exactly():
    monthly = repayment_schedule(1_000_000, 800, 36, moratorium_months=3)
    quarterly = quarterly_schedule(monthly)

    assert len(quarterly) == 12
    assert [row.quarter for row in quarterly] == list(range(1, 13))

    for index, q_row in enumerate(quarterly):
        chunk = monthly[index * 3:index * 3 + 3]

        assert q_row.opening_paise == chunk[0].opening_paise
        assert q_row.closing_paise == chunk[-1].closing_paise
        assert q_row.payment_paise == sum(r.payment_paise for r in chunk)
        assert q_row.principal_paid_paise == sum(
            r.principal_paid_paise for r in chunk
        )
        assert q_row.interest_accrued_paise == sum(
            r.interest_accrued_paise for r in chunk
        )

    assert quarterly[-1].closing_paise == 0
    assert sum(q.payment_paise for q in quarterly) == sum(
        m.payment_paise for m in monthly
    )
    assert_monetary_fields_are_int(quarterly)


def test_quarterly_schedule_handles_trailing_partial_quarter():
    monthly = repayment_schedule(100, 0, 4)
    quarterly = quarterly_schedule(monthly)

    assert len(quarterly) == 2
    assert quarterly[0].quarter == 1
    assert quarterly[1].quarter == 2
    assert quarterly[1].closing_paise == 0
    assert quarterly[1].payment_paise == monthly[3].payment_paise


def test_quarterly_schedule_empty_input():
    assert quarterly_schedule([]) == []


def test_quarterly_schedule_rejects_noncontiguous_months():
    monthly = list(repayment_schedule(100, 0, 6))
    monthly[3], monthly[4] = monthly[4], monthly[3]

    with pytest.raises(ValueError, match="contiguous"):
        quarterly_schedule(monthly)


# ---------------------------------------------------------------------------
# Operational costs breakdown.
# ---------------------------------------------------------------------------


def test_operational_costs_breakdown_matches_rated_unit_economics():
    archetype = sample_archetype()
    economics = archetype.unit_economics

    breakdown = operational_costs_breakdown(archetype)

    expected_revenue = economics.revenue_per_unit_paise * economics.units_per_month
    assert breakdown.monthly_revenue_paise == expected_revenue
    assert breakdown.monthly_fixed_cost_paise == economics.fixed_monthly_paise
    assert breakdown.monthly_total_operating_cost_paise == (
        breakdown.monthly_variable_cost_paise + breakdown.monthly_fixed_cost_paise
    )
    assert breakdown.annual_total_operating_cost_paise == (
        breakdown.monthly_total_operating_cost_paise * 12
    )
    assert_monetary_fields_are_int([breakdown])


def test_operational_costs_breakdown_scales_with_scale_bps():
    archetype = sample_archetype()

    full = operational_costs_breakdown(archetype, scale_bps=10_000)
    half = operational_costs_breakdown(archetype, scale_bps=5_000)

    assert half.monthly_revenue_paise == pytest.approx(
        full.monthly_revenue_paise / 2, abs=1
    )


# ---------------------------------------------------------------------------
# End-to-end plan builder.
# ---------------------------------------------------------------------------


def test_build_ps_financing_plan_reconciles_margin_and_loan():
    archetype = sample_archetype()
    plan = build_ps_financing_plan(archetype, 1_000_000)

    assert plan.project_cost_paise == 10_000_000
    assert plan.max_loan_paise == 9_000_000
    assert plan.loan_paise == plan.max_loan_paise
    assert plan.margin_paise + plan.max_loan_paise == plan.project_cost_paise
    assert plan.route.scheme is MICRO_FINANCE_SCHEME

    assert len(plan.schedule) == MICRO_FINANCE_SCHEME.tenure_months
    assert plan.schedule[0].opening_paise == plan.loan_paise
    assert plan.schedule[-1].closing_paise == 0

    assert plan.quarterly_schedule == tuple(quarterly_schedule(plan.schedule))
    assert plan.operational_costs == operational_costs_breakdown(archetype)


def test_build_ps_financing_plan_routes_to_term_loan():
    archetype = sample_archetype()
    plan = build_ps_financing_plan(archetype, 10_000_000)

    assert plan.project_cost_paise == 100_000_000
    assert plan.route.scheme is TERM_LOAN_SCHEME
    assert len(plan.schedule) == TERM_LOAN_SCHEME.tenure_months


def test_build_ps_financing_plan_raises_when_out_of_scope():
    archetype = sample_archetype()

    with pytest.raises(SchemeOutOfScopeError, match="Out of scope"):
        build_ps_financing_plan(archetype, 60_000_000)


def test_build_ps_financing_plan_honours_explicit_partial_loan():
    archetype = sample_archetype()
    plan = build_ps_financing_plan(archetype, 1_000_000, loan_paise=1_000_000)

    assert plan.loan_paise == 1_000_000
    assert plan.schedule[0].opening_paise == 1_000_000


def test_build_ps_financing_plan_rejects_loan_above_eligibility():
    archetype = sample_archetype()

    with pytest.raises(ValueError):
        build_ps_financing_plan(archetype, 1_000_000, loan_paise=999_999_999)


# ---------------------------------------------------------------------------
# Scale derivation: scale = project_cost / archetype_base_capex_total.
# ---------------------------------------------------------------------------


def test_derive_scale_bps_follows_the_formula():
    archetype = sample_archetype()
    base_capex = sum(archetype.capex_paise.values())
    assert base_capex == 20_000_000

    # Project cost equal to base capex is exactly 1x (rated) scale.
    scale = derive_scale_bps(archetype, base_capex)
    assert scale.scale_bps == BPS
    assert scale.capped is False
    assert scale.warning is None

    # A project cost of 10x base capex derives a 10x scale.
    scale = derive_scale_bps(archetype, base_capex * 10)
    assert scale.scale_bps == 10 * BPS
    assert scale.capped is False


def test_derive_scale_bps_caps_at_maximum_and_warns():
    archetype = sample_archetype()
    base_capex = sum(archetype.capex_paise.values())

    # 25x the archetype's rated capex exceeds the 20x cap.
    scale = derive_scale_bps(archetype, base_capex * 25)

    assert scale.raw_scale_bps == 25 * BPS
    assert scale.scale_bps == MAX_SCALE_BPS
    assert scale.capped is True
    assert scale.warning is not None
    assert "20.0x" in scale.warning


def test_derive_scale_bps_within_cap_has_no_warning():
    archetype = sample_archetype()
    base_capex = sum(archetype.capex_paise.values())

    scale = derive_scale_bps(archetype, base_capex * 20)

    assert scale.capped is False
    assert scale.warning is None


def test_derive_scale_bps_rejects_non_int():
    archetype = sample_archetype()

    with pytest.raises(TypeError):
        derive_scale_bps(archetype, 100.0)
