import Link from "next/link";
import { EngineChecks } from "@/components/EngineChecks";
import { FlowDiagram } from "@/components/FlowDiagram";
import { FlowExplorer } from "@/components/FlowExplorer";
import { Header } from "@/components/Header";
import { fetchFlow, fetchParams, fetchRun, fetchRuns, toHourView, type RunMeta, type RunSummary } from "@/lib/api";
import { formatNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

type Search = { run?: string; unit?: string; hour?: string };

/** Which run to show: the one named in the URL, else the first stored run that booked anything. */
function chooseRun(runs: RunSummary[], requested: string | undefined): RunSummary | null {
  if (requested) return runs.find((run) => run.run_id === requested) ?? null;
  return runs.find((run) => run.ledger_entry_count > 0) ?? null;
}

/** What the loaded run models, from the modules its scenario switched on. */
function scopeTag(meta: RunMeta): string {
  const modules = meta.scenario.modules;
  return [
    modules.dp_commitment ? "DP COMMITMENT" : "PRICE-TAKER",
    modules.rt_settlement ? "DA + RT" : "DA ONLY",
    modules.outages ? "SEEDED OUTAGES" : null,
    modules.dual_fuel ? "GAS + OIL" : "GAS ONLY",
  ]
    .filter(Boolean)
    .join(" · ");
}

export default async function FlowPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const [params, runs] = await Promise.all([fetchParams(), fetchRuns()]);
  const run = runs.online ? chooseRun(runs.data, search.run) : null;
  const unit = run ? (search.unit && run.unit_ids.includes(search.unit) ? search.unit : run.unit_ids[0]) : null;
  const [flow, meta] = run && unit ? await Promise.all([fetchFlow(run.run_id, unit), fetchRun(run.run_id)]) : [null, null];
  const hours = flow?.online ? flow.data.map(toHourView) : [];

  return (
    <>
      <Header params={params} screen="Flow" tag={meta?.online ? scopeTag(meta.data) : "NO RUN LOADED"} />
      <main className="page">
        <div className="page-head">
          <p className="eyebrow">Flow</p>
          <h1>The plant, hour by hour</h1>
          {run && unit && meta?.online ? (
            <dl className="run-strip">
              <div>
                <dt>Run</dt>
                <dd className="num">{run.run_id}</dd>
              </div>
              <div>
                <dt>Scenario</dt>
                <dd>
                  {runs.online &&
                    runs.data
                      .filter((item) => item.ledger_entry_count > 0)
                      .map((item) => (
                        <Link key={item.run_id} href={`/?run=${item.run_id}`} className={item.run_id === run.run_id ? "pick current" : "pick"} aria-current={item.run_id === run.run_id}>
                          {item.scenario_name}
                        </Link>
                      ))}
                </dd>
              </div>
              <div>
                <dt>Window</dt>
                <dd className="num">
                  {run.start_date} to {run.end_date}
                </dd>
              </div>
              <div>
                <dt>Unit</dt>
                <dd>
                  {run.unit_ids.map((id) => (
                    <Link key={id} href={`/?run=${run.run_id}&unit=${id}`} className={id === unit ? "pick current" : "pick"} aria-current={id === unit}>
                      {id}
                    </Link>
                  ))}
                </dd>
              </div>
              <div>
                <dt>Energy margin, run</dt>
                <dd className="num money-text">{formatNumber(run.energy_margin_usd, "usd")} $</dd>
              </div>
            </dl>
          ) : (
            <p>
              {runs.online
                ? "No run with ledger entries is stored. POST a scenario with dispatch on to /runs, then reload. Figures below are placeholders."
                : `${runs.reason}. Figures below are placeholders.`}
            </p>
          )}
        </div>
        {meta?.online && <EngineChecks invariants={meta.data.invariants} />}
        {hours.length > 0 ? (
          <FlowExplorer
            hours={hours}
            solver={meta?.online ? meta.data.solver : "price_taker"}
            summaries={meta?.online ? meta.data.solver_comparison : []}
            initialIndex={Number.parseInt(search.hour ?? "0", 10) || 0}
          />
        ) : (
          <FlowDiagram hour={null} />
        )}
      </main>
    </>
  );
}
