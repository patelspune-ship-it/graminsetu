from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.dpr.models import (
    Employment,
    FeasibilityReport,
    FinanceTerms,
    Money,
    Note,
    ProjectionAssumptions,
    StrictModel,
)
from app.fin import core, ps_scheme
from app.fin.solver import FinanceOffer, StackResult


# Permit JSON UUID strings without relaxing strict monetary validation.
ApiUUID = Annotated[UUID, Field(strict=False)]


class FinanceInput(FinanceTerms):
    @model_validator(mode="after")
    def validate_moratorium(self):
        if self.moratorium_months >= self.tenure_months:
            raise ValueError("moratorium_months must be below tenure_months")
        return self


class NarrativeInput(StrictModel):
    project_description: Note | None = None
    employment: Employment = Field(default_factory=Employment)
    market_observations: list[Note] = Field(default_factory=list, max_length=6)
    unknowns: list[Note] = Field(default_factory=list, max_length=8)
    risk_factors: list[Note] = Field(default_factory=list, max_length=6)
    additional_assumptions: list[Note] = Field(
        default_factory=list, max_length=6
    )


class ScenarioInput(StrictModel):
    assessment_id: ApiUUID
    archetype_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$", max_length=100
    )

    # Explicitly net of emergency reserves; not assumed equal to savings.
    available_for_project_paise: Money = Field(le=10_000_000_000)
    assumptions: ProjectionAssumptions


class FinancialModelRequest(ScenarioInput):
    finance: FinanceInput
    narrative: NarrativeInput = Field(default_factory=NarrativeInput)

    # Attached by re-submitting this request after the Feasibility Report
    # screen has already generated one; None means not generated yet.
    feasibility_report: FeasibilityReport | None = None

    # Applicant-chosen tenure/moratorium under cost_model="ps_scheme";
    # None means "use the routed scheme's own default". Ignored under
    # "custom_scale". See app.dpr.models.DprSessionData.
    tenure_override_months: int | None = Field(default=None, ge=1, le=360)
    moratorium_override_months: int | None = Field(default=None, ge=0, le=359)


class CapitalStackRequest(ScenarioInput):
    offers: list[FinanceInput] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_offer_ids(self):
        ids = [offer.id for offer in self.offers]
        if len(ids) != len(set(ids)):
            raise ValueError("Offer IDs must be unique")
        return self


class DprGenerateRequest(StrictModel):
    session_id: ApiUUID


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class RatioOut(OutputModel):
    numerator: int
    denominator: int = Field(gt=0)


class DscrOut(OutputModel):
    year: int
    cash_available_paise: int
    debt_service_paise: int
    ratio: RatioOut | None
    meets_1_25: bool | None


class SnapshotOut(OutputModel):
    # Pydantic supports your stdlib dataclasses as nested typed contracts.
    # None of these dataclasses contains Fraction, except DscrYear,
    # which is explicitly represented by DscrOut.
    project: core.ProjectCost
    stack: StackResult
    pnl: list[core.PnlMonth]
    cash: list[core.CashFlowMonth]
    dscr: list[DscrOut]
    breakeven: core.Breakeven
    surplus: list[int]

    cost_model: Literal["ps_scheme", "custom_scale"]
    finance_offer: FinanceOffer
    scheme_route: ps_scheme.SchemeRoute | None
    quarterly_schedule: list[ps_scheme.QuarterlyInstalment]
    operational_costs: ps_scheme.OperationalCostsBreakdown

    scale_bps_used: int
    scale_warning: str | None
    additional_wc_paise: list[int]
    owner_drawings_paise: list[int]


class FinancialModelOut(OutputModel):
    session_id: str
    status: Literal["modelled"]
    assumption_status: Literal["illustrative_unverified"]
    snapshot: SnapshotOut


class RankedOptionOut(OutputModel):
    rank: int
    tenure_months: int
    result: StackResult


class CapitalStackOut(OutputModel):
    session_id: str
    status: Literal["capital_stack_calculated"]
    assumption_status: Literal["illustrative_unverified"]
    ranking_policy: str
    options: list[RankedOptionOut]


class SubScoreOut(OutputModel):
    name: str
    weight_bps: int
    value: RatioOut | None
    note: str


class ViabilityResultOut(OutputModel):
    score: int | None
    verdict: str
    lower_bound_score: int
    upper_bound_score: int
    evidence_coverage_bps: int
    sub_scores: list[SubScoreOut]
    top_drivers: list[SubScoreOut]
    warnings: list[str]


class ViabilityItemOut(OutputModel):
    archetype_id: str
    required_own_contribution_paise: int
    result: ViabilityResultOut
    dataset_signature: str
    model_signature: str
    computed_at: datetime


class ViabilityOut(OutputModel):
    village_lgd: str
    assessment_id: str
    status: Literal["OK", "PARTIAL_COVERAGE", "OUT_OF_COVERAGE"]
    message: str
    contribution_assumption_bps: int
    capital_fit_basis: str
    missing_archetype_ids: list[str]
    items: list[ViabilityItemOut]


class DprOut(OutputModel):
    session_id: str
    status: Literal["dpr_ready"]
    download_url: str


class ErrorBody(OutputModel):
    code: str
    message: str
    session_id: str | None = None


class ErrorOut(OutputModel):
    error: ErrorBody