import base64
import binascii
import logging
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api_errors import ApiError
from app.voice import VoiceError, synthesize, transcribe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["Voice"])


class TranscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Base64-encoded audio, not a multipart upload, so this endpoint stays
    # a plain JSON request like the rest of this API.
    audio_base64: str = Field(min_length=1)
    lang: Literal["mr", "hi", "en"] = "en"


class TranscribeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str


class SpeakRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    lang: Literal["mr", "hi", "en"] = "en"


def _unavailable(exc: Exception) -> ApiError:
    logger.warning("Voice request failed: %s", exc)

    return ApiError(
        502,
        "VOICE_UNAVAILABLE",
        "The voice assistant is unavailable right now. Try again later, "
        "or use text instead.",
    )


@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe_endpoint(payload: TranscribeRequest):
    try:
        audio_bytes = base64.b64decode(payload.audio_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(
            400, "INVALID_AUDIO", "audio_base64 is not valid base64 data."
        ) from None

    try:
        text = transcribe(audio_bytes, payload.lang)
    except VoiceError as exc:
        raise _unavailable(exc) from None

    return TranscribeResponse(transcript=text)


@router.post("/speak")
def speak_endpoint(payload: SpeakRequest):
    try:
        audio_bytes = synthesize(payload.text, payload.lang)
    except VoiceError as exc:
        raise _unavailable(exc) from None

    return Response(content=audio_bytes, media_type="audio/wav")
