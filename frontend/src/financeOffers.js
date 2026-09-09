// Illustrative scenario terms only. None of these are confirmed lender
// offers or scheme eligibility — the backend enforces that distinction
// via `eligibility_confirmed` and returns explicit reasons when a term
// cannot be met. Amounts are paise; rates and shares are basis points.

export const PRIMARY_FINANCE_OFFER = {
  id: "ILLUSTRATIVE-TERM-60M",
  annual_rate_bps: 1100,
  tenure_months: 60,
  moratorium_months: 3,
  step_up: true,
  cc_annual_rate_bps: 1200,
  min_own_contribution_bps: 1000,
  max_term_loan_paise: null,
  eligibility_confirmed: null,
  pending_backended_subsidy_paise: 0,
};

export const FUNDING_OPTIONS = [
  {
    id: "PMEGP-ILLUSTRATIVE",
    label: "PMEGP-style subsidised term loan",
    note: "Eligibility for this scheme has not been verified for this applicant.",
    annual_rate_bps: 400,
    tenure_months: 60,
    moratorium_months: 6,
    step_up: false,
    cc_annual_rate_bps: 1200,
    min_own_contribution_bps: 1000,
    max_term_loan_paise: null,
    eligibility_confirmed: null,
    pending_backended_subsidy_paise: 0,
  },
  {
    id: "MUDRA-SHISHU",
    label: "MUDRA Shishu (loans up to ₹50,000)",
    note: "Capped at ₹50,000; may be too small for the required term loan.",
    annual_rate_bps: 900,
    tenure_months: 36,
    moratorium_months: 0,
    step_up: false,
    cc_annual_rate_bps: 1200,
    min_own_contribution_bps: 0,
    max_term_loan_paise: 5_000_000,
    eligibility_confirmed: true,
    pending_backended_subsidy_paise: 0,
  },
  {
    id: "MUDRA-KISHOR",
    label: "MUDRA Kishor (loans up to ₹5,00,000)",
    note: "Capped at ₹5,00,000.",
    annual_rate_bps: 1050,
    tenure_months: 48,
    moratorium_months: 3,
    step_up: false,
    cc_annual_rate_bps: 1200,
    min_own_contribution_bps: 500,
    max_term_loan_paise: 50_000_000,
    eligibility_confirmed: true,
    pending_backended_subsidy_paise: 0,
  },
  {
    id: "BANK-TERM-STANDARD",
    label: "Standard bank term loan",
    note: "Illustrative unsubsidised bank pricing.",
    annual_rate_bps: 1300,
    tenure_months: 60,
    moratorium_months: 3,
    step_up: true,
    cc_annual_rate_bps: 1200,
    min_own_contribution_bps: 1500,
    max_term_loan_paise: null,
    eligibility_confirmed: true,
    pending_backended_subsidy_paise: 0,
  },
];

export function defaultAssumptions() {
  return {
    scale_bps: 10_000,
    preliminary_bps: 300,
    contingency_bps: 500,
    wc_margin_bps: 2500,
    yoy_growth_bps: 800,
    fixed_cost_growth_bps: 500,
    start_calendar_month: 1,
    depreciation_bps: 1500,
    tax_bps: 0,
    minimum_dscr_bps: 12_500,
    additional_wc_paise: Array(60).fill(0),
    owner_drawings_paise: Array(60).fill(300_000),
    adjustment_basis:
      "Default scenario assumes drawings of ₹3,000/month, zero incremental " +
      "working capital and zero cash tax. These are explicit unverified " +
      "inputs, not findings about household needs or tax exemption.",
  };
}
