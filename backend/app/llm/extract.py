import json

from app.llm.errors import LlmError
from app.llm.gemini_client import generate

_SKILL_VALUES = {
    "basic_machine_operation",
    "farming",
    "animal_husbandry",
    "tailoring",
    "retail_sales",
    "food_processing",
    "bookkeeping",
}

_PREMISES_VALUES = {"owned", "rented", "not_arranged"}
_POWER_VALUES = {"single_phase", "three_phase", "unavailable"}

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "own_capital_paise": {"type": "INTEGER", "nullable": True},
        "skills": {
            "type": "ARRAY",
            "nullable": True,
            "items": {"type": "STRING", "enum": sorted(_SKILL_VALUES)},
        },
        "premises": {
            "type": "STRING",
            "nullable": True,
            "enum": sorted(_PREMISES_VALUES),
        },
        "power": {
            "type": "STRING",
            "nullable": True,
            "enum": sorted(_POWER_VALUES),
        },
    },
    "required": ["own_capital_paise", "skills", "premises", "power"],
}

_SYSTEM_PROMPT = (
    "You extract a structured profile from free-form text written by a "
    "rural entrepreneur in Hindi, Marathi, English, or a mix of these.\n\n"
    "Extract exactly these fields:\n"
    "- own_capital_paise: the applicant's own available capital, "
    "converted to paise (1 rupee = 100 paise), as an integer. Only "
    "convert an amount the text explicitly states as money the applicant "
    "already has available; never guess or estimate an amount.\n"
    "- skills: a list drawn only from this fixed set: "
    "basic_machine_operation, farming, animal_husbandry, tailoring, "
    "retail_sales, food_processing, bookkeeping. Include a skill only if "
    "the text clearly describes the applicant having it.\n"
    "- premises: one of owned, rented, not_arranged. Set this only if the "
    "text explicitly describes the applicant's business premises "
    "situation.\n"
    "- power: one of single_phase, three_phase, unavailable. Set this "
    "only if the text explicitly describes electricity availability at "
    "the premises.\n\n"
    "STRICT RULES:\n"
    "- Return null for any field that is not explicitly stated in the "
    "text. Do not infer, guess, default, or invent a value.\n"
    "- Never invent numbers, skills, or facts that are not present in "
    "the text.\n"
    "- Respond with JSON only, matching the given schema."
)


def _clean_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    number = int(value)
    return number if number >= 0 else None


def _clean_skills(value) -> list[str] | None:
    if not isinstance(value, list):
        return None
    cleaned = [item for item in value if item in _SKILL_VALUES]
    return list(dict.fromkeys(cleaned)) or None


def _clean_enum(value, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def extract_profile(text: str) -> dict:
    """Extract structured profile fields from free-form text.

    Every field is null unless explicitly stated in the input; the model
    output is also defensively re-validated here so a malformed or
    invented value can never reach the caller.
    """
    raw = generate(
        _SYSTEM_PROMPT,
        text,
        response_mime_type="application/json",
        response_schema=_RESPONSE_SCHEMA,
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmError(f"Gemini returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise LlmError("Gemini did not return a JSON object")

    return {
        "own_capital_paise": _clean_int(data.get("own_capital_paise")),
        "skills": _clean_skills(data.get("skills")),
        "premises": _clean_enum(data.get("premises"), _PREMISES_VALUES),
        "power": _clean_enum(data.get("power"), _POWER_VALUES),
    }
