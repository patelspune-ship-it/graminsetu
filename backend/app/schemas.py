from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Skill = Literal[
    "basic_machine_operation",
    "farming",
    "animal_husbandry",
    "tailoring",
    "retail_sales",
    "food_processing",
    "bookkeeping",
]

Language = Literal["en", "mr", "hi"]
Premises = Literal["owned", "rented", "not_arranged"]
Power = Literal["single_phase", "three_phase", "unavailable", "unknown"]


class ProfileCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    applicant_name: str = Field(min_length=2, max_length=100)
    village_id: str = Field(min_length=1, max_length=100)
    preferred_language: Language = "en"

    # Strict prevents JSON strings/floats/bools from becoming money.
    own_capital_paise: int = Field(
        strict=True,
        ge=0,
        le=10_000_000_000,
    )

    skills: list[Skill] = Field(default_factory=list, max_length=7)
    premises: Premises = "not_arranged"
    power: Power = "unknown"

    # Optional pin dropped on the "Select on Map" picker. Purely additive
    # context for a location-based catchment lookup — never used to look
    # up village_lgd, and never changes viability scoring or evidence.
    proposed_latitude: float | None = Field(default=None, ge=-90, le=90)
    proposed_longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("skills")
    @classmethod
    def deduplicate_skills(cls, value: list[Skill]) -> list[Skill]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_proposed_location(self):
        has_lat = self.proposed_latitude is not None
        has_lng = self.proposed_longitude is not None

        if has_lat != has_lng:
            raise ValueError(
                "proposed_latitude and proposed_longitude must be set together"
            )

        return self


class VillageOut(BaseModel):
    id: str
    name: str
    district: str
    state: str
    lgd_code: str | None
    is_demo: bool
    source: str
    # Village centroid, when known. Additive/optional so existing consumers
    # of this schema (demo fixtures included) are unaffected; used only to
    # centre the "Select on Map" picker for the proposed business location
    # — never to change village_lgd, scoring or evidence calculations.
    latitude: float | None = None
    longitude: float | None = None


class AssessmentOut(BaseModel):
    id: str
    created_at: datetime
    status: str
    profile: ProfileCreate
    village: VillageOut
