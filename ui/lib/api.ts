/**
 * Read-only client for the engine API. Types come from the generated OpenAPI schema
 * (`npm run gen:types`); nothing here computes a figure.
 */
import type { components } from "./api-types";

export type ParamsResponse = components["schemas"]["ParamsResponse"];

const API_URL = process.env.ROSETON_API_URL ?? "http://127.0.0.1:8000";

export type EngineParams =
  | { online: true; params: ParamsResponse }
  | { online: false; reason: string };

/** Plant parameters with provenance. Never throws: an unreachable engine is a visible state. */
export async function fetchParams(): Promise<EngineParams> {
  try {
    const response = await fetch(`${API_URL}/params`, { cache: "no-store" });
    if (!response.ok) {
      return { online: false, reason: `engine returned ${response.status}` };
    }
    return { online: true, params: (await response.json()) as ParamsResponse };
  } catch {
    return { online: false, reason: "engine unreachable" };
  }
}
