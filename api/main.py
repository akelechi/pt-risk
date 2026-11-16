"""FastAPI layer over the engine. Responses are the pydantic contracts, serialized.

The API computes nothing: it calls `engine.run.run`, stores the RunResult as JSON under
runs/{run_id}/, and serves slices of it. Run with:

    uvicorn api.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine.contracts import (
    LedgerEntry,
    LedgerRollup,
    ParamsResponse,
    PlantState,
    RunCreated,
    RunMeta,
    RunResult,
    Scenario,
)
from engine.ledger.ledger import Grain, rollup
from engine.plant.params import ProvenanceError, flatten_leaves, load_plant, status_counts
from engine.run import REPO_ROOT, run

RUNS_DIR = "runs"
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

    def load_result(run_id: str) -> RunResult:
        if not run_id.isalnum():
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        path = root / RUNS_DIR / run_id / RESULT_FILE
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
        directory = root / RUNS_DIR / result.meta.run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / RESULT_FILE).write_text(result.model_dump_json())
        return RunCreated(run_id=result.meta.run_id)

    @app.get("/runs", response_model=list[str])
    def list_runs() -> list[str]:
        """Ids of stored runs, sorted."""
        directory = root / RUNS_DIR
        if not directory.exists():
            return []
        return sorted(path.parent.name for path in directory.glob(f"*/{RESULT_FILE}"))

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
