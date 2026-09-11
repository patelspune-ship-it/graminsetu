class LlmError(Exception):
    """Raised when the LLM backend cannot produce a usable result."""


class LlmRateLimitedError(LlmError):
    """Raised specifically for a 429 from the LLM backend (quota/rate
    limit), so callers can tell "temporarily out of quota" apart from a
    configuration or network failure and say so explicitly instead of a
    generic "unavailable"."""
