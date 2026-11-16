import Link from "next/link";
import type { Fetched, ParamsResponse } from "@/lib/api";

/**
 * Header shown on every screen. Carries the count of `assumed` plant parameters
 * (invariant 7). The count is read from the engine; if the engine is unreachable the
 * header says so rather than showing a remembered number.
 */
const SCREENS = [
  { name: "Flow", href: "/" },
  { name: "Parameters", href: "/parameters" },
];

export function Header({ params, screen, tag }: { params: Fetched<ParamsResponse>; screen: string; tag: string }) {
  return (
    <header className="header">
      <div className="brand">
        <span className="brand-name">ROSETON LEDGER</span>
        <nav className="brand-nav" aria-label="Screens">
          {SCREENS.map((item) => (
            <Link key={item.href} href={item.href} className={item.name === screen ? "current" : undefined} aria-current={item.name === screen ? "page" : undefined}>
              {item.name}
            </Link>
          ))}
        </nav>
      </div>
      <div className="header-status">
        <span className="tag">{tag}</span>
        {params.online ? (
          <Link
            href="/parameters"
            className="badge badge-assumed"
            title="Plant parameters with no public source use typical values and are marked assumed. Open the list."
            aria-label={`${params.data.assumed_parameter_count} of ${params.data.leaves.length} plant parameters are assumed; open the list`}
          >
            <span className="badge-mark" aria-hidden="true" />
            <span className="num">{params.data.assumed_parameter_count}</span> assumed
            <span className="badge-of">
              of <span className="num">{params.data.leaves.length}</span> parameters
            </span>
          </Link>
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
