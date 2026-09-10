import httpx

from app.config import settings
from app.llm.errors import LlmError

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)


def generate(
    system_prompt: str,
    user_prompt: str,
    *,
    response_mime_type: str | None = None,
    response_schema: dict | None = None,
    timeout: float = 20.0,
) -> str:
    """Call the Gemini API and return the raw text of the first candidate.

    Raises LlmError for any missing configuration, network, or response
    shape failure, so callers have a single exception to handle.
    """
    api_key = settings.gemini_api_key
    if not api_key:
        raise LlmError("GEMINI_API_KEY is not configured")

    generation_config: dict = {"temperature": 0}
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type
    if response_schema:
        generation_config["responseSchema"] = response_schema

    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": generation_config,
    }

    try:
        response = httpx.post(
            GEMINI_URL,
            params={"key": api_key},
            json=body,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmError(f"Gemini request failed: {exc}") from exc
