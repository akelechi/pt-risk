import type { EngineParams } from "@/lib/api";

/**
 * Header shown on every screen. Carries the count of `assumed` plant parameters
 * (invariant 7). The count is read from the engine; if the engine is unreachable the
 * header says so rather than showing a remembered number.
 */
export function Header({ engine, screen }: { engine: EngineParams; screen: string }) {
  return (
    <header className="header">
      <div className="brand">
        <span className="brand-name">ROSETON LEDGER</span>
        <span className="brand-screen">{screen}</span>
      </div>
      <div className="header-status">
        <span className="tag">MILESTONE 0 · STATIC</span>
        {engine.online ? (
          <span
            className="badge badge-assumed"
            aria-label={`${engine.params.assumed_parameter_count} of ${engine.params.leaves.length} plant parameters are assumed`}
          >
            <span className="badge-mark" aria-hidden="true" />
            <span className="num">{engine.params.assumed_parameter_count}</span> assumed
            <span className="badge-of">
              of <span className="num">{engine.params.leaves.length}</span> parameters
            </span>
          </span>
        ) : (
          <span className="badge badge-offline" role="status">
            <span className="badge-mark" aria-hidden="true" />
            {engine.reason} · assumed count unavailable
          </span>
        )}
      </div>
    </header>
  );
}
