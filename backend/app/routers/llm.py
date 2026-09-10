import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.api_errors import ApiError
from app.llm import LlmError, explain_result, extract_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["LLM"])


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    computed_data: dict
    lang: Literal["en", "hi", "mr"] = "en"


class ExplainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str


class ExtractProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


class ExtractProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    own_capital_paise: int | None = None
    skills: list[str] | None = None
    premises: str | None = None
    power: str | None = None


def _unavailable(exc: Exception) -> ApiError:
    logger.warning("LLM request failed: %s", exc)
    return ApiError(
        502,
        "LLM_UNAVAILABLE",
        "The language assistant is unavailable right now. Try again later.",
    )


@router.post("/explain", response_model=ExplainResponse)
def explain(payload: ExplainRequest):
    try:
        text = explain_result(payload.computed_data, payload.lang)
    except LlmError as exc:
        raise _unavailable(exc) from None

    return ExplainResponse(explanation=text)


@router.post("/extract-profile", response_model=ExtractProfileResponse)
def extract(payload: ExtractProfileRequest):
    try:
        fields = extract_profile(payload.text)
    except LlmError as exc:
        raise _unavailable(exc) from None

    return ExtractProfileResponse(**fields)
