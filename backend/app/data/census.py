import argparse
import csv
import io
import json
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db import engine
from app.data.common import (
    DATA_DIR,
    DISTRICTS,
    atomic_write,
    code_cell,
    digest,
    file_bytes,
    initialize_database,
    integer_cell,
    invalidate_index,
    json_bytes,
    lock_pipeline,
    normalize_name,
    point_wkt,
    read_csv,
    required_text,
    resolve_columns,
    save_dataset,
)
from app.data.models import Dataset, OsmPlace, Village


COLUMN_ALIASES = {
    "village_name": [
        "village_name",
        "village name",
        "name of village",
        "town village name",
        "town/village name",
        "area name",
    ],
    "district": [
        "district",
        "district name",
        "district_name",
        "name of district",
    ],
    "population": [
        "population",
        "total population",
        "total_population",
        "population total",
        "tot_p",
        "p_tot",
    ],
    "village_lgd": [
        "village_lgd",
        "lgd village code",
        "lgd_village_code",
        "village lgd code",
        "lgd code",
    ],
    "census_code": [
        "census_code",
        "census village code",
        "census 2011 village code",
        "census 2011 code",
        "town/village code",
        "town village code",
    ],
    "households": [
        "households",
        "number of households",
        "no of households",
        "no_hh",
        "total households",
    ],
    "workers": [
        "workers",
        "total workers",
        "total_workers",
        "tot_work_p",
    ],
}

DISTRICT_NAMES = {
    "nashik": "Nashik",
    "nasik": "Nashik",
    "नाशिक": "Nashik",
    "jalgaon": "Jalgaon",
    "जळगाव": "Jalgaon",
}


def district_name(value: str) -> str | None:
    return DISTRICT_NAMES.get(normalize_name(value))


def load_crosswalk(path: Path, encoding: str) -> dict[str, str]:
    headers, rows = read_csv(path, encoding)

    aliases = {
        "census_code": COLUMN_ALIASES["census_code"],
        "village_lgd": COLUMN_ALIASES["village_lgd"],
    }

    columns = resolve_columns(
        headers,
        aliases,
        required={"census_code", "village_lgd"},
    )

    output = {}
    used_lgd = set()

    for line, row in rows:
        census = code_cell(
            required_text(row, columns["census_code"], path, line),
            f"{path}:{line}:census_code",
            census=True,
        )
        lgd = code_cell(
            required_text(row, columns["village_lgd"], path, line),
            f"{path}:{line}:village_lgd",
        )

        # Do not guess how to allocate population across village
        # splits/mergers. MVP requires a reviewed one-to-one crosswalk.
        if census in output or lgd in used_lgd:
            raise ValueError(
                f"{path}:{line}: crosswalk is not one-to-one. "
                "Review Census/LGD splits or mergers explicitly."
            )

        output[census] = lgd
        used_lgd.add(lgd)

    return output


def load_village_rows(
    path: Path,
    district: str,
    encoding: str = "utf-8-sig",
    crosswalk_path: Path | None = None,
    columns_path: Path | None = None,
):
    headers, raw_rows = read_csv(path, encoding)

    explicit = (
        json.loads(columns_path.read_text(encoding="utf-8"))
        if columns_path
        else {}
    )

    columns = resolve_columns(
        headers,
        COLUMN_ALIASES,
        required={"village_name", "district", "population"},
        explicit=explicit,
    )

    crosswalk = (
        load_crosswalk(crosswalk_path, encoding)
        if crosswalk_path
        else None
    )

    if "village_lgd" not in columns:
        if crosswalk is None:
            raise ValueError(
                "Missing required column 'village_lgd'. "
                "Census village codes are not LGD codes. "
                "Supply an explicit LGD column or --crosswalk."
            )

        if "census_code" not in columns:
            raise ValueError(
                "Missing required column 'census_code': "
                "needed to join the supplied Census-to-LGD crosswalk. "
                f"Accepted aliases: {COLUMN_ALIASES['census_code']}"
            )

    output = []
    seen_lgd = set()
    seen_census = set()

    for line, row in raw_rows:
        raw_district = required_text(
            row, columns["district"], path, line
        )
        canonical_district = district_name(raw_district)

        if canonical_district != district:
            continue

        name = required_text(
            row, columns["village_name"], path, line
        )

        population = integer_cell(
            required_text(row, columns["population"], path, line),
            f"{path}:{line}:population",
        )

        census = None

        if "census_code" in columns:
            census = code_cell(
                required_text(row, columns["census_code"], path, line),
                f"{path}:{line}:census_code",
                census=True,
            )

        if "village_lgd" in columns:
            lgd = code_cell(
                required_text(row, columns["village_lgd"], path, line),
                f"{path}:{line}:village_lgd",
            )

            if crosswalk is not None and census:
                mapped = crosswalk.get(census)
                if mapped is None or mapped != lgd:
                    raise ValueError(
                        f"{path}:{line}: LGD value disagrees with "
                        "or is missing from the supplied crosswalk"
                    )
        else:
            lgd = crosswalk.get(census)

            if lgd is None:
                raise ValueError(
                    f"{path}:{line}: Census code {census} has no LGD "
                    "crosswalk entry; no code was invented"
                )

        if lgd in seen_lgd:
            raise ValueError(
                f"{path}:{line}: duplicate LGD village {lgd}. "
                "Check whether the CSV includes totals, towns or duplicate rows."
            )

        if census and census in seen_census:
            raise ValueError(
                f"{path}:{line}: duplicate Census village code {census}"
            )

        seen_lgd.add(lgd)
        if census:
            seen_census.add(census)

        optional = {}

        for field in ("households", "workers"):
            optional[field] = (
                integer_cell(
                    required_text(row, columns[field], path, line),
                    f"{path}:{line}:{field}",
                )
                if field in columns
                else None
            )

        if optional["workers"] is not None and optional["workers"] > population:
            raise ValueError(
                f"{path}:{line}: workers exceed population; "
                "check that the correct columns were selected"
            )

        output.append({
            "village_lgd": lgd,
            "census_code": census,
            "name": name,
            "district": district,
            "state": "Maharashtra",
            "population": population,
            **optional,
            "source_line": line,
        })

    if not output:
        raise ValueError(
            f"{path}: no village records selected for {district}. "
            "Check the district-name column and aliases. "
            "Numeric district codes are not district names."
        )

    return output, columns


def choose_match(
    name: str,
    candidates: list[dict],
    threshold: float = 90,
    minimum_gap: float = 8,
):
    query = normalize_name(name)

    if not query:
        return None, "empty_normalized_name", None, None

    ranked = []

    for candidate in candidates:
        score = max(
            (
                fuzz.ratio(query, alias)
                for alias in candidate["normalized_names"]
                if alias
            ),
            default=0,
        )
        ranked.append((score, candidate["osm_id"], candidate))

    ranked.sort(key=lambda item: (-item[0], item[1]))

    if not ranked:
        return None, "no_place_candidates", None, None

    best_score, _, best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0

    if best_score < threshold:
        return None, "below_threshold", best_score, best

    if len(ranked) > 1 and best_score - second_score < minimum_gap:
        return None, "ambiguous_candidates", best_score, best

    return best, "matched", best_score, best


def match_rows(rows, candidates, threshold, minimum_gap):
    proposals = []

    for row in rows:
        match, status, score, candidate = choose_match(
            row["name"], candidates, threshold, minimum_gap
        )

        proposals.append({
            "row": row,
            "match": match,
            "status": status,
            "score": score,
            "candidate": candidate,
        })

    assignments = Counter(
        proposal["match"]["osm_id"]
        for proposal in proposals
        if proposal["match"] is not None
    )

    # Do not let two Census villages silently share one place node.
    for proposal in proposals:
        match = proposal["match"]

        if match and assignments[match["osm_id"]] > 1:
            proposal["match"] = None
            proposal["status"] = "place_assigned_to_multiple_villages"

    return proposals


def report_bytes(proposals, unmatched_only=False) -> bytes:
    buffer = io.StringIO(newline="")

    columns = [
        "village_lgd",
        "census_code",
        "village_name",
        "status",
        "match_score",
        "candidate_osm_id",
        "candidate_names",
    ]

    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()

    for proposal in proposals:
        if unmatched_only and proposal["match"] is not None:
            continue

        row = proposal["row"]
        candidate = proposal["candidate"]

        writer.writerow({
            "village_lgd": row["village_lgd"],
            "census_code": row["census_code"],
            "village_name": row["name"],
            "status": proposal["status"],
            "match_score": proposal["score"],
            "candidate_osm_id": candidate["osm_id"] if candidate else "",
            "candidate_names": (
                " | ".join(candidate["names"]) if candidate else ""
            ),
        })

    return buffer.getvalue().encode("utf-8")


def import_census(args):
    rows, resolved_columns = load_village_rows(
        path=args.csv,
        district=args.district,
        encoding=args.encoding,
        crosswalk_path=args.crosswalk,
        columns_path=args.columns,
    )

    with Session(engine) as session, session.begin():
        lock_pipeline(session)

        osm_dataset = session.get(Dataset, f"osm:{args.district}")

        if osm_dataset is None:
            raise ValueError(
                f"Import OSM for {args.district} before matching Census villages"
            )

        places = session.scalars(
            select(OsmPlace).where(
                OsmPlace.district == args.district
            )
        ).all()

        candidates = [
            {
                "osm_id": place.osm_id,
                "names": place.names,
                "normalized_names": [
                    normalize_name(name) for name in place.names
                ],
                "latitude": place.latitude,
                "longitude": place.longitude,
            }
            for place in places
        ]

        proposals = match_rows(
            rows,
            candidates,
            args.threshold,
            args.minimum_gap,
        )

        fingerprint = digest(
            args.csv.read_bytes(),
            file_bytes(args.crosswalk),
            file_bytes(args.columns),
            osm_dataset.fingerprint.encode(),
            json_bytes({
                "threshold": args.threshold,
                "minimum_gap": args.minimum_gap,
                "encoding": args.encoding,
            }),
            Path(__file__).read_bytes(),
        )

        imported = []

        for proposal in proposals:
            original = proposal["row"]
            match = proposal["match"]

            row = {
                key: value
                for key, value in original.items()
                if key != "source_line"
            }

            row.update({
                "latitude": match["latitude"] if match else None,
                "longitude": match["longitude"] if match else None,
                "geom": (
                    point_wkt(match["longitude"], match["latitude"])
                    if match else None
                ),
                "coordinate_method": (
                    "osm_place_name_match"
                    if match else proposal["status"]
                ),
                "coordinate_match_score": (
                    proposal["score"] if match else None
                ),
                "provenance": {
                    "census_year": 2011,
                    "csv": str(args.csv),
                    "csv_line": original["source_line"],
                    "resolved_columns": resolved_columns,
                    "crosswalk": (
                        str(args.crosswalk) if args.crosswalk else None
                    ),
                    "osm_place_id": match["osm_id"] if match else None,
                    "osm_dataset_fingerprint": osm_dataset.fingerprint,
                    "coordinates_verified_manually": False,
                    "missing_optional_fields": [
                        field for field in ("households", "workers")
                        if field not in resolved_columns
                    ],
                },
            })

            imported.append(row)

        ids = [row["village_lgd"] for row in imported]

        collisions = session.execute(
            select(Village.village_lgd, Village.district).where(
                Village.village_lgd.in_(ids),
                Village.district != args.district,
            )
        ).all()

        if collisions:
            raise ValueError(
                f"LGD codes already belong to another imported district: "
                f"{collisions[:10]}"
            )

        invalidate_index(session)

        session.execute(
            delete(Village).where(Village.district == args.district)
        )

        for start in range(0, len(imported), 500):
            session.execute(
                insert(Village),
                imported[start:start + 500],
            )

        matched = sum(
            proposal["match"] is not None
            for proposal in proposals
        )

        save_dataset(
            session,
            f"census:{args.district}",
            fingerprint,
            {
                "csv": str(args.csv),
                "village_count": len(imported),
                "matched_count": matched,
                "population_year": 2011,
                "resolved_columns": resolved_columns,
                "osm_fingerprint_used": osm_dataset.fingerprint,
                "coordinate_method": "district-scoped fuzzy OSM place match",
            },
        )

    reports = DATA_DIR / "reports"
    prefix = args.district.lower()

    atomic_write(
        reports / f"{prefix}_village_matches.csv",
        report_bytes(proposals),
    )
    atomic_write(
        reports / f"{prefix}_unmatched_villages.csv",
        report_bytes(proposals, unmatched_only=True),
    )

    print(
        f"{args.district}: {matched}/{len(imported)} matched "
        f"({matched / len(imported):.1%})."
    )
    print(f"Unmatched report: {reports / f'{prefix}_unmatched_villages.csv'}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--district", choices=DISTRICTS, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path)
    parser.add_argument("--columns", type=Path)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--threshold", type=float, default=90)
    parser.add_argument("--minimum-gap", type=float, default=8)
    args = parser.parse_args()

    if not 0 <= args.threshold <= 100:
        parser.error("--threshold must be between 0 and 100")

    if not 0 <= args.minimum_gap <= 100:
        parser.error("--minimum-gap must be between 0 and 100")

    initialize_database()
    import_census(args)


if __name__ == "__main__":
    main()