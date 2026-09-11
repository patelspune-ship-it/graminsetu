from pathlib import Path

import pytest
from pypdf import PdfReader

from app.dpr import generate_dpr, make_sample_dpr
from app.dpr.context import DISCLAIMER
from app.dpr.generator import DprLayoutError
from app.dpr.models import DprSessionData
from app.dpr.sample import sample_session


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    output = tmp_path_factory.mktemp("dpr") / "sample.pdf"
    result = make_sample_dpr(output)
    assert result == str(output.resolve())
    return output


def test_sample_is_exactly_nine_a4_pages(sample_pdf):
    reader = PdfReader(sample_pdf)

    assert len(reader.pages) == 9

    # These floats are PDF geometry, not financial values.
    for page in reader.pages:
        assert abs(float(page.mediabox.width) - 595.276) < 1
        assert abs(float(page.mediabox.height) - 841.890) < 1


def test_footer_is_present_on_every_page(sample_pdf):
    reader = PdfReader(sample_pdf)

    for number, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        assert f"Page {number} of 9" in text
        assert DISCLAIMER in text


def test_pdf_retains_financing_warning(sample_pdf):
    reader = PdfReader(sample_pdf)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "INFEASIBLE / UNVERIFIED FINANCING SCENARIO" in text
    assert "eligibility has not been verified" in text


def test_sample_pdf_contains_quarterly_and_opex_sections(sample_pdf):
    reader = PdfReader(sample_pdf)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Quarterly repayment schedule" in text
    assert "Operational costs breakdown" in text
    assert "TOTAL MONTHLY OPERATING COST" in text


def _render_ps_scheme_pdf(tmp_path, available_for_project_paise):
    payload = sample_session().model_dump()
    payload["assumptions"]["cost_model"] = "ps_scheme"
    payload["promoter"]["available_for_project_paise"] = (
        available_for_project_paise
    )
    data = DprSessionData.model_validate(payload)

    target = tmp_path / "ps_scheme.pdf"
    generate_dpr(data, target)
    return target


def test_ps_scheme_micro_finance_pdf_shows_derivation_and_scheme(tmp_path):
    target = _render_ps_scheme_pdf(tmp_path, 1_000_000)
    reader = PdfReader(target)

    assert len(reader.pages) == 9

    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Micro Finance Scheme" in text
    assert "margin" in text.lower()
    assert "routed to" in text.lower()


def test_ps_scheme_term_loan_pdf_fits_fixed_page_count(tmp_path):
    # 84-month tenure: the complete monthly ledger no longer fits page 7,
    # so it is replaced by a reference to the quarterly schedule.
    target = _render_ps_scheme_pdf(tmp_path, 10_000_000)
    reader = PdfReader(target)

    assert len(reader.pages) == 9

    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Term Loan Scheme" in text
    assert "exceeds this report" in text


def test_overflow_does_not_replace_existing_output(tmp_path, monkeypatch):
    from app.dpr import generator

    target = tmp_path / "existing.pdf"
    target.write_bytes(b"original-file")

    class TooManyPages:
        pages = [object()] * 10

    monkeypatch.setattr(
        generator.HTML,
        "render",
        lambda *args, **kwargs: TooManyPages(),
    )

    with pytest.raises(DprLayoutError):
        generate_dpr(sample_session(), target)

    assert target.read_bytes() == b"original-file"