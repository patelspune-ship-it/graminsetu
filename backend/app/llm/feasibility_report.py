"""
Hyper-Local Business Feasibility Report.

Generates six narrative sections for a promoter-facing feasibility
report. This module NEVER computes a new figure. Every number, distance,
population, price, or month name that can appear in its output must
already exist in the ``village_data`` / ``archetype`` /
``computed_financials`` given to it — those are assembled elsewhere
(app.viability, app.fin, the Village Directory import) from
already-computed, already-verified sources.

Five of the six sections are written by an LLM call, constrained to a
JSON schema and a "facts" payload containing only pre-formatted,
already-computed values; a post-generation check rejects any output
containing a number that was not in that payload. The sixth section,
competitor_mapping, never goes through the LLM at all — it is a direct,
verbatim pass-through of the already-computed market_gap sub-score and
its note, so the LLM cannot restate, round, or embellish it.

Import direction: this module may depend on app.archetypes (schema
only) and app.llm.*. It must never be imported by app.fin or
app.viability — those must stay usable, and testable, without any LLM
dependency.
"""

import json
import re
from fractions import Fraction

from app.archetypes.schema import Archetype
from app.llm.errors import LlmError
from app.llm.gemini_client import generate

_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
}

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_SEASONALITY_AVERAGE_BPS = 10_000

_DISTRIBUTION_CHANNEL_HINTS = {
    "agri_processing": [
        "direct sale to the milling/processing customer at the unit",
        "local haat/weekly market stalls",
        "tie-ups with nearby kirana stores",
    ],
    "retail": [
        "walk-in retail at the unit",
        "local haat/weekly market stalls",
        "informal delivery to nearby households",
    ],
}
_DEFAULT_DISTRIBUTION_CHANNELS = [
    "direct sale at the unit",
    "local haat/weekly market stalls",
    "nearby kirana/retail tie-ups",
]


_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "market_reach": {"type": "STRING"},
        "opportunity_analysis": {"type": "STRING"},
        "swot": {
            "type": "OBJECT",
            "properties": {
                "strengths": {"type": "STRING"},
                "weaknesses": {"type": "STRING"},
                "opportunities": {"type": "STRING"},
                "threats": {"type": "STRING"},
            },
            "required": ["strengths", "weaknesses", "opportunities", "threats"],
        },
        "threats": {"type": "STRING"},
        "product_market_value": {"type": "STRING"},
    },
    "required": [
        "market_reach",
        "opportunity_analysis",
        "swot",
        "threats",
        "product_market_value",
    ],
}

_SYSTEM_PROMPT = (
    "You are a narrative writer inside a rural-enterprise advisory tool. "
    "You will be given a JSON object called FACTS, containing values that "
    "have already been computed, measured or looked up by other systems "
    "— never by you. Your only job is to weave these exact facts into "
    "readable prose, in {language}, across five report sections.\n\n"
    "STRICT RULES:\n"
    "- Every number, distance, population figure, price, percentage, "
    "count, or month name in your output must already appear in FACTS. "
    "Never calculate, estimate, round differently, convert units, total "
    "up, average, or invent any number that is not already there.\n"
    "- If a fact is null, missing, or an empty list, say plainly in that "
    "section that the evidence is absent for that point. Never guess or "
    "speculate a plausible-sounding value or name in its place.\n"
    "- Do not give financial, legal or investment advice, and do not "
    "assert loan approval, eligibility, or guaranteed demand.\n"
    "- Write only in {language}, in short plain sentences. Keep every "
    "section to 2-3 sentences, well under 500 characters.\n\n"
    "SECTIONS TO WRITE:\n"
    "- market_reach: state the catchment population and catchment radius "
    "from FACTS, name the nearest town and its distance from FACTS (or "
    "say it is not known if null), and suggest plausible distribution "
    "channels for this type of business from the channel list given in "
    "FACTS — general business knowledge, not a new claim about this "
    "specific village.\n"
    "- opportunity_analysis: using the reported crops and amenity facts "
    "given, describe underserved niches for this business type. State "
    "explicitly which parts of this analysis have no supporting "
    "evidence in FACTS.\n"
    "- swot: four short paragraphs — strengths, weaknesses, "
    "opportunities, threats — each explicitly referencing the given "
    "project cost and the applicant's own capital from FACTS.\n"
    "- threats: cover three things — supply chain bottlenecks (using "
    "the archetype's required inputs from FACTS), seasonal demand "
    "(name only the low-season months already listed in FACTS, do not "
    "compute or guess others), and single-buyer dependency risk "
    "(general business risk, not a new fact about this village).\n"
    "- product_market_value: pricing guidance using the given price per "
    "unit and the given population percentile from FACTS as a "
    "purchasing-power indicator."
)

_NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _digit_tokens(text: str) -> set[str]:
    tokens = set()
    for match in _NUMBER_PATTERN.finditer(text):
        cleaned = match.group().replace(",", "")
        if cleaned.strip("."):
            tokens.add(cleaned)
    return tokens


def _assert_numbers_are_grounded(generated: dict, facts: dict) -> None:
    """Reject any generated number absent from the facts given to the LLM.

    Single-digit tokens are excluded: they are common as prose (list
    counts, "a few") rather than the invented-figure risk this guards
    against. Anything with two or more digits must already be present,
    verbatim (after stripping thousands separators), in the FACTS JSON.
    """
    allowed = _digit_tokens(json.dumps(facts, ensure_ascii=False, default=str))
    generated_text = json.dumps(generated, ensure_ascii=False, default=str)
    found = _digit_tokens(generated_text)

    suspicious = sorted(
        token for token in found
        if len(token.replace(".", "")) >= 2 and token not in allowed
    )

    if suspicious:
        raise LlmError(
            "Feasibility report narrative contained numbers not present "
            f"in the supplied facts: {suspicious}"
        )


def _low_season_months(seasonality_bps: list[int]) -> list[str]:
    return [
        _MONTH_NAMES[index]
        for index, value in enumerate(seasonality_bps)
        if value < _SEASONALITY_AVERAGE_BPS
    ]


def _rupees(paise: int | None) -> str | None:
    if paise is None:
        return None
    sign = "-" if paise < 0 else ""
    rupees, remainder = divmod(abs(paise), 100)
    suffix = f".{remainder:02d}" if remainder else ""
    return f"{sign}₹{rupees:,}{suffix}"


def _percent_from_bps(bps: int | None) -> str | None:
    if bps is None:
        return None
    whole, frac = divmod(bps, 100)
    return f"{whole}.{frac:02d}%"


def _percent_from_ratio(value: dict | None) -> str | None:
    if value is None:
        return None
    ratio = Fraction(value["numerator"], value["denominator"])
    scaled = round(ratio * 100)
    return f"{scaled}%"


def _distribution_channels(category: str) -> list[str]:
    return _DISTRIBUTION_CHANNEL_HINTS.get(category, _DEFAULT_DISTRIBUTION_CHANNELS)


def _build_facts(
    village_data: dict,
    archetype: Archetype,
    computed_financials: dict,
) -> dict:
    return {
        "village_name": village_data.get("name"),
        "district": village_data.get("district"),
        "state": village_data.get("state"),
        "archetype_name": archetype.name_en,
        "archetype_category": archetype.category,
        "catchment_radius_metres": archetype.catchment_m,
        "catchment_population": village_data.get("catchment_population_proxy"),
        "nearest_town_name": village_data.get("nearest_town_name"),
        "nearest_town_distance_km": village_data.get("nearest_town_distance_km"),
        "plausible_distribution_channels": _distribution_channels(
            archetype.category
        ),
        "reported_crops": village_data.get("reported_crops") or [],
        "reported_amenities": village_data.get("reported_amenities") or [],
        "required_inputs": archetype.inputs_required,
        "low_season_months": _low_season_months(archetype.seasonality_bps),
        "project_cost": _rupees(computed_financials.get("project_cost_paise")),
        "applicant_own_capital": _rupees(
            computed_financials.get("available_for_project_paise")
        ),
        "price_per_unit": _rupees(archetype.unit_economics.revenue_per_unit_paise),
        "unit_label": archetype.unit_economics.unit_label,
        "population_percentile": _percent_from_bps(
            computed_financials.get("population_percentile_bps")
        ),
    }


def _competitor_mapping(market_gap_sub_score: dict | None) -> dict:
    """Verbatim pass-through — never touched by the LLM."""
    if market_gap_sub_score is None:
        return {
            "value_percent": None,
            "note": (
                "No market-gap evidence has been computed for this "
                "village/archetype pair."
            ),
        }

    return {
        "value_percent": _percent_from_ratio(market_gap_sub_score.get("value")),
        "note": market_gap_sub_score.get("note"),
    }


def generate_feasibility_report(
    village_data: dict,
    archetype: Archetype,
    computed_financials: dict,
    lang: str,
) -> dict:
    """Generate the six-section Hyper-Local Business Feasibility Report.

    Consumes only already-computed data; produces narrative only.

    village_data: {
        "name", "district", "state": str
        "catchment_population_proxy": int | None
        "nearest_town_name": str | None
        "nearest_town_distance_km": number | None
        "reported_crops": list[str] | None
        "reported_amenities": list[str] | None
    }
    computed_financials: {
        "project_cost_paise": int
        "available_for_project_paise": int
        "population_percentile_bps": int | None   (0..10000)
        "market_gap_sub_score": dict | None        (app.viability.cached.serialize_subscore output)
    }

    Returns a dict with exactly six keys: market_reach,
    opportunity_analysis, swot, threats, competitor_mapping,
    product_market_value.
    """
    language = _LANGUAGE_NAMES.get(lang, _LANGUAGE_NAMES["en"])
    facts = _build_facts(village_data, archetype, computed_financials)

    raw = generate(
        _SYSTEM_PROMPT.format(language=language),
        "FACTS:\n" + json.dumps(facts, ensure_ascii=False, default=str),
        response_mime_type="application/json",
        response_schema=_RESPONSE_SCHEMA,
    )

    try:
        generated = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmError(f"Gemini returned invalid JSON: {exc}") from exc

    if not isinstance(generated, dict):
        raise LlmError("Gemini did not return a JSON object")

    missing = [key for key in _RESPONSE_SCHEMA["required"] if key not in generated]
    if missing:
        raise LlmError(f"Gemini response missing sections: {missing}")

    swot = generated.get("swot")
    swot_keys = {"strengths", "weaknesses", "opportunities", "threats"}
    if not isinstance(swot, dict) or set(swot) != swot_keys:
        raise LlmError("Gemini response's swot section has an unexpected shape")

    _assert_numbers_are_grounded(generated, facts)

    return {
        "market_reach": generated["market_reach"],
        "opportunity_analysis": generated["opportunity_analysis"],
        "swot": generated["swot"],
        "threats": generated["threats"],
        "competitor_mapping": _competitor_mapping(
            computed_financials.get("market_gap_sub_score")
        ),
        "product_market_value": generated["product_market_value"],
    }
