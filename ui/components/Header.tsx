import type { Fetched, ParamsResponse } from "@/lib/api";

/**
 * Header shown on every screen. Carries the count of `assumed` plant parameters
 * (invariant 7). The count is read from the engine; if the engine is unreachable the
 * header says so rather than showing a remembered number.
 */
export function Header({ params, screen, tag }: { params: Fetched<ParamsResponse>; screen: string; tag: string }) {
  return (
    <header className="header">
      <div className="brand">
        <span className="brand-name">ROSETON LEDGER</span>
        <span className="brand-screen">{screen}</span>
      </div>
      <div className="header-status">
        <span className="tag">{tag}</span>
        {params.online ? (
          <span
            className="badge badge-assumed"
            aria-label={`${params.data.assumed_parameter_count} of ${params.data.leaves.length} plant parameters are assumed`}
          >
            <span className="badge-mark" aria-hidden="true" />
            <span className="num">{params.data.assumed_parameter_count}</span> assumed
            <span className="badge-of">
              of <span className="num">{params.data.leaves.length}</span> parameters
            </span>
          </span>
        ) : (
          <span className="badge badge-offline" role="status">
            <span className="badge-mark" aria-hidden="true" />
            {params.reason} · assumed count unavailable
          </span>
        )}
      </div>
    </header>
  );
}
