from pathlib import Path

from .generator import DprLayoutError, generate_dpr
from .models import DprSessionData


def make_sample_dpr(
    out_path: str | Path = "artifacts/graminsetu_sample_dpr.pdf",
) -> str:
    from .sample import make_sample_dpr as generate_sample

    return generate_sample(out_path)


__all__ = [
    "DprLayoutError",
    "DprSessionData",
    "generate_dpr",
    "make_sample_dpr",
]