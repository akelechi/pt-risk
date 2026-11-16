"""API returns a run id and serves the contracts; it computes nothing itself."""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from api.main import create_app
from engine.contracts import ParamsResponse, RunMeta
from tests.conftest import REPO_ROOT


@pytest.fixture()
def client(repo_copy) -> TestClient:
    return TestClient(create_app(repo_copy))


@pytest.fixture()
def scenario_body() -> dict:
    body = yaml.safe_load((REPO_ROOT / "config" / "scenario.base.yaml").read_text())
    body["start_date"], body["end_date"] = "2025-01-01", "2025-01-31"
    return body


def test_post_runs_returns_a_stable_run_id(client: TestClient, scenario_body: dict):
    first = client.post("/runs", json=scenario_body)
    second = client.post("/runs", json=scenario_body)
    assert first.status_code == 201 and second.status_code == 201
    run_id = first.json()["run_id"]
    assert len(run_id) == 12 and run_id == second.json()["run_id"]
    assert client.get("/runs").json() == [run_id]


def test_get_run_returns_meta_with_invariants(client: TestClient, scenario_body: dict):
    run_id = client.post("/runs", json=scenario_body).json()["run_id"]
    meta = RunMeta.model_validate(client.get(f"/runs/{run_id}").json())
    assert meta.run_id == run_id and meta.seed == scenario_body["seed"]
    assert {result.invariant_id: result.status for result in meta.invariants} == {
        1: "not_applicable", 2: "not_applicable", 3: "not_applicable", 4: "not_applicable",
        5: "not_applicable", 6: "pass", 7: "pass", 8: "pass",
    }
    assert meta.inputs[0].rows == 3 * 31 * 24


def test_ledger_and_states_are_empty_in_milestone_0(client: TestClient, scenario_body: dict):
    run_id = client.post("/runs", json=scenario_body).json()["run_id"]
    for grain in ("hour", "day", "month"):
        response = client.get(f"/runs/{run_id}/ledger", params={"grain": grain})
        assert response.status_code == 200 and response.json() == []
    assert client.get(f"/runs/{run_id}/states").json() == []
    assert client.get(f"/runs/{run_id}/ledger", params={"grain": "year"}).status_code == 422


def test_unknown_run_and_bad_scenarios(client: TestClient, scenario_body: dict):
    assert client.get("/runs/doesnotexist").status_code == 404
    assert client.get("/runs/..%2F..%2Fconfig").status_code == 404
    assert client.post("/runs", json={**scenario_body, "end_date": "2024-01-01"}).status_code == 422
    assert client.post("/runs", json={**scenario_body, "unit_ids": ["U9"]}).status_code == 422
    modules = {**scenario_body["modules"], "dispatch": True}
    assert client.post("/runs", json={**scenario_body, "modules": modules}).status_code == 501


def test_params_lists_every_leaf_with_provenance(client: TestClient):
    params = ParamsResponse.model_validate(client.get("/params").json())
    assert params.plant_name == "Roseton"
    assert len(params.leaves) == 36 and params.assumed_parameter_count == 33
    assert params.status_counts == {"public": 3, "assumed": 33, "confirmed": 0}
    assert all(leaf.source and leaf.unit for leaf in params.leaves)
