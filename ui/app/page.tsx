import Link from "next/link";
import { FlowDiagram } from "@/components/FlowDiagram";
import { FlowExplorer } from "@/components/FlowExplorer";
import { Header } from "@/components/Header";
import { fetchFlow, fetchParams, fetchRun, fetchRuns, toHourView, type RunSummary } from "@/lib/api";
import { formatNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

type Search = { run?: string; unit?: string; hour?: string };

/** Which run to show: the one named in the URL, else the first stored run that booked anything. */
function chooseRun(runs: RunSummary[], requested: string | undefined): RunSummary | null {
  if (requested) return runs.find((run) => run.run_id === requested) ?? null;
  return runs.find((run) => run.ledger_entry_count > 0) ?? null;
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
      <Header params={params} screen="Flow" tag="MILESTONE 1 · DA PRICE-TAKER · GAS ONLY" />
      <main className="page">
        <div className="page-head">
          <h1>One hour of the plant</h1>
          {run && unit && meta?.online ? (
            <dl className="run-strip">
              <div>
                <dt>Run</dt>
                <dd className="num">{run.run_id}</dd>
              </div>
              <div>
                <dt>Scenario</dt>
                <dd>{run.scenario_name}</dd>
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
              <div>
                <dt>Invariants</dt>
                <dd className="checks">
                  {meta.data.invariants.map((item) => (
                    <span key={item.invariant_id} className={`check ${item.status}`} title={`${item.name}: ${item.detail}`}>
                      <span aria-hidden="true">{item.status === "pass" ? "✓" : item.status === "fail" ? "✕" : "·"}</span>
                      <span className="num">{item.invariant_id}</span>
                      <span className="sr-only">
                        {item.name}: {item.status.replace("_", " ")}
                      </span>
                    </span>
                  ))}
                </dd>
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
        {hours.length > 0 ? (
          <FlowExplorer hours={hours} initialIndex={Number.parseInt(search.hour ?? "0", 10) || 0} />
        ) : (
          <FlowDiagram hour={null} />
        )}
      </main>
    </>
  );
}
