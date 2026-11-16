"""API returns a run id and serves the contracts; it computes nothing itself."""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from api.main import create_app
from engine.contracts import HourFlow, ParamsResponse, RunMeta
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
    assert [item["run_id"] for item in client.get("/runs").json()] == [run_id]


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
    modules = {**scenario_body["modules"], "gas_basis": True}
    assert client.post("/runs", json={**scenario_body, "modules": modules}).status_code == 501


def test_params_lists_every_leaf_with_provenance(client: TestClient):
    params = ParamsResponse.model_validate(client.get("/params").json())
    assert params.plant_name == "Roseton"
    assert len(params.leaves) == 38 and params.assumed_parameter_count == 31
    assert params.status_counts == {"public": 7, "assumed": 31, "confirmed": 0}
    assert all(leaf.source and leaf.unit for leaf in params.leaves)


# ------------------------------------------------------------------- milestone 1


@pytest.fixture()
def m1_run(client: TestClient) -> str:
    body = yaml.safe_load((REPO_ROOT / "config" / "scenario.m1.yaml").read_text())
    body["start_date"], body["end_date"] = "2025-01-01", "2025-01-03"
    response = client.post("/runs", json=body)
    assert response.status_code == 201
    return response.json()["run_id"]


def test_runs_list_summarises_runs(client: TestClient, m1_run: str):
    (summary,) = client.get("/runs").json()
    assert summary["run_id"] == m1_run and summary["scenario_name"] == "m1_jan2025_u1"
    assert summary["unit_ids"] == ["U1"] and summary["ledger_entry_count"] > 0
    assert summary["energy_margin_usd"] == client.get(f"/runs/{m1_run}").json()["energy_margin_usd"]


def test_flow_returns_one_payload_per_hour(client: TestClient, m1_run: str):
    flows = [HourFlow.model_validate(item) for item in client.get(f"/runs/{m1_run}/flow").json()]
    assert len(flows) == 3 * 24
    assert client.get(f"/runs/{m1_run}/flow", params={"month": "2025-02"}).json() == []
    meta = client.get(f"/runs/{m1_run}").json()
    assert round(sum(flow.hour_energy_margin_usd for flow in flows), 2) == meta["energy_margin_usd"]
    for flow in flows:
        assert flow.output_mw == flow.da_schedule_mw == flow.state.output_mw
        assert flow.hour_energy_margin_usd == pytest.approx(flow.da_energy_rev_usd + flow.fuel_cost_usd + flow.vom_usd, abs=0.005)
        assert flow.offered_mw == 553.32 and flow.offer_min_price_usd_per_mwh <= flow.offer_max_price_usd_per_mwh
        assert set(flow.input_refs) == {"lbmp_da", "gas_price", "gas_basis"}
        assert (len(flow.entries) == 3) == flow.state.committed


def test_hour_endpoint_matches_flow_and_ledger(client: TestClient, m1_run: str):
    flows = client.get(f"/runs/{m1_run}/flow").json()
    target = next(item for item in flows if item["state"]["committed"])
    for stamp in (target["ts_utc"], target["ts_local"]):  # same instant, either rendering
        hour = client.get(f"/runs/{m1_run}/hour/{stamp}")
        assert hour.status_code == 200 and hour.json() == target
    ledger = client.get(f"/runs/{m1_run}/ledger").json()
    booked = [entry for entry in ledger if entry["ts_utc"] == target["ts_utc"]]
    assert booked == target["entries"]
    month = client.get(f"/runs/{m1_run}/ledger", params={"grain": "month"}).json()
    assert {row["line"] for row in month} == {"da_energy_rev", "fuel_cost_gas", "vom"}
    assert len(client.get(f"/runs/{m1_run}/states").json()) == 72


def test_hour_endpoint_errors(client: TestClient, m1_run: str):
    assert client.get(f"/runs/{m1_run}/hour/2030-01-01T00:00:00Z").status_code == 404
    assert client.get(f"/runs/{m1_run}/hour/2025-01-01T05:00:00").status_code == 422  # no offset
    assert client.get(f"/runs/{m1_run}/hour/not-a-time").status_code == 422
    assert client.get(f"/runs/{m1_run}/flow", params={"unit_id": "U2"}).status_code == 404


def test_seed_scenarios_fill_an_empty_run_store_once(repo_copy, tmp_path, monkeypatch):
    """A host with a read-only code directory: runs live elsewhere and are seeded on first use."""
    from api.main import create_app

    store = tmp_path / "elsewhere"
    monkeypatch.setenv("ROSETON_RUNS_DIR", str(store))
    monkeypatch.setenv("ROSETON_SEED_SCENARIOS", "config/scenario.m1.yaml, config/scenario.m2.yaml")
    seeded = TestClient(create_app(repo_copy))
    runs = seeded.get("/runs").json()
    assert sorted(item["scenario_name"] for item in runs) == ["m1_jan2025_u1", "m2_jan2025_u1"]
    assert len(list(store.glob("*/result.json"))) == 2 and not (repo_copy / "runs").exists()
    assert seeded.get(f"/runs/{runs[0]['run_id']}").status_code == 200
    assert len(seeded.get("/runs").json()) == 2  # asked again: nothing is run twice


def test_code_version_falls_back_to_the_deployed_commit(tmp_path, monkeypatch):
    from engine.version import code_version

    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    assert code_version(tmp_path) == "unversioned"
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "abc123")
    assert code_version(tmp_path) == "abc123"
