from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.archetypes.schema import Archetype


Money = Annotated[int, Field(strict=True, ge=0)]
SignedMoney = Annotated[int, Field(strict=True)]
RateBps = Annotated[int, Field(strict=True, ge=0, le=10_000)]
ShortText = Annotated[str, Field(min_length=1, max_length=180)]
Note = Annotated[str, Field(min_length=1, max_length=320)]
# Longer LLM-narrative sections (feasibility report); still bounded, so a
# malfunctioning generator cannot silently blow out the fixed-page layout.
Narrative = Annotated[str, Field(min_length=1, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


class Promoter(StrictModel):
    name: ShortText
    village: ShortText
    district: ShortText
    state: ShortText

    # Already net of household emergency reserves.
    available_for_project_paise: Money

    address: ShortText | None = None
    education: ShortText | None = None
    experience: ShortText | None = None
    skills: list[ShortText] = Field(max_length=7)
    premises: ShortText | None = None
    power: ShortText | None = None


class FinanceTerms(StrictModel):
    id: ShortText
    annual_rate_bps: RateBps
    tenure_months: int = Field(ge=1, le=60)
    moratorium_months: int = Field(ge=0, le=59)
    step_up: bool

    cc_annual_rate_bps: RateBps
    min_own_contribution_bps: RateBps
    max_term_loan_paise: Money | None

    eligibility_confirmed: bool | None
    pending_backended_subsidy_paise: Money


class ProjectionAssumptions(StrictModel):
    # "ps_scheme" (primary, PS-mandated): project cost and loan sizing are
    # derived from available_for_project_paise via app.fin.ps_scheme, and
    # the scheme router selects rate/tenure/moratorium; the finance block's
    # own rate/tenure/moratorium/step_up are not used.
    # "custom_scale" (secondary): the pre-existing bottom-up archetype
    # capex model (app.fin.core.project_cost), financed by the supplied
    # finance terms.
    cost_model: Literal["ps_scheme", "custom_scale"] = "ps_scheme"

    scale_bps: int = Field(ge=1, le=100_000)
    preliminary_bps: RateBps
    contingency_bps: RateBps
    wc_margin_bps: RateBps

    yoy_growth_bps: RateBps
    fixed_cost_growth_bps: RateBps
    start_calendar_month: int = Field(ge=1, le=12)

    depreciation_bps: RateBps
    tax_bps: RateBps
    minimum_dscr_bps: int = Field(ge=1)

    # Exactly five years; amounts are monthly, not annual.
    additional_wc_paise: list[SignedMoney] = Field(
        min_length=60, max_length=60
    )
    owner_drawings_paise: list[Money] = Field(
        min_length=60, max_length=60
    )

    adjustment_basis: Note


class Employment(StrictModel):
    # None means not established, not zero.
    proprietor_roles: int | None = Field(default=None, ge=0)
    paid_full_time_jobs: int | None = Field(default=None, ge=0)
    paid_part_time_jobs: int | None = Field(default=None, ge=0)
    wage_cost_basis: Note | None = None


class DataSource(StrictModel):
    name: ShortText
    reference: ShortText
    status: Note


class Swot(StrictModel):
    strengths: Narrative
    weaknesses: Narrative
    opportunities: Narrative
    threats: Narrative


class CompetitorMapping(StrictModel):
    # Verbatim pass-through of the computed market_gap sub-score; never
    # produced or rephrased by the LLM. None means no evidence computed.
    value_percent: ShortText | None = None
    note: Note | None = None


class FeasibilityReport(StrictModel):
    """Hyper-Local Business Feasibility Report (app.llm.feasibility_report).

    Narrative only — every number in it must already exist elsewhere in
    this session's computed data. None on DprSessionData means a report
    was never generated for this session, not that generation failed
    silently.
    """
    market_reach: Narrative
    opportunity_analysis: Narrative
    swot: Swot
    threats: Narrative
    competitor_mapping: CompetitorMapping
    product_market_value: Narrative


class DprSessionData(StrictModel):
    report_id: ShortText
    report_date: str
    promoter: Promoter
    archetype: Archetype
    finance: FinanceTerms
    assumptions: ProjectionAssumptions
    employment: Employment

    project_description: Note
    market_observations: list[Note] = Field(max_length=6)
    unknowns: list[Note] = Field(max_length=10)
    risk_factors: list[Note] = Field(max_length=6)
    additional_assumptions: list[Note] = Field(max_length=6)
    data_sources: list[DataSource] = Field(min_length=1, max_length=6)

    # None means not generated for this session; the DPR states this
    # explicitly rather than omitting the section.
    feasibility_report: FeasibilityReport | None = None

    @field_validator("report_date")
    @classmethod
    def validate_report_date(cls, value: str) -> str:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("report_date must be YYYY-MM-DD")
        return value