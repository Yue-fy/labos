import asyncio

from fastapi.testclient import TestClient

from labos.central import create_app
from labos.models import Plan
from test_runtime import run_with_local_pump
from test_storage import ready_store


def test_failed_quality_review_cannot_promote_rejected_data(central_config, tmp_path):
    from labos.review import build_review
    store, run_id = asyncio.run(run_with_local_pump(central_config, tmp_path,
        Plan(angle_stop_deg=10, exposure_ms=1, quality={"max_counts": 2})))
    review = build_review(store, run_id)
    assert review["data_quality"] == {"accepted": 0, "rejected": 1, "unassessed": 0, "total": 1}
    assert review["signal_summary"] is None
    assert review["closure"]["status"] == "verified_by_software_readback"
    assert review["next_actions"][0]["requires_new_preflight"] is True
    assert review["next_actions"][0]["requires_start"] is True
    assert review["next_actions"][0]["proposed_plan"]["exposure_ms"] < 1
    assert store.latest_review(run_id)["body"] == review


def test_completed_run_reports_only_supported_observations(central_config, tmp_path):
    from labos.review import build_review
    store, run_id = asyncio.run(run_with_local_pump(central_config, tmp_path,
        Plan(angle_stop_deg=10, exposure_ms=1)))
    review = build_review(store, run_id)
    assert review["data_quality"]["accepted"] == 2
    assert len(review["accepted_measurement_ids"]) == 2
    assert review["signal_summary"]["qualified_spectra"] == 2
    assert "precision" in " ".join(review["limitations"]).lower()
    first = store.save_review(run_id, review)
    assert store.save_review(run_id, review)["id"] == first["id"]
    store.set_run(run_id, "FAILED", "closure changed")
    second = store.save_review(run_id, build_review(store, run_id))
    assert second["version"] == first["version"] + 1
    assert store.reviews(run_id)[-1]["body"] == review


def test_run_status_does_not_prove_shutdown(tmp_path):
    from labos.models import SetupProfile
    from labos.review import build_review
    store = ready_store(tmp_path)
    run_id = store.create_run(Plan(), SetupProfile(), {})["id"]
    store.set_run(run_id, "COMPLETED", release=True)
    assert build_review(store, run_id)["closure"]["status"] == "unconfirmed"


def test_review_routes_precede_control_and_are_operator_only(central_config):
    from labos.models import SetupProfile
    app = create_app(central_config)
    with TestClient(app) as client:
        run_id = app.state.store.create_run(Plan(), SetupProfile(), {})["id"]
        url = f"/api/runs/{run_id}/review"
        auth = {"Authorization": "Bearer " + "O" * 40}
        assert client.post(url, headers={"Authorization": "Bearer " + "A" * 40}).status_code == 403
        response = client.post(url, headers=auth)
        assert response.status_code == 200
        assert response.json()["body"]["closure"]["status"] == "unconfirmed"
        assert client.get(url, headers=auth).json()["id"] == response.json()["id"]
