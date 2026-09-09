from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


class UnitEconomics(StrictModel):
    unit_label: str = Field(min_length=1)

    revenue_per_unit_paise: int = Field(gt=0)
    units_per_month: int = Field(gt=0)

    variable_cost_bps: int = Field(ge=0, le=10_000)

    # Fraction of variable operating costs eligible for inventory/payables.
    # Processing services and tailoring need different treatment from retail.
    inventory_eligible_cost_bps: int = Field(ge=0, le=10_000)

    fixed_monthly_paise: int = Field(ge=0)

    inventory_days: int = Field(ge=0, le=365)
    receivable_days: int = Field(ge=0, le=365)
    payable_days: int = Field(ge=0, le=365)


class Archetype(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name_en: str = Field(min_length=1)
    name_mr: str = Field(min_length=1)
    category: str = Field(min_length=1)

    catchment_m: int = Field(gt=0)
    competition_categories: list[str] = Field(min_length=1)

    capex_paise: dict[str, int]
    required_skills: list[str]
    inputs_required: list[str]

    demand_coefficient_bps: int = Field(gt=0, le=100_000)
    seasonality_bps: list[int] = Field(min_length=12, max_length=12)

    unit_economics: UnitEconomics

    power_requirement: str
    potential_scheme_families: list[str]

    assumption_status: str
    assumptions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_business(self):
        required_capex = {"machinery", "civil", "installation"}

        if set(self.capex_paise) != required_capex:
            raise ValueError(
                "capex_paise must contain exactly: "
                "machinery, civil, installation"
            )

        if any(value < 0 for value in self.capex_paise.values()):
            raise ValueError("capex_paise cannot contain negative amounts")

        if sum(self.capex_paise.values()) <= 0:
            raise ValueError("Total capex must be positive")

        if any(value < 0 for value in self.seasonality_bps):
            raise ValueError("seasonality_bps cannot contain negative values")

        if sum(self.seasonality_bps) != 120_000:
            raise ValueError(
                "seasonality_bps must sum to 120000 "
                "(annual monthly average = 10000)"
            )

        if self.assumption_status != "illustrative_unverified":
            raise ValueError(
                "These MVP configurations must remain labelled "
                "illustrative_unverified until independently reviewed"
            )

        return self