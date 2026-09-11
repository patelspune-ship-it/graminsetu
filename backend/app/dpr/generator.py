import os
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from weasyprint import CSS, HTML, default_url_fetcher
from weasyprint.text.fonts import FontConfiguration

from .context import DISCLAIMER, build_context
from .financials import calculate_financials
from .formatting import (
    bps_percent,
    fraction_ratio,
    indian_currency,
    known,
)
from .models import DprSessionData


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_FONT_DIR = Path("/usr/share/fonts/truetype/noto")


class DprLayoutError(ValueError):
    pass


def template_environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
    )
    env.filters.update(
        inr=indian_currency,
        bps=bps_percent,
        ratio=fraction_ratio,
        known=known,
    )
    return env


def font_paths() -> tuple[Path, Path]:
    # Optional deployment override: directory with these two font files.
    root = Path(os.environ.get("DPR_FONT_DIR", str(DEFAULT_FONT_DIR)))
    paths = (
        (root / "NotoSans-Regular.ttf").resolve(),
        (root / "NotoSansDevanagari-Regular.ttf").resolve(),
    )

    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(
                f"Required DPR font missing: {path}. "
                "Install fonts-noto-core or set DPR_FONT_DIR."
            )

    return paths


def render_html(data: DprSessionData) -> str:
    snapshot = calculate_financials(data)
    context = build_context(data, snapshot)
    return template_environment().get_template("report.html").render(**context)


def generate_dpr(
    session_data: DprSessionData | dict,
    out_path: str | Path,
) -> str:
    if isinstance(session_data, DprSessionData):
        # Revalidate, including mutable lists/nested data.
        data = DprSessionData.model_validate(session_data.model_dump())
    else:
        data = DprSessionData.model_validate(session_data)

    html_text = render_html(data)
    latin_font, marathi_font = font_paths()
    allowed_urls = {
        latin_font.as_uri(),
        marathi_font.as_uri(),
    }

    def local_font_fetcher(url: str, *args, **kwargs):
        if url not in allowed_urls:
            raise ValueError(f"External DPR resource is not allowed: {url}")
        return default_url_fetcher(url, *args, **kwargs)

    # CSS is application-owned; no user text is interpolated into it.
    css_env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=False,
        undefined=StrictUndefined,
    )
    css_text = css_env.get_template("report.css").render(
        latin_font_uri=latin_font.as_uri(),
        marathi_font_uri=marathi_font.as_uri(),
        disclaimer=DISCLAIMER,
    )

    fonts = FontConfiguration()

    stylesheet = CSS(
        string=css_text,
        font_config=fonts,
        url_fetcher=local_font_fetcher,
    )
    document = HTML(
        string=html_text,
        url_fetcher=local_font_fetcher,
    ).render(
        stylesheets=[stylesheet],
        font_config=fonts,
    )

    if len(document.pages) != 9:
        raise DprLayoutError(
            f"Expected exactly 9 A4 pages; rendered {len(document.pages)}. "
            "Reduce narrative length or revise the layout. "
            "No content was truncated and the output file was not replaced."
        )

    for number, page in enumerate(document.pages, start=1):
        if f"section-{number}" not in page.anchors:
            raise DprLayoutError(
                f"Section {number} does not start on physical page {number}"
            )

    target = Path(out_path).expanduser().resolve()
    if target.suffix.lower() != ".pdf":
        raise ValueError("out_path must end with .pdf")

    target.parent.mkdir(parents=True, exist_ok=True)

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.stem}-",
            suffix=".pdf",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)

        document.write_pdf(target=str(temporary))
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return str(target)