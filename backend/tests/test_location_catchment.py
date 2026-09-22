from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api_errors import install_error_handlers
from app.data.catchment import LocationCatchment, compute_location_catchment
from app.data.models import Village
from app.db import get_db
from app.models import Assessment
from app.routers import advisory


# --- compute_location_catchment: pure aggregation over a mocked db.execute ---


def _db_returning(rows):
    db = Mock()
    db.execute.return_value.mappings.return_value.all.return_value = rows
    return db


def test_compute_location_catchment_sums_population_and_counts_facilities():
    rows = [
        {
            "village_lgd": "A",
            "population": 1_000,
            "village_amenities": {
                "markets": {
                    "mandis_regular_market": {"available": True},
                    "pds_shop": {"available": False},
                }
            },
        },
        {
            "village_lgd": "B",
            "population": 2_500,
            "village_amenities": {
                "markets": {
                    "weekly_haat": {"available": True},
                    "agricultural_marketing_society": {"available": True},
                }
            },
        },
        {
            # No amenities at all must count as zero, never be skipped or estimated.
            "village_lgd": "C",
            "population": 500,
            "village_amenities": None,
        },
    ]
    db = _db_returning(rows)

    result = compute_location_catchment(db, 19.5, 74.5)

    assert result.radius_m == 10_000
    assert result.village_count == 3
    assert result.catchment_population == 4_000
    assert result.market_facility_count == 3


def test_compute_location_catchment_empty_radius_is_all_zero():
    db = _db_returning([])

    result = compute_location_catchment(db, 0.0, 0.0)

    assert result.village_count == 0
    assert result.catchment_population == 0
    assert result.market_facility_count == 0


def test_compute_location_catchment_finance_facilities_are_not_counted():
    rows = [
        {
            "village_lgd": "A",
            "population": 1_000,
            "village_amenities": {
                "finance": {
                    "cooperative_bank": {"available": True},
                    "shg": {"available": True},
                },
                "markets": {},
            },
        },
    ]
    db = _db_returning(rows)

    result = compute_location_catchment(db, 19.5, 74.5)

    assert result.market_facility_count == 0


def test_compute_location_catchment_passes_point_and_radius_to_query():
    db = _db_returning([])

    compute_location_catchment(db, 19.1, 74.2, radius_m=5_000)

    _, params = db.execute.call_args.args
    assert params == {"latitude": 19.1, "longitude": 74.2, "radius_m": 5_000}


# --- /api/villages/{village_lgd}/viability: additive location_catchment field ---


def _client(profile_extra=None):
    assessment_id = str(uuid4())
    profile = {
        "applicant_name": "Test Applicant",
        "village_id": "TEST-LGD",
        "preferred_language": "en",
        "own_capital_paise": 12_000_000,
        "skills": [],
        "premises": "owned",
        "power": "three_phase",
        **(profile_extra or {}),
    }
    assessment = SimpleNamespace(id=assessment_id, profile=profile)
    village = SimpleNamespace(
        village_lgd="TEST-LGD",
        name="Test Village",
        district="Nashik",
        state="Maharashtra",
    )

    db = Mock()

    def get(model, key):
        if model is Assessment:
            return assessment if key == assessment_id else None
        if model is Village:
            return village if key == "TEST-LGD" else None
        return None

    db.get.side_effect = get
    db.scalars.return_value.all.return_value = []

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(advisory.router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    return TestClient(app, raise_server_exceptions=False), assessment_id


def test_viability_has_no_location_catchment_without_a_pin(monkeypatch):
    client, assessment_id = _client()

    def must_not_run(*args, **kwargs):
        raise AssertionError("must not compute a catchment when no pin was dropped")

    monkeypatch.setattr(advisory, "compute_location_catchment", must_not_run)

    response = client.get(
        "/api/villages/TEST-LGD/viability", params={"assessment_id": assessment_id}
    )

    assert response.status_code == 200
    assert response.json()["location_catchment"] is None


def test_viability_includes_location_catchment_when_pin_dropped(monkeypatch):
    client, assessment_id = _client(
        {"proposed_latitude": 20.0, "proposed_longitude": 74.0}
    )

    monkeypatch.setattr(
        advisory,
        "compute_location_catchment",
        lambda db, lat, lng, radius_m=10_000: LocationCatchment(
            radius_m=10_000,
            village_count=7,
            catchment_population=42_000,
            market_facility_count=3,
        ),
    )

    response = client.get(
        "/api/villages/TEST-LGD/viability", params={"assessment_id": assessment_id}
    )

    assert response.status_code == 200
    assert response.json()["location_catchment"] == {
        "radius_m": 10_000,
        "village_count": 7,
        "catchment_population": 42_000,
        "market_facility_count": 3,
    }


def test_viability_with_pin_does_not_change_status_or_items(monkeypatch):
    """Additive only: the catchment panel's presence must not shift the
    village_lgd scoring path's status/coverage/ranking output."""
    without_pin_client, without_id = _client()
    with_pin_client, with_id = _client(
        {"proposed_latitude": 20.0, "proposed_longitude": 74.0}
    )

    monkeypatch.setattr(
        advisory,
        "compute_location_catchment",
        lambda db, lat, lng, radius_m=10_000: LocationCatchment(
            radius_m=10_000, village_count=1, catchment_population=100,
            market_facility_count=0,
        ),
    )

    without = without_pin_client.get(
        "/api/villages/TEST-LGD/viability", params={"assessment_id": without_id}
    ).json()
    with_pin = with_pin_client.get(
        "/api/villages/TEST-LGD/viability", params={"assessment_id": with_id}
    ).json()

    for key in ("status", "message", "missing_archetype_ids", "items"):
        assert without[key] == with_pin[key]

    assert without["location_catchment"] is None
    assert with_pin["location_catchment"] is not None
