from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.advisory_schemas import FinancialModelRequest
from app.advisory_service import exact_json
from app.api_errors import install_error_handlers
from app.data.models import Village
from app.db import get_db
from app.dpr.sample import sample_session
from app.models import Assessment, AdvisorySession
from app.routers import advisory


@pytest.fixture
def harness():
    assessment_id = str(uuid4())
    profile = {
        "applicant_name": "Test Applicant",
        "village_id": "TEST-LGD",
        "preferred_language": "en",
        "own_capital_paise": 12_000_000,
        "skills": ["basic_machine_operation"],
        "premises": "owned",
        "power": "three_phase",
    }
    assessment = SimpleNamespace(
        id=assessment_id,
        profile=profile,
    )
    village = SimpleNamespace(
        village_lgd="TEST-LGD",
        name="Test Village",
        district="Nashik",
        state="Maharashtra",
    )

    db = Mock()
    saved = {}

    def get(model, key):
        if model is Assessment:
            return assessment if key == assessment_id else None
        if model is Village:
            return village if key == "TEST-LGD" else None
        if model is AdvisorySession:
            return saved.get(key)
        return None

    db.get.side_effect = get
    db.add.side_effect = lambda record: saved.__setitem__(record.id, record)
    db.scalars.return_value.all.return_value = []

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(advisory.router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, db, assessment_id, saved


def request_payload(assessment_id):
    sample = sample_session()
    return {
        "assessment_id": assessment_id,
        "archetype_id": "flour_mill",
        "available_for_project_paise": 12_000_000,
        "finance": sample.finance.model_dump(mode="json"),
        "assumptions": sample.assumptions.model_dump(mode="json"),
    }


@pytest.mark.parametrize("bad_money", [1.5, "100", True])
def test_money_is_strict(harness, bad_money):
    client, _, assessment_id, _ = harness
    payload = request_payload(assessment_id)
    payload["available_for_project_paise"] = bad_money

    response = client.post("/api/financial-model", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_fraction_serialization_is_exact():
    assert exact_json({"ratio": Fraction(5, 4)}) == {
        "ratio": {"numerator": 5, "denominator": 4}
    }


def test_invalid_moratorium_is_rejected(harness):
    _, _, assessment_id, _ = harness
    payload = request_payload(assessment_id)
    payload["finance"]["moratorium_months"] = 60

    with pytest.raises(ValueError):
        FinancialModelRequest.model_validate(payload)


def test_missing_index_is_structured(harness):
    client, _, assessment_id, _ = harness

    response = client.get(
        "/api/villages/TEST-LGD/viability",
        params={"assessment_id": assessment_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OUT_OF_COVERAGE"
    assert body["items"] == []
    assert len(body["missing_archetype_ids"]) == 6


def test_financial_model_persists_exact_snapshot(harness):
    client, db, assessment_id, saved = harness

    response = client.post(
        "/api/financial-model",
        json=request_payload(assessment_id),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    record = saved[body["session_id"]]

    assert record.status == "modelled"
    assert record.financial_model == body["snapshot"]
    assert record.session_data["kind"] == "financial_model"
    assert len(body["snapshot"]["pnl"]) == 60
    db.commit.assert_called_once()

    for year in body["snapshot"]["dscr"]:
        if year["ratio"] is not None:
            assert set(year["ratio"]) == {"numerator", "denominator"}


def test_capital_stack_retains_infeasible_offers(harness):
    client, _, assessment_id, saved = harness
    payload = request_payload(assessment_id)
    offer = payload.pop("finance")
    offer["eligibility_confirmed"] = False
    payload["offers"] = [offer]

    response = client.post("/api/capital-stack", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["options"]) == 1
    result = body["options"][0]["result"]
    assert result["feasible"] is False
    assert result["reasons"]
    assert saved[body["session_id"]].capital_stack == body


def test_unexpected_errors_do_not_expose_details(harness):
    client, db, assessment_id, _ = harness
    db.get.side_effect = RuntimeError("SECRET database connection details")

    response = client.get(
        "/api/villages/TEST-LGD/viability",
        params={"assessment_id": assessment_id},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "SECRET" not in response.text
    assert "Traceback" not in response.text


def test_pdf_download(harness, monkeypatch, tmp_path):
    client, _, _, saved = harness
    session_id = str(uuid4())
    artifact_id = str(uuid4())
    monkeypatch.setenv("DPR_OUTPUT_DIR", str(tmp_path))

    pdf = b"%PDF-1.4\n% test artifact\n"
    (tmp_path / f"{artifact_id}.pdf").write_bytes(pdf)
    saved[session_id] = AdvisorySession(
        id=session_id,
        status="dpr_ready",
        session_data={},
        dpr_artifact_id=artifact_id,
    )

    response = client.get(f"/api/dpr/{session_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == pdf


def test_unknown_pdf_session(harness):
    client, _, _, _ = harness
    response = client.get(f"/api/dpr/{uuid4()}/download")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"