/**
 * Read-only client for the engine API. Types come from the generated OpenAPI schema
 * (`npm run gen:types`); nothing here computes a figure.
 */
import type { components } from "./api-types";

export type ParamsResponse = components["schemas"]["ParamsResponse"];
export type RunSummary = components["schemas"]["RunSummary"];
export type RunMeta = components["schemas"]["RunMeta"];
export type HourFlow = components["schemas"]["HourFlow"];
export type SolverSummary = components["schemas"]["SolverSummary"];

/**
 * The fields of an HourFlow the flow screen displays, flattened. A selection of engine
 * values, passed from the server component to the scrubber; no arithmetic is done on them.
 */
export type HourView = Pick<
  HourFlow,
  | "ts_utc"
  | "ts_local"
  | "unit_id"
  | "da_lbmp_usd_per_mwh"
  | "offered_mw"
  | "offer_min_price_usd_per_mwh"
  | "offer_max_price_usd_per_mwh"
  | "da_schedule_mw"
  | "output_mw"
  | "gas_price_usd_per_mmbtu"
  | "gas_burn_mmbtu"
  | "da_energy_rev_usd"
  | "fuel_cost_usd"
  | "vom_usd"
  | "hour_energy_margin_usd"
  | "start_cost_usd"
  | "start_and_no_load_cost_usd"
  | "uplift_usd"
  | "started"
  | "rt_lbmp_usd_per_mwh"
  | "deviation_mw"
  | "rt_balancing_usd"
  | "forced_outage"
  | "comparison_output_mw"
> & {
  committed: boolean;
  thermal_state: HourFlow["state"]["thermal_state"];
  fuel: HourFlow["state"]["fuel"];
  available_mw: number;
  reason: string;
};

export function toHourView(flow: HourFlow): HourView {
  return {
    ts_utc: flow.ts_utc,
    ts_local: flow.ts_local,
    unit_id: flow.unit_id,
    da_lbmp_usd_per_mwh: flow.da_lbmp_usd_per_mwh,
    offered_mw: flow.offered_mw,
    offer_min_price_usd_per_mwh: flow.offer_min_price_usd_per_mwh,
    offer_max_price_usd_per_mwh: flow.offer_max_price_usd_per_mwh,
    da_schedule_mw: flow.da_schedule_mw,
    output_mw: flow.output_mw,
    gas_price_usd_per_mmbtu: flow.gas_price_usd_per_mmbtu,
    gas_burn_mmbtu: flow.gas_burn_mmbtu,
    da_energy_rev_usd: flow.da_energy_rev_usd,
    fuel_cost_usd: flow.fuel_cost_usd,
    vom_usd: flow.vom_usd,
    hour_energy_margin_usd: flow.hour_energy_margin_usd,
    start_cost_usd: flow.start_cost_usd,
    start_and_no_load_cost_usd: flow.start_and_no_load_cost_usd,
    uplift_usd: flow.uplift_usd,
    started: flow.started,
    rt_lbmp_usd_per_mwh: flow.rt_lbmp_usd_per_mwh,
    deviation_mw: flow.deviation_mw,
    rt_balancing_usd: flow.rt_balancing_usd,
    forced_outage: flow.forced_outage,
    comparison_output_mw: flow.comparison_output_mw,
    committed: flow.state.committed,
    thermal_state: flow.state.thermal_state,
    fuel: flow.state.fuel,
    available_mw: flow.state.available_mw,
    reason: flow.decision.reason,
  };
}

const API_URL = process.env.ROSETON_API_URL ?? "http://127.0.0.1:8000";

export type Fetched<T> = { online: true; data: T } | { online: false; reason: string };

/** GET a path from the engine. Never throws: an unreachable engine is a visible state. */
async function get<T>(path: string): Promise<Fetched<T>> {
  try {
    const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
    if (!response.ok) {
      return { online: false, reason: `engine returned ${response.status}` };
    }
    return { online: true, data: (await response.json()) as T };
  } catch {
    return { online: false, reason: "engine unreachable" };
  }
}

/** Plant parameters with provenance. */
export const fetchParams = () => get<ParamsResponse>("/params");

/** Stored runs. */
export const fetchRuns = () => get<RunSummary[]>("/runs");

/** Metadata of one run, including invariant results. */
export const fetchRun = (runId: string) => get<RunMeta>(`/runs/${encodeURIComponent(runId)}`);

/** Flow payloads for every hour of one unit of a run. */
export const fetchFlow = (runId: string, unitId: string) =>
  get<HourFlow[]>(`/runs/${encodeURIComponent(runId)}/flow?unit_id=${encodeURIComponent(unitId)}`);
