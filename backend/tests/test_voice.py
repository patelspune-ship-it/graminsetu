import base64

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api_errors import install_error_handlers
from app.routers import voice as voice_router
from app.voice import VoiceError, synthesize, transcribe
from app.voice.bhashini_client import CONFIG_URL


def _pipeline_response(task_type: str, service_id: str = "svc-1") -> dict:
    return {
        "pipelineResponseConfig": [
            {"taskType": task_type, "config": [{"serviceId": service_id}]}
        ],
        "pipelineInferenceAPIEndPoint": {
            "callbackUrl": "https://inference.example/compute",
            "inferenceApiKey": {"name": "Authorization", "value": "infer-key"},
        },
    }


def _json_response(url: str, payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code, json=payload, request=httpx.Request("POST", url)
    )


@pytest.fixture(autouse=True)
def bhashini_config(monkeypatch):
    monkeypatch.setattr(
        "app.voice.bhashini_client.settings.bhashini_api_key", "test-key"
    )
    monkeypatch.setattr(
        "app.voice.bhashini_client.settings.bhashini_user_id", "test-user"
    )


def test_transcribe_returns_text_on_success(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        if url == CONFIG_URL:
            return _json_response(url, _pipeline_response("asr"))

        return _json_response(
            url,
            {"pipelineResponse": [{"taskType": "asr", "output": [{"source": "नमस्कार"}]}]},
        )

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    result = transcribe(b"fake-audio-bytes", "mr")

    assert result == "नमस्कार"


def test_transcribe_raises_without_config(monkeypatch):
    monkeypatch.setattr("app.voice.bhashini_client.settings.bhashini_api_key", None)

    def fake_post(*args, **kwargs):
        raise AssertionError("must not call the network without config")

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    with pytest.raises(VoiceError):
        transcribe(b"fake-audio-bytes", "hi")


def test_transcribe_rejects_unsupported_language():
    with pytest.raises(VoiceError):
        transcribe(b"fake-audio-bytes", "fr")


def test_transcribe_rejects_empty_audio():
    with pytest.raises(VoiceError):
        transcribe(b"", "en")


def test_transcribe_raises_on_network_failure(monkeypatch):
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError(
            "connection refused", request=httpx.Request("POST", CONFIG_URL)
        )

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    with pytest.raises(VoiceError):
        transcribe(b"fake-audio-bytes", "en")


def test_transcribe_raises_on_auth_failure(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _json_response(url, {"message": "invalid key"}, status_code=401)

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    with pytest.raises(VoiceError):
        transcribe(b"fake-audio-bytes", "en")


def test_transcribe_raises_on_quota_exceeded(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _json_response(url, {"message": "quota exceeded"}, status_code=429)

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    with pytest.raises(VoiceError):
        transcribe(b"fake-audio-bytes", "en")


def test_transcribe_raises_on_malformed_response(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        if url == CONFIG_URL:
            return _json_response(url, _pipeline_response("asr"))

        return _json_response(url, {"unexpected": "shape"})

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    with pytest.raises(VoiceError):
        transcribe(b"fake-audio-bytes", "en")


def test_transcribe_raises_on_blank_transcript(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        if url == CONFIG_URL:
            return _json_response(url, _pipeline_response("asr"))

        return _json_response(
            url,
            {"pipelineResponse": [{"taskType": "asr", "output": [{"source": "   "}]}]},
        )

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    with pytest.raises(VoiceError):
        transcribe(b"fake-audio-bytes", "en")


def test_synthesize_returns_audio_bytes_on_success(monkeypatch):
    audio_bytes = b"RIFF....WAVEfmt "
    encoded = base64.b64encode(audio_bytes).decode("ascii")

    def fake_post(url, headers=None, json=None, timeout=None):
        if url == CONFIG_URL:
            return _json_response(url, _pipeline_response("tts"))

        return _json_response(
            url,
            {
                "pipelineResponse": [
                    {"taskType": "tts", "audio": [{"audioContent": encoded}]}
                ]
            },
        )

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    result = synthesize("Hello there", "en")

    assert result == audio_bytes


def test_synthesize_rejects_empty_text():
    with pytest.raises(VoiceError):
        synthesize("   ", "en")


def test_synthesize_raises_on_missing_service_for_task(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        # Pipeline lookup succeeds but has no "tts" entry.
        return _json_response(url, _pipeline_response("asr"))

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    with pytest.raises(VoiceError):
        synthesize("Hello", "en")


def test_synthesize_raises_on_invalid_audio_payload(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        if url == CONFIG_URL:
            return _json_response(url, _pipeline_response("tts"))

        return _json_response(
            url,
            {
                "pipelineResponse": [
                    {"taskType": "tts", "audio": [{"audioContent": "not-base64!!"}]}
                ]
            },
        )

    monkeypatch.setattr("app.voice.bhashini_client.httpx.post", fake_post)

    with pytest.raises(VoiceError):
        synthesize("Hello", "en")


@pytest.fixture
def client():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(voice_router.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_transcribe_endpoint_returns_transcript_on_success(client, monkeypatch):
    monkeypatch.setattr(voice_router, "transcribe", lambda audio, lang: "hello world")

    response = client.post(
        "/api/voice/transcribe",
        json={"audio_base64": base64.b64encode(b"abc").decode(), "lang": "en"},
    )

    assert response.status_code == 200
    assert response.json() == {"transcript": "hello world"}


def test_transcribe_endpoint_returns_400_on_invalid_base64(client):
    response = client.post(
        "/api/voice/transcribe",
        json={"audio_base64": "not valid base64!!", "lang": "en"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_AUDIO"


def test_transcribe_endpoint_returns_502_when_voice_unavailable(client, monkeypatch):
    def failing(audio, lang):
        raise VoiceError("boom")

    monkeypatch.setattr(voice_router, "transcribe", failing)

    response = client.post(
        "/api/voice/transcribe",
        json={"audio_base64": base64.b64encode(b"abc").decode(), "lang": "mr"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "VOICE_UNAVAILABLE"


def test_transcribe_endpoint_never_crashes_on_unexpected_failure(client, monkeypatch):
    def failing(audio, lang):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(voice_router, "transcribe", failing)

    response = client.post(
        "/api/voice/transcribe",
        json={"audio_base64": base64.b64encode(b"abc").decode(), "lang": "en"},
    )

    assert response.status_code == 500


def test_speak_endpoint_returns_audio_on_success(client, monkeypatch):
    monkeypatch.setattr(voice_router, "synthesize", lambda text, lang: b"audio-bytes")

    response = client.post(
        "/api/voice/speak", json={"text": "Hello", "lang": "hi"}
    )

    assert response.status_code == 200
    assert response.content == b"audio-bytes"
    assert response.headers["content-type"] == "audio/wav"


def test_speak_endpoint_returns_502_when_voice_unavailable(client, monkeypatch):
    def failing(text, lang):
        raise VoiceError("boom")

    monkeypatch.setattr(voice_router, "synthesize", failing)

    response = client.post(
        "/api/voice/speak", json={"text": "Hello", "lang": "en"}
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "VOICE_UNAVAILABLE"


def test_speak_endpoint_rejects_unknown_language(client):
    response = client.post(
        "/api/voice/speak", json={"text": "Hello", "lang": "fr"}
    )

    assert response.status_code == 422
