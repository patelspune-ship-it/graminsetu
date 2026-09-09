from pathlib import Path

import pytest
from pypdf import PdfReader

from app.dpr import generate_dpr, make_sample_dpr
from app.dpr.context import DISCLAIMER
from app.dpr.generator import DprLayoutError
from app.dpr.sample import sample_session


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    output = tmp_path_factory.mktemp("dpr") / "sample.pdf"
    result = make_sample_dpr(output)
    assert result == str(output.resolve())
    return output


def test_sample_is_exactly_eight_a4_pages(sample_pdf):
    reader = PdfReader(sample_pdf)

    assert len(reader.pages) == 8

    # These floats are PDF geometry, not financial values.
    for page in reader.pages:
        assert abs(float(page.mediabox.width) - 595.276) < 1
        assert abs(float(page.mediabox.height) - 841.890) < 1


def test_footer_is_present_on_every_page(sample_pdf):
    reader = PdfReader(sample_pdf)

    for number, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        assert f"Page {number} of 8" in text
        assert DISCLAIMER in text


def test_pdf_retains_financing_warning(sample_pdf):
    reader = PdfReader(sample_pdf)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "INFEASIBLE / UNVERIFIED FINANCING SCENARIO" in text
    assert "eligibility has not been verified" in text


def test_overflow_does_not_replace_existing_output(tmp_path, monkeypatch):
    from app.dpr import generator

    target = tmp_path / "existing.pdf"
    target.write_bytes(b"original-file")

    class TooManyPages:
        pages = [object()] * 9

    monkeypatch.setattr(
        generator.HTML,
        "render",
        lambda *args, **kwargs: TooManyPages(),
    )

    with pytest.raises(DprLayoutError):
        generate_dpr(sample_session(), target)

    assert target.read_bytes() == b"original-file"