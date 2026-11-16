import type { RunMeta } from "@/lib/api";

type Invariant = RunMeta["invariants"][number];

/** One plain sentence per check, for a reader who has not seen the brief. Wording only. */
const PLAIN: Record<number, string> = {
  1: "What the plant delivered equals what it sold day-ahead plus what it settled in real time.",
  2: "Fuel burned matches the plant's output, hours on line and starts; the oil tank never goes negative and permit hours are not exceeded.",
  3: "Fuel, no-load and start costs equal fuel quantity times fuel price, each hour to the cent.",
  4: "Energy revenue equals schedule times day-ahead price plus deviation times real-time price, each hour to the cent.",
  5: "The optimised schedule is never worse than the simple rule and never better than the theoretical best.",
  6: "Every day has the right number of hours, including the 23- and 25-hour daylight-saving days.",
  7: "Every plant parameter states its value, unit, source and whether it is public or assumed.",
  8: "Running the same scenario twice gives exactly the same ledger.",
};

const STATUS_WORD: Record<Invariant["status"], string> = {
  pass: "holds",
  fail: "FAILS",
  not_applicable: "not modelled in this run",
};

const MARK: Record<Invariant["status"], string> = { pass: "✓", fail: "✕", not_applicable: "·" };

/**
 * The engine's self-checks for the loaded run, named in words. The summary line says how
 * many hold; opening it shows what each one means and the engine's own detail line.
 * Statuses and details come from the engine; only the explanatory sentences live here.
 */
export function EngineChecks({ invariants }: { invariants: Invariant[] }) {
  const checked = invariants.filter((item) => item.status !== "not_applicable");
  const passed = checked.filter((item) => item.status === "pass").length;
  const failed = checked.length - passed;
  return (
    <details className={`engine-checks${failed > 0 ? " failing" : ""}`}>
      <summary>
        <span className="engine-checks-title">Engine self-checks</span>
        <span className="engine-checks-count">
          {failed > 0 ? (
            <>
              <span className="num">{failed}</span> of <span className="num">{checked.length}</span> FAIL
            </>
          ) : (
            <>
              <span className="num">{passed}</span> of <span className="num">{checked.length}</span> hold
            </>
          )}
          {checked.length < invariants.length && (
            <>
              {" "}
              · <span className="num">{invariants.length - checked.length}</span> not modelled in this run
            </>
          )}
        </span>
        <span className="checks">
          {invariants.map((item) => (
            <span key={item.invariant_id} className={`check ${item.status}`}>
              <span aria-hidden="true">{MARK[item.status]}</span> {item.name}
              <span className="sr-only">: {STATUS_WORD[item.status]}</span>
            </span>
          ))}
        </span>
        <span className="engine-checks-hint">what these mean</span>
      </summary>
      <p className="engine-checks-intro">
        After every run the engine recomputes these identities from the plant&apos;s states and the input prices,
        independently of the ledger, and compares. A check that fails means the numbers on this screen cannot be trusted.
      </p>
      <ol className="engine-checks-list">
        {invariants.map((item) => (
          <li key={item.invariant_id} className={item.status}>
            <span className={`check ${item.status}`}>
              <span aria-hidden="true">{MARK[item.status]}</span> {item.name}
            </span>
            <span className="engine-checks-status">{STATUS_WORD[item.status]}</span>
            <p>{PLAIN[item.invariant_id] ?? item.name}</p>
            <p className="engine-checks-detail">{item.detail}</p>
          </li>
        ))}
      </ol>
    </details>
  );
}
