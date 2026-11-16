"use client";

import { useMemo } from "react";
import type { HourView, SolverSummary } from "@/lib/api";
import { formatNumber } from "@/lib/format";

const TRACK_HEIGHT = 12;

const SOLVER_LABEL: Record<string, string> = {
  dp: "DP",
  price_taker_constrained: "Price-taker with run-time limits",
  price_taker: "Price-taker, no limits or start cost",
};

type Row = { solver: string; on: boolean[]; starts: number[] };

/** On/off per hour and the hours where a solver comes on line, read from engine output MW. */
function rowOf(solver: string, outputMw: number[]): Row {
  const on = outputMw.map((mw) => mw > 0);
  const starts = on.flatMap((isOn, position) => (isOn && !(position > 0 && on[position - 1]) ? [position] : []));
  return { solver, on, starts };
}

/**
 * Commitment timeline: one track per solver on the same hour axis as the price plot.
 * Filled = on line; a notch above the track = a start. The first track is the run's own
 * solver; the others are the baselines the engine ran alongside it. Totals in the
 * captions are the engine's solver summaries.
 */
export function CommitmentStrip({ hours, index, solver, summaries }: {
  hours: HourView[]; index: number; solver: string; summaries: SolverSummary[];
}) {
  const rows = useMemo(() => {
    const own = rowOf(solver, hours.map((hour) => hour.output_mw));
    const others = Object.keys(hours[0]?.comparison_output_mw ?? {}).map((name) =>
      rowOf(name, hours.map((hour) => hour.comparison_output_mw[name] ?? 0)),
    );
    return [own, ...others];
  }, [hours, solver]);
  const summaryOf = (name: string) => summaries.find((item) => item.solver === name);

  return (
    <section className="commitment" aria-label="Commitment timeline by solver">
      {rows.map((row, position) => {
        const summary = summaryOf(row.solver);
        return (
          <div key={row.solver} className="commitment-row">
            <div className="commitment-caption">
              <span className="commitment-name">
                {SOLVER_LABEL[row.solver] ?? row.solver}
                {position === 0 ? " · this run" : ""}
              </span>
              {summary && (
                <span className="commitment-totals">
                  <span className="num">{summary.starts}</span> starts ·{" "}
                  <span className="num">{summary.hours_on}</span> h on · energy margin{" "}
                  <span className="num money-text">{formatNumber(summary.energy_margin_usd, "usd")}</span>{" "}
                  <span className="figure-unit">$</span>
                </span>
              )}
            </div>
            <svg className="commitment-track" viewBox={`0 0 ${hours.length} ${TRACK_HEIGHT}`} preserveAspectRatio="none"
              role="img" aria-label={`${SOLVER_LABEL[row.solver] ?? row.solver}: ${row.starts.length} starts, on in ${row.on.filter(Boolean).length} of ${hours.length} hours`}>
              {row.on.map((isOn, hour) =>
                isOn ? <rect key={hour} x={hour} y={4} width={1} height={TRACK_HEIGHT - 4} className="strip-on" /> : null,
              )}
              {position === 0 &&
                hours.map((item, hour) =>
                  item.forced_outage ? <rect key={`out-${hour}`} x={hour} y={0} width={1} height={4} className="strip-outage" /> : null,
                )}
              {row.starts.map((hour) => (
                <rect key={`start-${hour}`} x={hour} y={0} width={2} height={TRACK_HEIGHT} className="strip-start" />
              ))}
              <rect x={index} y={0} width={1} height={TRACK_HEIGHT} className="strip-cursor" />
            </svg>
          </div>
        );
      })}
      <p className="commitment-key">
        <span className="key-on" aria-hidden="true" /> on line
        <span className="key-start" aria-hidden="true" /> start
        {hours.some((item) => item.forced_outage) && (
          <>
            <span className="key-outage" aria-hidden="true" /> forced outage (this run)
          </>
        )}
      </p>
    </section>
  );
}
