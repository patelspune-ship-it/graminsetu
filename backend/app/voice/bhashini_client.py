import base64

import httpx

from app.config import settings
from app.voice.errors import VoiceError

# MeitY's shared Bhashini ULCA pipeline. Callers only ever pass a source
# language; the config lookup below resolves it to the actual ASR/TTS
# service (and inference endpoint) currently backing that pipeline.
CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
PIPELINE_ID = "64392f96daac500b55c543cd"

SUPPORTED_LANGUAGES = {"mr", "hi", "en"}


def _require_config() -> tuple[str, str]:
    api_key = settings.bhashini_api_key
    user_id = settings.bhashini_user_id

    if not api_key or not user_id:
        raise VoiceError(
            "BHASHINI_API_KEY/BHASHINI_USER_ID are not configured"
        )

    return api_key, user_id


def _require_language(lang: str) -> str:
    if lang not in SUPPORTED_LANGUAGES:
        raise VoiceError(f"Unsupported language for Bhashini: {lang!r}")

    return lang


def _get_pipeline(task_type: str, lang: str, timeout: float) -> dict:
    api_key, user_id = _require_config()

    body = {
        "pipelineTasks": [
            {
                "taskType": task_type,
                "config": {"language": {"sourceLanguage": lang}},
            }
        ],
        "pipelineRequestConfig": {"pipelineId": PIPELINE_ID},
    }

    try:
        response = httpx.post(
            CONFIG_URL,
            headers={
                "userID": user_id,
                "ulcaApiKey": api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise VoiceError(
            f"Bhashini pipeline lookup failed: {exc}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise VoiceError(
            f"Bhashini pipeline lookup failed: {exc}"
        ) from exc


def _service_id(pipeline: dict, task_type: str) -> str:
    try:
        for entry in pipeline["pipelineResponseConfig"]:
            if entry["taskType"] == task_type:
                return entry["config"][0]["serviceId"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VoiceError(
            f"Bhashini pipeline response is missing a {task_type} service: {exc}"
        ) from exc

    raise VoiceError(f"Bhashini pipeline response has no {task_type} service")


def _compute(pipeline: dict, task_body: dict, timeout: float) -> dict:
    try:
        endpoint = pipeline["pipelineInferenceAPIEndPoint"]
        callback_url = endpoint["callbackUrl"]
        inference_key = endpoint["inferenceApiKey"]
        headers = {
            inference_key["name"]: inference_key["value"],
            "Content-Type": "application/json",
        }
    except (KeyError, TypeError) as exc:
        raise VoiceError(
            f"Bhashini pipeline response is missing an inference endpoint: {exc}"
        ) from exc

    try:
        response = httpx.post(
            callback_url, headers=headers, json=task_body, timeout=timeout
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise VoiceError(f"Bhashini inference request failed: {exc}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise VoiceError(f"Bhashini inference request failed: {exc}") from exc


def transcribe(audio_bytes: bytes, lang: str, *, timeout: float = 20.0) -> str:
    """Transcribe recorded speech via the Bhashini ASR pipeline.

    Raises VoiceError for any missing configuration, unsupported language,
    network, or response-shape failure, so callers have a single exception
    to handle and can never crash on an upstream surprise.
    """
    lang = _require_language(lang)

    if not audio_bytes:
        raise VoiceError("No audio was provided to transcribe")

    pipeline = _get_pipeline("asr", lang, timeout)
    service_id = _service_id(pipeline, "asr")

    task_body = {
        "pipelineTasks": [
            {
                "taskType": "asr",
                "config": {
                    "language": {"sourceLanguage": lang},
                    "serviceId": service_id,
                    "audioFormat": "wav",
                    "samplingRate": 16000,
                },
            }
        ],
        "inputData": {
            "audio": [
                {"audioContent": base64.b64encode(audio_bytes).decode("ascii")}
            ]
        },
    }

    result = _compute(pipeline, task_body, timeout)

    try:
        text = result["pipelineResponse"][0]["output"][0]["source"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VoiceError(f"Bhashini ASR response was malformed: {exc}") from exc

    if not isinstance(text, str) or not text.strip():
        raise VoiceError("Bhashini ASR returned no transcript")

    return text.strip()


def synthesize(text: str, lang: str, *, timeout: float = 20.0) -> bytes:
    """Synthesize speech via the Bhashini TTS pipeline.

    Raises VoiceError for any missing configuration, unsupported language,
    network, or response-shape failure, so callers have a single exception
    to handle and can never crash on an upstream surprise.
    """
    lang = _require_language(lang)

    if not text.strip():
        raise VoiceError("No text was provided to synthesize")

    pipeline = _get_pipeline("tts", lang, timeout)
    service_id = _service_id(pipeline, "tts")

    task_body = {
        "pipelineTasks": [
            {
                "taskType": "tts",
                "config": {
                    "language": {"sourceLanguage": lang},
                    "serviceId": service_id,
                    "gender": "female",
                    "audioFormat": "wav",
                    "samplingRate": 8000,
                },
            }
        ],
        "inputData": {"input": [{"source": text}]},
    }

    result = _compute(pipeline, task_body, timeout)

    try:
        audio_b64 = result["pipelineResponse"][0]["audio"][0]["audioContent"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VoiceError(f"Bhashini TTS response was malformed: {exc}") from exc

    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise VoiceError(f"Bhashini TTS returned invalid audio data: {exc}") from exc

    if not audio_bytes:
        raise VoiceError("Bhashini TTS returned empty audio")

    return audio_bytes
