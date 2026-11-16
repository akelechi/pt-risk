"""FastAPI layer over the engine. Responses are the pydantic contracts, serialized.

The API computes nothing: it calls `engine.run.run`, stores the RunResult as JSON under
runs/{run_id}/, and serves slices of it. Run with:

    uvicorn api.main:app --reload

Two environment variables adapt it to a host whose code directory is read-only:
  ROSETON_RUNS_DIR         where runs are stored (default: runs/ under the repository root)
  ROSETON_SEED_SCENARIOS   comma-separated scenario files to run once, the first time runs
                           are asked for, so a fresh instance has something to show
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine.contracts import (
    HourFlow,
    LedgerEntry,
    LedgerRollup,
    ParamsResponse,
    PlantState,
    RunCreated,
    RunMeta,
    RunResult,
    RunSummary,
    Scenario,
)
from engine.flow import hour_flow, hour_flows
from engine.ledger.ledger import Grain, rollup
from engine.plant.params import ProvenanceError, flatten_leaves, load_plant, status_counts
from engine.run import REPO_ROOT, load_scenario, run

RUNS_DIR = "runs"
RUNS_DIR_ENV = "ROSETON_RUNS_DIR"
SEED_SCENARIOS_ENV = "ROSETON_SEED_SCENARIOS"
RESULT_FILE = "result.json"
DEFAULT_PLANT_CONFIG = Path("config") / "plant.roseton.yaml"


def create_app(root: Path = REPO_ROOT) -> FastAPI:
    """Build the app against a repository root (tests pass a temporary root)."""
    root = Path(root)
    app = FastAPI(title="Roseton Ledger API", version="0.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    runs_dir = Path(os.environ[RUNS_DIR_ENV]) if os.environ.get(RUNS_DIR_ENV) else root / RUNS_DIR
    seed_lock = threading.Lock()
    seeded = {"done": False}

    def store(result: RunResult) -> None:
        directory = runs_dir / result.meta.run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / RESULT_FILE).write_text(result.model_dump_json())

    def ensure_seeded() -> None:
        """Run the seed scenarios once per process when the run store is empty."""
        if seeded["done"]:
            return
        with seed_lock:
            if seeded["done"]:
                return
            paths = [item.strip() for item in os.environ.get(SEED_SCENARIOS_ENV, "").split(",") if item.strip()]
            if paths and not any(runs_dir.glob(f"*/{RESULT_FILE}")):
                for path in paths:
                    store(run(load_scenario(root / path), root))
            seeded["done"] = True

    def load_result(run_id: str) -> RunResult:
        if not run_id.isalnum():
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        ensure_seeded()
        path = runs_dir / run_id / RESULT_FILE
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        return RunResult.model_validate_json(path.read_text())

    @app.post("/runs", response_model=RunCreated, status_code=201)
    def create_run(scenario: Scenario) -> RunCreated:
        """Execute a scenario synchronously and return its run id."""
        try:
            result = run(scenario, root)
        except NotImplementedError as error:
            raise HTTPException(status_code=501, detail=str(error)) from error
        except (ValueError, KeyError, FileNotFoundError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        store(result)
        return RunCreated(run_id=result.meta.run_id)

    @app.get("/runs", response_model=list[RunSummary])
    def list_runs() -> list[RunSummary]:
        """Stored runs, sorted by run id."""
        ensure_seeded()
        directory = runs_dir
        if not directory.exists():
            return []
        summaries = []
        for path in sorted(directory.glob(f"*/{RESULT_FILE}")):
            meta = RunResult.model_validate_json(path.read_text()).meta
            summaries.append(
                RunSummary(
                    run_id=meta.run_id,
                    scenario_name=meta.scenario.name,
                    start_date=meta.scenario.start_date,
                    end_date=meta.scenario.end_date,
                    unit_ids=meta.scenario.unit_ids,
                    ledger_entry_count=meta.ledger_entry_count,
                    energy_margin_usd=meta.energy_margin_usd,
                    modules_on=[name for name, on in meta.scenario.modules.model_dump().items() if on],
                )
            )
        return summaries

    def pick_unit(result: RunResult, unit_id: str | None) -> str:
        units = result.meta.scenario.unit_ids
        if unit_id is None:
            if len(units) != 1:
                raise HTTPException(status_code=422, detail=f"run has units {units}; pass unit_id")
            return units[0]
        if unit_id not in units:
            raise HTTPException(status_code=404, detail=f"run has no unit {unit_id!r}")
        return unit_id

    @app.get("/runs/{run_id}/flow", response_model=list[HourFlow])
    def get_flow(run_id: str, unit_id: str | None = None, month: str | None = None) -> list[HourFlow]:
        """Flow-diagram payloads for every hour of one unit, optionally one local month (YYYY-MM)."""
        result = load_result(run_id)
        return hour_flows(result, unit_id=pick_unit(result, unit_id), month=month)

    @app.get("/runs/{run_id}/hour/{ts}", response_model=HourFlow)
    def get_hour(run_id: str, ts: str, unit_id: str | None = None) -> HourFlow:
        """Flow-diagram payload for one hour: every arrow's value plus the rows behind it.

        `ts` is an ISO timestamp with a UTC offset, e.g. 2025-01-15T17:00:00Z.
        """
        try:
            stamp = datetime.fromisoformat(ts)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=f"bad timestamp {ts!r}") from error
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise HTTPException(status_code=422, detail="timestamp needs a UTC offset (e.g. ...Z)")
        result = load_result(run_id)
        flow = hour_flow(result, pick_unit(result, unit_id), stamp)
        if flow is None:
            raise HTTPException(status_code=404, detail=f"run has no hour {ts}")
        return flow

    @app.get("/runs/{run_id}", response_model=RunMeta)
    def get_run(run_id: str) -> RunMeta:
        """Run metadata: config hash, seed, data snapshot ids, code version, invariant results."""
        return load_result(run_id).meta

    @app.get("/runs/{run_id}/ledger", response_model=list[LedgerEntry] | list[LedgerRollup])
    def get_ledger(run_id: str, grain: Grain = "hour") -> list[LedgerEntry] | list[LedgerRollup]:
        """Ledger entries (grain=hour) or roll-up views by local day or month."""
        entries = load_result(run_id).ledger
        return entries if grain == "hour" else rollup(entries, grain)

    @app.get("/runs/{run_id}/states", response_model=list[PlantState])
    def get_states(run_id: str) -> list[PlantState]:
        """Hourly plant states of the run."""
        return load_result(run_id).states

    @app.get("/params", response_model=ParamsResponse)
    def get_params() -> ParamsResponse:
        """Plant config with provenance, flattened, plus the count of assumed parameters."""
        try:
            plant = load_plant(root / DEFAULT_PLANT_CONFIG)
        except ProvenanceError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        counts = status_counts(plant)
        return ParamsResponse(
            plant_name=plant.name,
            leaves=flatten_leaves(plant),
            status_counts=counts,
            assumed_parameter_count=counts["assumed"],
        )

    return app


app = create_app()
