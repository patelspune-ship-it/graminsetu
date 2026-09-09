import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from geoalchemy2.elements import WKTElement
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.db import Base, engine
from app.data.models import Dataset, ViabilityIndex

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"

DISTRICTS = {
    "Nashik": (19.3, 73.3, 20.9, 74.9),
    "Jalgaon": (20.3, 74.6, 21.3, 76.3),
}

# Serialize ingestion/precompute writers. This also prevents an ingestion
# invalidation racing with a precompute job.
PIPELINE_LOCK = 71624031


def initialize_database():
    # Register all existing application models as well.
    from app import models  # noqa: F401
    from app.data import models as data_models  # noqa: F401

    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

    Base.metadata.create_all(engine)


def lock_pipeline(session):
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": PIPELINE_LOCK},
    )


def invalidate_index(session):
    # A change in either district can affect cross-boundary catchments.
    session.query(ViabilityIndex).delete(synchronize_session=False)


def digest(*parts: bytes) -> str:
    hasher = hashlib.sha256()

    for part in parts:
        # Length prefix prevents concatenation ambiguity.
        hasher.update(len(part).to_bytes(8, "big"))
        hasher.update(part)

    return hasher.hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def file_bytes(path: Path | None) -> bytes:
    return path.read_bytes() if path else b""


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def point_wkt(longitude: float, latitude: float):
    return WKTElement(
        f"POINT({longitude} {latitude})",
        srid=4326,
    )


def load_boundary(path: Path):
    """
    Accepts a geometry, Feature, or FeatureCollection.

    Coordinates must be WGS84 longitude/latitude.
    The file must contain only the intended district polygon(s).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))

    if raw.get("type") == "FeatureCollection":
        geometries = [
            shape(feature["geometry"])
            for feature in raw["features"]
            if feature.get("geometry")
        ]
    elif raw.get("type") == "Feature":
        geometries = [shape(raw["geometry"])]
    else:
        geometries = [shape(raw)]

    if not geometries:
        raise ValueError(f"{path}: no boundary geometries found")

    boundary = unary_union(geometries)

    if boundary.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"{path}: expected Polygon or MultiPolygon")

    if boundary.is_empty or not boundary.is_valid:
        raise ValueError(f"{path}: boundary is empty or invalid")

    min_x, min_y, max_x, max_y = boundary.bounds

    if not (
        -180 <= min_x <= max_x <= 180
        and -90 <= min_y <= max_y <= 90
    ):
        raise ValueError(f"{path}: coordinates are not WGS84 lon/lat")

    return boundary


def inside_boundary(boundary, longitude: float, latitude: float) -> bool:
    return boundary.covers(Point(longitude, latitude))


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()

    # Preserve letters, digits, combining marks and whitespace.
    # Do not remove Bk/Kh, directions or settlement qualifiers.
    value = "".join(
        character
        if unicodedata.category(character)[0] in {"L", "N", "M"}
        else " "
        for character in value
    )

    return " ".join(value.split())


def normalize_header(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def resolve_columns(
    headers: list[str],
    aliases: dict[str, list[str]],
    required: set[str],
    explicit: dict[str, str] | None = None,
) -> dict[str, str]:
    explicit = explicit or {}

    if len(headers) != len(set(headers)):
        raise ValueError("CSV contains duplicate column headers")

    resolved = {}

    for canonical, candidates in aliases.items():
        if canonical in explicit:
            wanted = normalize_header(explicit[canonical])
            matches = [
                header for header in headers
                if normalize_header(header) == wanted
            ]
        else:
            allowed = {normalize_header(name) for name in candidates}
            matches = [
                header for header in headers
                if normalize_header(header) in allowed
            ]

        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous column for '{canonical}': {matches}. "
                "Use --columns JSON to choose the intended column."
            )

        if matches:
            resolved[canonical] = matches[0]
        elif canonical in required or canonical in explicit:
            raise ValueError(
                f"Missing required column '{canonical}'. "
                f"Accepted aliases: {candidates}. "
                f"Available columns: {headers}"
            )

    unknown = set(explicit) - set(aliases)
    if unknown:
        raise ValueError(f"Unknown explicit column keys: {sorted(unknown)}")

    return resolved


def read_csv(path: Path, encoding: str = "utf-8-sig"):
    with path.open("r", encoding=encoding, newline="") as handle:
        sample = handle.read(65536)
        handle.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(handle, dialect=dialect)

        if not reader.fieldnames:
            raise ValueError(f"{path}: CSV has no header")

        headers = list(reader.fieldnames)
        rows = []

        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(
                    f"{path}:{line_number}: more values than column headers"
                )

            if not any((value or "").strip() for value in row.values()):
                continue

            rows.append((line_number, row))

    return headers, rows


def required_text(row, column: str, path: Path, line: int) -> str:
    value = (row.get(column) or "").strip()

    if not value:
        raise ValueError(f"{path}:{line}: blank required value in '{column}'")

    return value


def integer_cell(value: str, label: str) -> int:
    value = value.strip()

    # Accept plain integers, western grouping or Indian grouping.
    valid = (
        re.fullmatch(r"\d+", value)
        or re.fullmatch(r"\d{1,3}(,\d{3})+", value)
        or re.fullmatch(r"\d{1,2}(,\d{2})*,\d{3}", value)
    )

    if not valid:
        raise ValueError(f"{label}: expected non-negative integer, got {value!r}")

    return int(value.replace(",", ""))


def code_cell(value: str, label: str, census: bool = False) -> str:
    value = value.strip()

    if not re.fullmatch(r"\d{1,12}", value):
        raise ValueError(
            f"{label}: expected digit-only code, got {value!r}. "
            "Do not supply Excel decimal/scientific notation."
        )

    if int(value) == 0:
        raise ValueError(f"{label}: zero is not a valid village code")

    if census:
        if len(value) > 6:
            raise ValueError(f"{label}: expected a Census village code <=6 digits")
        return value.zfill(6)

    # LGD codes are stored canonically without leading zeroes.
    return str(int(value))


def save_dataset(session, dataset_id: str, fingerprint: str, details: dict):
    statement = insert(Dataset).values(
        id=dataset_id,
        fingerprint=fingerprint,
        details=details,
    )

    session.execute(
        statement.on_conflict_do_update(
            index_elements=[Dataset.id],
            set_={
                "fingerprint": statement.excluded.fingerprint,
                "details": statement.excluded.details,
                "imported_at": text("now()"),
            },
        )
    )


def dataset_signature(session) -> str:
    rows = session.execute(
        select(Dataset.id, Dataset.fingerprint).order_by(Dataset.id)
    ).all()

    return digest(json_bytes([list(row) for row in rows]))