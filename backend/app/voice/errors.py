class VoiceError(Exception):
    """Raised when the Bhashini voice backend cannot produce a usable
    result (missing configuration, auth, quota, network, or a malformed
    response). Callers map this to a single clean failure; the voice
    layer must never crash the request."""
