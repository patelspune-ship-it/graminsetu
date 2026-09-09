from datetime import date
from typing import Annotated

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

    @field_validator("report_date")
    @classmethod
    def validate_report_date(cls, value: str) -> str:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("report_date must be YYYY-MM-DD")
        return value