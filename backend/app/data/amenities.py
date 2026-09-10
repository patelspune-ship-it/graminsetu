import argparse
import csv
from glob import glob
from pathlib import Path

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.data.common import (
    BACKEND_DIR,
    DATA_DIR,
    DISTRICTS,
    digest,
    initialize_database,
    invalidate_index,
    lock_pipeline,
    save_dataset,
)
from app.data.models import Village
from app.db import engine

RAW_DIR = DATA_DIR / "raw"

EXPECTED_COLUMN_COUNT = 396
MATCH_RATE_THRESHOLD = 0.80

# Government District Census Handbook layout is fixed-column; a change in
# column count or these anchor labels means the layout has shifted and
# every other hardcoded index below would silently read the wrong field.
ANCHOR_COLUMNS = {
    3: "District Name",
    6: "Village Code",
    7: "Village Name",
}

DISTANCE_LABELS = {"a": "<5km", "b": "5-10km", "c": "10km+"}

# (status column, distance-code column), 0-indexed.
FACILITY_COLUMNS = {
    "national_highway": (293, 294),
    "state_highway": (295, 296),
    "major_district_road": (297, 298),
    "black_topped": (301, 302),
    "gravel": (303, 304),
    "all_weather": (307, 308),
    "atm": (313, 314),
    "commercial_bank": (315, 316),
    "cooperative_bank": (317, 318),
    "agricultural_credit_society": (319, 320),
    "shg": (321, 322),
    "pds_shop": (323, 324),
    "mandis_regular_market": (325, 326),
    "weekly_haat": (327, 328),
    "agricultural_marketing_society": (329, 330),
    "csc": (267, 268),
}

# (status column, summer-hours column, winter-hours column).
POWER_COLUMNS = {
    "domestic": (357, 358, 359),
    "agriculture": (360, 361, 362),
    "commercial": (363, 364, 365),
}

CROP_COLUMNS = {"first": 369, "second": 372, "third": 375}

LAND_COLUMNS = {
    "net_area_sown_ha": 386,
    "total_unirrigated_ha": 387,
    "area_irrigated_ha": 388,
}

NEAREST_TOWN_NAME_COLUMN = 394
NEAREST_TOWN_DISTANCE_COLUMN = 395


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(BACKEND_DIR))
    except ValueError:
        return str(path)


def resolve_csv_path(district: str, raw_dir: Path = RAW_DIR) -> Path:
    pattern = str(
        raw_dir / f"DCHB_Village_Amenities-Maharashtra-{district}-*.csv"
    )
    matches = sorted(glob(pattern))

    if not matches:
        raise ValueError(f"No amenities CSV found matching {pattern}")

    if len(matches) > 1:
        raise ValueError(
            f"Multiple amenities CSVs match {pattern}, expected exactly one: "
            f"{matches}"
        )

    return Path(matches[0])


def clean_village_code(raw: str) -> str:
    """Strip the Excel text-artifact leading apostrophe and whitespace.

    Does not raise on an unexpected shape: a code that still doesn't match
    a known village_lgd simply counts against the match rate, which is the
    actual fail-loud gate.
    """
    value = (raw or "").strip().lstrip("'").strip()
    return str(int(value)) if value.isdigit() else value


def parse_status(raw: str) -> bool | None:
    value = (raw or "").strip()
    if value == "1":
        return True
    if value == "2":
        return False
    return None


def parse_distance_code(raw: str) -> str | None:
    value = (raw or "").strip().lower()
    return value if value in DISTANCE_LABELS else None


def parse_hours(raw: str) -> int | None:
    value = (raw or "").strip()
    if not value or value.upper() == "NA":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_number(raw: str) -> float | None:
    value = (raw or "").strip()
    if not value or value.upper() == "NA":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_text(raw: str) -> str | None:
    value = (raw or "").strip()
    if not value or value.upper() == "NA":
        return None
    return value


def decode_facility(status_raw: str, distance_raw: str) -> dict:
    distance_code = parse_distance_code(distance_raw)

    return {
        "available": parse_status(status_raw),
        "raw_status": (status_raw or "").strip() or None,
        "distance_code": distance_code,
        "distance_range_km": DISTANCE_LABELS.get(distance_code),
    }


def decode_power(status_raw: str, summer_raw: str, winter_raw: str) -> dict:
    return {
        "available": parse_status(status_raw),
        "raw_status": (status_raw or "").strip() or None,
        "hours_summer": parse_hours(summer_raw),
        "hours_winter": parse_hours(winter_raw),
    }


def parse_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))

    if len(header) != EXPECTED_COLUMN_COUNT:
        raise ValueError(
            f"{path}: expected {EXPECTED_COLUMN_COUNT} columns, "
            f"found {len(header)}. The Village Directory layout may have changed."
        )

    for index, label in ANCHOR_COLUMNS.items():
        if header[index].strip() != label:
            raise ValueError(
                f"{path}: expected column {index} to be {label!r}, "
                f"found {header[index]!r}. The Village Directory layout "
                "may have changed; hardcoded column indices are unsafe."
            )

    return header


def parse_rows(path: Path) -> list[tuple[int, list[str]]]:
    parse_header(path)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)

        return [
            (line, row)
            for line, row in enumerate(reader, start=2)
            if any(cell.strip() for cell in row)
        ]


def build_amenities(row: list[str], path: Path, line: int) -> dict:
    def facility(name: str) -> dict:
        status_col, distance_col = FACILITY_COLUMNS[name]
        return decode_facility(row[status_col], row[distance_col])

    def power(name: str) -> dict:
        status_col, summer_col, winter_col = POWER_COLUMNS[name]
        return decode_power(row[status_col], row[summer_col], row[winter_col])

    return {
        "power": {name: power(name) for name in POWER_COLUMNS},
        "roads": {
            name: facility(name)
            for name in (
                "black_topped",
                "gravel",
                "all_weather",
                "national_highway",
                "state_highway",
                "major_district_road",
            )
        },
        "finance": {
            name: facility(name)
            for name in (
                "commercial_bank",
                "cooperative_bank",
                "atm",
                "agricultural_credit_society",
                "shg",
            )
        },
        "markets": {
            name: facility(name)
            for name in (
                "mandis_regular_market",
                "weekly_haat",
                "agricultural_marketing_society",
                "pds_shop",
            )
        },
        "crops": {
            "agricultural_commodities": {
                key: parse_text(row[column])
                for key, column in CROP_COLUMNS.items()
            },
        },
        "land": {
            key: parse_number(row[column])
            for key, column in LAND_COLUMNS.items()
        },
        "connectivity": {
            "nearest_town_name": parse_text(row[NEAREST_TOWN_NAME_COLUMN]),
            "nearest_town_distance_km": parse_number(
                row[NEAREST_TOWN_DISTANCE_COLUMN]
            ),
            "csc": facility("csc"),
        },
        "source": {
            "csv": _relative_path(path),
            "csv_line": line,
        },
    }


def ensure_amenities_column(session) -> None:
    # Additive schema change: adds the column without rewriting the table.
    session.execute(
        text("ALTER TABLE villages ADD COLUMN IF NOT EXISTS village_amenities JSONB")
    )


def load_amenities(district: str) -> None:
    if district not in DISTRICTS:
        raise ValueError(
            f"Unknown district {district!r}; expected one of {sorted(DISTRICTS)}"
        )

    path = resolve_csv_path(district)
    rows = parse_rows(path)

    if not rows:
        raise ValueError(f"{path}: no data rows found")

    fingerprint = digest(path.read_bytes(), Path(__file__).read_bytes())

    with Session(engine) as session, session.begin():
        lock_pipeline(session)
        ensure_amenities_column(session)

        known_lgds = {
            lgd
            for (lgd,) in session.execute(
                select(Village.village_lgd).where(Village.district == district)
            ).all()
        }

        if not known_lgds:
            raise ValueError(
                f"No imported villages found for {district}. "
                "Run the Census loader before loading amenities."
            )

        updates = []
        unmatched_examples = []

        for line, row in rows:
            village_lgd = clean_village_code(row[6])

            if village_lgd not in known_lgds:
                if len(unmatched_examples) < 10:
                    unmatched_examples.append(
                        {"line": line, "raw_code": row[6], "name": row[7]}
                    )
                continue

            updates.append({
                "village_lgd": village_lgd,
                "village_amenities": build_amenities(row, path, line),
            })

        total = len(rows)
        matched = len(updates)
        match_rate = matched / total

        print(
            f"{district}: matched {matched}/{total} Village Directory rows "
            f"to imported villages ({match_rate:.1%})."
        )

        if match_rate < MATCH_RATE_THRESHOLD:
            raise ValueError(
                f"{district}: amenities match rate {match_rate:.1%} is below "
                f"the {MATCH_RATE_THRESHOLD:.0%} threshold. Refusing to write "
                f"partial/null data. Unmatched examples: {unmatched_examples}"
            )

        for start in range(0, len(updates), 500):
            session.execute(update(Village), updates[start:start + 500])

        invalidate_index(session)

        save_dataset(
            session,
            f"amenities:{district}",
            fingerprint,
            {
                "csv": _relative_path(path),
                "rows": total,
                "matched": matched,
                "match_rate": match_rate,
                "unmatched_examples": unmatched_examples,
            },
        )

    print(f"{district}: wrote village_amenities for {matched} villages.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--district", choices=DISTRICTS, required=True)
    args = parser.parse_args()

    initialize_database()
    load_amenities(args.district)


if __name__ == "__main__":
    main()
