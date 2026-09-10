import json

from app.llm.errors import LlmError
from app.llm.gemini_client import generate

_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
}

_SYSTEM_PROMPT = (
    "You are a plain-language explainer inside a rural entrepreneurship "
    "advisory tool. You will be given a JSON object of already-computed "
    "financial and viability figures. Your only job is to restate these "
    "exact numbers in clear, simple {language} for a first-time small "
    "business applicant.\n\n"
    "STRICT RULES:\n"
    "- Only use numbers, labels and values that are already present in "
    "the JSON data given to you below.\n"
    "- Never calculate, estimate, infer, round differently, total up, or "
    "add any number that is not already present in the data.\n"
    "- Never invent figures, percentages, comparisons or facts that are "
    "not in the data.\n"
    "- If a field is null, missing, or marked unknown, say plainly that "
    "it is unknown or not available instead of guessing.\n"
    "- Do not give financial, legal or investment advice, and do not "
    "state or imply loan approval or rejection.\n"
    "- Write only in {language}, in short plain sentences suitable for "
    "someone reading a financial summary for the first time."
)


def explain_result(computed_data: dict, lang: str) -> str:
    """Restate already-computed figures in plain language.

    The model is instructed to only restate the numbers it is given; it
    must never calculate, infer, or add new figures.
    """
    language = _LANGUAGE_NAMES.get(lang, _LANGUAGE_NAMES["en"])
    system_prompt = _SYSTEM_PROMPT.format(language=language)

    user_prompt = (
        "Here is the computed data, as JSON. Restate only what is in it, "
        "in " + language + ":\n\n"
        + json.dumps(computed_data, ensure_ascii=False, default=str)
    )

    text = generate(system_prompt, user_prompt).strip()
    if not text:
        raise LlmError("Gemini returned an empty explanation")
    return text
