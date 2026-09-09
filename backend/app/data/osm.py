import argparse
import json
import math
import random
import time
from pathlib import Path

import httpx
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.db import engine
from app.data.common import (
    DATA_DIR,
    DISTRICTS,
    atomic_write,
    digest,
    initialize_database,
    inside_boundary,
    invalidate_index,
    json_bytes,
    load_boundary,
    lock_pipeline,
    point_wkt,
    save_dataset,
)
from app.data.models import OsmPlace, OsmPoi


# Editable, first-match-wins normalization.
# Each rule contains AND conditions; rules within a category are OR.
#
# Category names intentionally match the six archetype configs where
# the OSM tag actually supports that interpretation.
CATEGORY_RULES = {
    "dairy_collection": [
        {"industrial": "dairy_collection"},
        {"amenity": "milk_collection"},
        {"produce": "milk", "industrial": "collection"},
    ],
    "flour_mill": [
        {"craft": "flour_mill"},
        {"industrial": "flour_mill"},
        {"industrial": "mill", "product": "flour"},
        {"man_made": "mill", "product": "flour"},
    ],
    "dal_mill": [
        {"industrial": "dal_mill"},
        {"craft": "dal_mill"},
        {"industrial": "mill", "product": "dal"},
    ],
    "grain_processing": [
        {"industrial": "grain_processing"},
        {"industrial": "mill", "product": "grain"},
    ],
    "tailor": [
        {"shop": "tailor"},
        {"craft": "tailor"},
        {"craft": "dressmaker"},
    ],
    "agri_storage": [
        {"industrial": "agricultural_storage"},
        {"warehouse": "agricultural"},
        {"storage": "onion"},
        {"storage": "grain"},
    ],
    "cold_storage": [
        {"industrial": "cold_storage"},
        {"warehouse": "cold_storage"},
    ],
    "warehouse": [
        {"building": "warehouse"},
        {"industrial": "warehouse"},
    ],
    "grocery": [
        {"shop": "grocery"},
        {"shop": "general"},
        {"shop": "supermarket"},
    ],
    "convenience": [
        {"shop": "convenience"},
    ],
    "bank": [
        {"amenity": "bank"},
    ],
    "marketplace": [
        {"amenity": "marketplace"},
    ],
    "dairy_retail": [
        {"shop": "dairy"},
    ],
}


def normalize_category(tags: dict) -> str | None:
    normalized = {
        str(key).casefold(): str(value).casefold().strip()
        for key, value in tags.items()
    }

    for category, rules in CATEGORY_RULES.items():
        for rule in rules:
            if all(normalized.get(key) == value for key, value in rule.items()):
                return category

    return None


def build_query(bbox: tuple[float, float, float, float]) -> str:
    bbox_text = ",".join(map(str, bbox))

    # Query keys are derived from rules, so adding a category does not
    # accidentally forget its associated Overpass query.
    keys = sorted({
        key
        for rules in CATEGORY_RULES.values()
        for rule in rules
        for key in rule
    })

    clauses = [
        f'node["place"="village"]({bbox_text});'
    ]
    clauses.extend(
        f'nwr["{key}"]({bbox_text});'
        for key in keys
    )

    return (
        "[out:json][timeout:180];"
        "(" + "".join(clauses) + ");"
        "out center tags;"
    )


def validate_response(payload):
    if not isinstance(payload, dict):
        raise ValueError("Overpass response is not a JSON object")

    # Overpass can return HTTP 200 with a runtime error and partial data.
    if payload.get("remark"):
        raise ValueError(
            f"Overpass reported an error/partial result: {payload['remark']}"
        )

    if not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass response has no elements list")

    if not all(isinstance(item, dict) for item in payload["elements"]):
        raise ValueError("Overpass elements contain non-object records")


def fetch_overpass(
    district: str,
    endpoint: str,
    cache_dir: Path,
    refresh: bool = False,
    offline: bool = False,
    attempts: int = 5,
    client=None,
    sleep=time.sleep,
) -> tuple[dict, Path]:
    query = build_query(DISTRICTS[district])
    query_hash = digest(query.encode("utf-8"))

    cache_path = cache_dir / (
        f"osm_{district.lower()}_{query_hash[:16]}.json"
    )

    if cache_path.exists() and not refresh:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        validate_response(payload)
        return payload, cache_path

    if offline:
        raise FileNotFoundError(
            f"Offline mode: required cache is missing: {cache_path}"
        )

    owns_client = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(240, connect=30),
        headers={"User-Agent": "GraminSetu-SIH-MVP/0.1"},
    )

    last_error = None

    try:
        for attempt in range(attempts):
            retry_after = None

            try:
                response = client.post(
                    endpoint,
                    data={"data": query},
                )

                if response.status_code in {429, 502, 503, 504}:
                    last_error = RuntimeError(
                        f"Overpass HTTP {response.status_code}"
                    )
                    header = response.headers.get("Retry-After", "")
                    if header.isdigit():
                        retry_after = min(int(header), 300)
                else:
                    response.raise_for_status()
                    payload = response.json()
                    validate_response(payload)

                    atomic_write(
                        cache_path,
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                        ).encode("utf-8"),
                    )
                    return payload, cache_path

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc

            if attempt < attempts - 1:
                delay = (
                    retry_after
                    if retry_after is not None
                    else min(5 * (2 ** attempt), 120) + random.uniform(0, 2)
                )
                print(f"Retrying Overpass in {delay:.1f}s: {last_error}")
                sleep(delay)

        raise RuntimeError(
            f"Overpass failed after {attempts} attempts: {last_error}"
        )
    finally:
        if owns_client:
            client.close()


def osm_names(tags: dict) -> list[str]:
    names = []

    for key, value in tags.items():
        if (
            key == "name"
            or key.startswith("name:")
            or key in {"official_name", "alt_name", "short_name"}
        ):
            names.extend(
                name.strip()
                for name in str(value).split(";")
                if name.strip()
            )

    return sorted(set(names))


def element_coordinates(element: dict):
    coordinates = (
        element
        if element.get("type") == "node"
        else element.get("center", {})
    )

    latitude = coordinates.get("lat")
    longitude = coordinates.get("lon")

    if latitude is None or longitude is None:
        return None

    latitude = float(latitude)
    longitude = float(longitude)

    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        raise ValueError(f"Invalid OSM coordinates: {element.get('id')}")

    return longitude, latitude


def import_osm(
    district: str,
    payload: dict,
    cache_path: Path,
    boundary_path: Path,
):
    boundary = load_boundary(boundary_path)

    places = []
    pois = []
    seen = set()

    for element in payload["elements"]:
        osm_type = element.get("type")
        osm_id = element.get("id")

        if osm_type not in {"node", "way", "relation"} or osm_id is None:
            continue

        identity = (osm_type, int(osm_id))
        if identity in seen:
            continue
        seen.add(identity)

        coordinates = element_coordinates(element)
        if coordinates is None:
            continue

        longitude, latitude = coordinates

        if not inside_boundary(boundary, longitude, latitude):
            continue

        tags = element.get("tags", {})

        if osm_type == "node" and tags.get("place") == "village":
            names = osm_names(tags)

            if names:
                places.append({
                    "district": district,
                    "osm_id": int(osm_id),
                    "names": names,
                    "tags": tags,
                    "latitude": latitude,
                    "longitude": longitude,
                    "geom": point_wkt(longitude, latitude),
                })

        category = normalize_category(tags)

        if category:
            pois.append({
                "district": district,
                "osm_type": osm_type,
                "osm_id": int(osm_id),
                "category": category,
                "name": tags.get("name"),
                "tags": tags,
                "geom": point_wkt(longitude, latitude),
            })

    fingerprint = digest(
        cache_path.read_bytes(),
        boundary_path.read_bytes(),
        json_bytes(CATEGORY_RULES),
        Path(__file__).read_bytes(),
    )

    with Session(engine) as session, session.begin():
        lock_pipeline(session)

        session.execute(
            delete(OsmPlace).where(OsmPlace.district == district)
        )
        session.execute(
            delete(OsmPoi).where(OsmPoi.district == district)
        )

        for rows, model in ((places, OsmPlace), (pois, OsmPoi)):
            for start in range(0, len(rows), 500):
                session.execute(insert(model), rows[start:start + 500])

        save_dataset(
            session,
            f"osm:{district}",
            fingerprint,
            {
                "raw_cache": str(cache_path),
                "boundary": str(boundary_path),
                "bbox": list(DISTRICTS[district]),
                "osm_base_timestamp": payload.get(
                    "osm3s", {}
                ).get("timestamp_osm_base"),
                "place_nodes": len(places),
                "normalized_pois": len(pois),
                "license": "OpenStreetMap contributors, ODbL",
                "representative_points": (
                    "Nodes use their coordinates; ways/relations use "
                    "Overpass bounding-box centers."
                ),
            },
        )

        invalidate_index(session)

    print(
        f"{district}: imported {len(places)} village place nodes "
        f"and {len(pois)} categorized POIs"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--district", choices=DISTRICTS, required=True)
    parser.add_argument("--boundary", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument(
        "--endpoint",
        default="https://overpass-api.de/api/interpreter",
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    if args.refresh and args.offline:
        parser.error("--refresh and --offline cannot be combined")

    initialize_database()

    payload, cache_path = fetch_overpass(
        district=args.district,
        endpoint=args.endpoint,
        cache_dir=args.cache_dir,
        refresh=args.refresh,
        offline=args.offline,
    )

    import_osm(
        args.district,
        payload,
        cache_path,
        args.boundary,
    )


if __name__ == "__main__":
    main()