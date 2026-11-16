import { Header } from "@/components/Header";
import { fetchParams, type ParamsResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

type Leaf = ParamsResponse["leaves"][number];

const STATUS_WORD: Record<Leaf["status"], string> = { public: "public", assumed: "assumed", confirmed: "confirmed" };

const SECTION_TITLE: Record<string, string> = {
  fuel: "Fuel",
  emissions: "Emissions",
  capacity: "Capacity",
  fixed: "Fixed costs",
};

/** "units.U1.pmax_mw" -> section "Unit U1", name "pmax_mw". */
function split(path: string): { section: string; name: string } {
  const parts = path.split(".");
  if (parts[0] === "units") return { section: `Unit ${parts[1]}`, name: parts.slice(2).join(".") };
  return { section: SECTION_TITLE[parts[0]] ?? parts[0], name: parts.slice(1).join(".") };
}

/** A config value as readable text. Presentation only. */
function show(value: unknown): string {
  if (value === null || value === undefined) return "none";
  if (Array.isArray(value)) return value.map(show).join("; ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key} ${show(item)}`)
      .join(", ");
  }
  return String(value);
}

export default async function ParametersPage() {
  const params = await fetchParams();
  const sections = new Map<string, { name: string; leaf: Leaf }[]>();
  if (params.online) {
    for (const leaf of params.data.leaves) {
      const { section, name } = split(leaf.path);
      sections.set(section, [...(sections.get(section) ?? []), { name, leaf }]);
    }
  }
  return (
    <>
      <Header params={params} screen="Parameters" tag="PLANT CONFIG WITH PROVENANCE" />
      <main className="page">
        <div className="page-head">
          <p className="eyebrow">Parameters</p>
          <h1>What the model assumes about the plant</h1>
          <p className="params-intro">
            Every number that turns a price into a dollar is listed here with where it came from.{" "}
            <strong>Public</strong> values come from a published source such as EIA. <strong>Assumed</strong> values
            have no public source, so the model uses a typical value for this kind of plant and says so.{" "}
            <strong>Confirmed</strong> values have been checked against the plant&apos;s own records. Results on the
            Flow screen are only as good as the assumed values behind them. Both units carry the same assumed values,
            so each appears twice in the count.
          </p>
        </div>
        {!params.online ? (
          <p>{params.reason}. The parameter list is unavailable.</p>
        ) : (
          <>
            <ul className="params-counts" aria-label="Parameters by status">
              {(["public", "assumed", "confirmed"] as const).map((status) => (
                <li key={status}>
                  <span className={`status status-${status}`}>{STATUS_WORD[status]}</span>
                  <span className="num">{params.data.status_counts[status] ?? 0}</span>
                </li>
              ))}
            </ul>
            {[...sections.entries()].map(([section, rows]) => (
              <section key={section} className="params-section" aria-label={section}>
                <h2>{section}</h2>
                <div className="params-scroll">
                  <table className="params-table">
                    <thead>
                      <tr>
                        <th scope="col">Parameter</th>
                        <th scope="col">Value</th>
                        <th scope="col">Unit</th>
                        <th scope="col">Status</th>
                        <th scope="col">Source</th>
                        <th scope="col">As of</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(({ name, leaf }) => (
                        <tr key={leaf.path}>
                          <th scope="row" className="num">{name}</th>
                          <td className="num params-value">{show(leaf.value)}</td>
                          <td className="num">{leaf.unit}</td>
                          <td>
                            <span className={`status status-${leaf.status}`}>{STATUS_WORD[leaf.status]}</span>
                          </td>
                          <td>{leaf.source}</td>
                          <td className="num">{leaf.as_of}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </>
        )}
      </main>
    </>
  );
}
