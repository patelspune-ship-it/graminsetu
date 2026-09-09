import argparse
from collections import Counter
from fractions import Fraction
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.archetypes import ARCHETYPES
from app.db import engine
from app.data.common import (
    dataset_signature,
    digest,
    initialize_database,
    json_bytes,
    lock_pipeline,
    read_csv,
    resolve_columns,
)
from app.data.models import Dataset, Village, ViabilityIndex
from app.fin.core import round_half_up
from app.viability.cached import serialize_subscore
from app.viability.scoring import SubScore, WEIGHTS_BPS, median


FEATURE_QUERY = text("""
SELECT
    v.village_lgd,
    v.district,
    v.population,

    (
        SELECT COUNT(DISTINCT (p.osm_type, p.osm_id))
        FROM osm_pois p
        WHERE p.category = ANY(CAST(:categories AS text[]))
          AND ST_DWithin(p.geom, v.geom, :radius_m)
    ) AS competitor_count,

    (
        SELECT COALESCE(SUM(n.population), 0)
        FROM villages n
        WHERE n.geom IS NOT NULL
          AND ST_DWithin(n.geom, v.geom, :radius_m)
    ) AS catchment_population_proxy,

    (
        SELECT ST_Distance(p.geom, v.geom)
        FROM osm_pois p
        WHERE p.category = 'bank'
        ORDER BY p.geom <-> v.geom
        LIMIT 1
    ) AS nearest_mapped_bank_m

FROM villages v
WHERE v.geom IS NOT NULL
ORDER BY v.district, v.village_lgd
""")


def midrank_lookup(values: list[int]) -> dict[int, Fraction]:
    counts = Counter(values)
    total = len(values)

    if total == 0:
        return {}

    less = 0
    result = {}

    for value in sorted(counts):
        equal = counts[value]
        result[value] = Fraction(2 * less + equal, 2 * total)
        less += equal

    return result


def load_reviews(path: Path | None) -> dict[tuple[str, str], dict]:
    if path is None:
        return {}

    headers, rows = read_csv(path)

    aliases = {
        "village_lgd": ["village_lgd", "lgd village code"],
        "archetype_id": ["archetype_id", "archetype"],
        "competition_coverage_verified": [
            "competition_coverage_verified"
        ],
        "population_proxy_accepted": ["population_proxy_accepted"],
    }

    columns = resolve_columns(
        headers,
        aliases,
        required=set(aliases),
    )

    reviews = {}

    for line, row in rows:
        values = {
            key: (row.get(column) or "").strip()
            for key, column in columns.items()
        }

        key = (
            values["village_lgd"],
            values["archetype_id"],
        )

        if not key[0] or key[1] not in ARCHETYPES:
            raise ValueError(f"{path}:{line}: invalid village/archetype key")

        if key in reviews:
            raise ValueError(f"{path}:{line}: duplicate review key {key}")

        review = {}

        for field in (
            "competition_coverage_verified",
            "population_proxy_accepted",
        ):
            value = values[field].casefold()

            if value not in {"true", "false"}:
                raise ValueError(
                    f"{path}:{line}:{field}: expected true or false"
                )

            review[field] = value == "true"

        reviews[key] = review

    return reviews


def make_model_signature(reviews: dict) -> str:
    source_paths = [
        Path(__file__),
        Path(__file__).resolve().parents[1] / "viability" / "scoring.py",
        Path(__file__).resolve().parents[1] / "viability" / "cached.py",
    ]

    return digest(
        *(path.read_bytes() for path in source_paths),
        json_bytes({
            key: archetype.model_dump()
            for key, archetype in ARCHETYPES.items()
        }),
        json_bytes([
            [list(key), value]
            for key, value in sorted(reviews.items())
        ]),
    )


def precompute(review_path: Path | None):
    reviews = load_reviews(review_path)
    model_hash = make_model_signature(reviews)

    with Session(engine) as session, session.begin():
        lock_pipeline(session)

        datasets = {
            item.id: item
            for item in session.scalars(select(Dataset)).all()
        }

        villages = session.scalars(
            select(Village).order_by(Village.village_lgd)
        ).all()

        if not villages:
            raise ValueError("No Census villages imported")

        known_ids = {village.village_lgd for village in villages}

        unknown_reviews = {
            lgd for lgd, _ in reviews
            if lgd not in known_ids
        }

        if unknown_reviews:
            raise ValueError(
                f"Coverage review contains unknown LGD codes: "
                f"{sorted(unknown_reviews)[:10]}"
            )

        district_villages = {}

        for village in villages:
            district_villages.setdefault(village.district, []).append(village)

        for district in district_villages:
            osm = datasets.get(f"osm:{district}")
            census = datasets.get(f"census:{district}")

            if osm is None or census is None:
                raise ValueError(
                    f"{district}: OSM and Census imports are both required"
                )

            if census.details["osm_fingerprint_used"] != osm.fingerprint:
                raise ValueError(
                    f"{district}: OSM changed after Census matching. "
                    "Rerun the Census loader before precomputing."
                )

        data_hash = dataset_signature(session)

        population_ranks = {
            district: midrank_lookup([
                village.population
                for village in district_rows
                if village.population > 0
            ])
            for district, district_rows in district_villages.items()
        }

        geocoded_counts = {
            district: sum(
                village.latitude is not None
                and village.longitude is not None
                for village in district_rows
            )
            for district, district_rows in district_villages.items()
        }

        # Upsert current pairs, then remove pairs no longer generated.
        current_pairs = set()
        total_written = 0

        for archetype_id, archetype in ARCHETYPES.items():
            rows = session.execute(
                FEATURE_QUERY,
                {
                    "categories": archetype.competition_categories,
                    "radius_m": archetype.catchment_m,
                },
            ).mappings().all()

            density_references = {}

            for row in rows:
                population = int(row["catchment_population_proxy"])

                if population > 0:
                    density_references.setdefault(
                        row["district"], []
                    ).append(
                        Fraction(
                            int(row["competitor_count"]) * 1_000,
                            population,
                        )
                    )

            medians = {
                district: median(values)
                for district, values in density_references.items()
                if values
            }

            records = []

            for row in rows:
                lgd = row["village_lgd"]
                district = row["district"]

                competitors = int(row["competitor_count"])
                catchment_population = int(
                    row["catchment_population_proxy"]
                )
                district_median = medians.get(district)
                review = reviews.get((lgd, archetype_id), {})

                market = None

                if not review.get("competition_coverage_verified", False):
                    market_note = (
                        "Mapped POIs counted, but category coverage has "
                        "not been reviewed. No competitor-absence inference."
                    )
                elif not review.get("population_proxy_accepted", False):
                    market_note = (
                        "Catchment population proxy has not been reviewed; "
                        "unmatched villages or boundary effects may undercount it."
                    )
                elif not catchment_population or not district_median:
                    market_note = (
                        "Missing/zero catchment population or zero district "
                        "median density; relative market gap is undefined."
                    )
                else:
                    local_density = Fraction(
                        competitors * 1_000,
                        catchment_population,
                    )

                    market = max(
                        Fraction(0),
                        min(
                            Fraction(1),
                            1 - local_density / district_median,
                        ),
                    )

                    market_note = (
                        f"{competitors} mapped competitors within "
                        f"{archetype.catchment_m} m. Density uses a "
                        "reviewed representative-point population proxy, "
                        "not an exact catchment population."
                    )

                population = int(row["population"])
                demand = population_ranks[district].get(population)

                scores = [
                    SubScore(
                        "market_gap",
                        WEIGHTS_BPS["market_gap"],
                        market,
                        market_note,
                    ),
                    SubScore(
                        "demand",
                        WEIGHTS_BPS["demand"],
                        demand,
                        (
                            "Census 2011 village-population midrank within "
                            "the imported district village dataset. "
                            "Not a purchasing-power estimate."
                        ),
                    ),
                    SubScore(
                        "inputs",
                        WEIGHTS_BPS["inputs"],
                        (
                            Fraction(1)
                            if not archetype.inputs_required
                            else None
                        ),
                        (
                            "Not crop-input constrained in this archetype; "
                            "non-crop procurement remains unverified."
                            if not archetype.inputs_required
                            else
                            "No comparable crop catchment dataset loaded. "
                            "OSM and Census population cannot supply crop acreage."
                        ),
                    ),
                    SubScore(
                        "infrastructure",
                        WEIGHTS_BPS["infrastructure"],
                        None,
                        (
                            "Nearest mapped bank is available as a feature. "
                            "Verified mandi, road and power inputs are missing."
                        ),
                    ),
                ]

                known_weight = sum(
                    score.weight_bps for score in scores
                    if score.value is not None
                )

                known_contribution = round_half_up(sum(
                    (
                        score.weight_bps * score.value
                        for score in scores
                        if score.value is not None
                    ),
                    start=Fraction(0),
                ))

                warnings = [
                    "OSM data completeness is not established by POI count.",
                    "Census population is from 2011.",
                    "Name-matched OSM coordinates are provisional.",
                    "Catchment population sums geocoded village representative "
                    "points; missing villages and unloaded neighbouring areas "
                    "can undercount population.",
                    "Mapped business density is a proxy, not a demand forecast.",
                    "Geographic cache excludes applicant-specific skills and capital.",
                ]

                if (
                    len(district_villages[district])
                    != geocoded_counts[district]
                ):
                    warnings.append(
                        f"{geocoded_counts[district]} of "
                        f"{len(district_villages[district])} imported villages "
                        "in this district have matched coordinates."
                    )

                bank_distance = row["nearest_mapped_bank_m"]

                records.append({
                    "village_lgd": lgd,
                    "archetype_id": archetype_id,
                    "geographic_scores": [
                        serialize_subscore(score) for score in scores
                    ],
                    "features": {
                        "catchment_m": archetype.catchment_m,
                        "mapped_competitors": competitors,
                        "catchment_population_proxy": catchment_population,
                        "village_population_2011": population,
                        "nearest_mapped_bank_m": (
                            round(bank_distance)
                            if bank_distance is not None else None
                        ),
                        "bank_distance_method": (
                            "PostGIS geography distance to representative point"
                        ),
                        "district_reference_catchments": len(
                            density_references.get(district, [])
                        ),
                        "district_median_density_per_1000": (
                            {
                                "numerator": district_median.numerator,
                                "denominator": district_median.denominator,
                            }
                            if district_median is not None else None
                        ),
                        "review_flags": review,
                    },
                    "warnings": warnings,
                    "known_contribution_bps": known_contribution,
                    "known_weight_bps": known_weight,
                    "dataset_signature": data_hash,
                    "model_signature": model_hash,
                })

                current_pairs.add((lgd, archetype_id))

            for start in range(0, len(records), 500):
                statement = insert(ViabilityIndex).values(
                    records[start:start + 500]
                )

                update_fields = {
                    column: getattr(statement.excluded, column)
                    for column in (
                        "geographic_scores",
                        "features",
                        "warnings",
                        "known_contribution_bps",
                        "known_weight_bps",
                        "dataset_signature",
                        "model_signature",
                    )
                }
                update_fields["computed_at"] = text("now()")

                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[
                            ViabilityIndex.village_lgd,
                            ViabilityIndex.archetype_id,
                        ],
                        set_=update_fields,
                    )
                )

            total_written += len(records)
            print(f"{archetype_id}: {len(records)} indexed villages")

        existing = session.execute(
            select(
                ViabilityIndex.village_lgd,
                ViabilityIndex.archetype_id,
            )
        ).all()

        for lgd, archetype_id in existing:
            if (lgd, archetype_id) not in current_pairs:
                session.execute(
                    ViabilityIndex.__table__.delete().where(
                        ViabilityIndex.village_lgd == lgd,
                        ViabilityIndex.archetype_id == archetype_id,
                    )
                )

    print(f"Committed {total_written} village × archetype rows.")
    print("Unmatched villages remain in villages but are not spatially indexed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-review", type=Path)
    args = parser.parse_args()

    initialize_database()
    precompute(args.coverage_review)


if __name__ == "__main__":
    main()