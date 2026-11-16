import { FlowDiagram } from "@/components/FlowDiagram";
import { Header } from "@/components/Header";
import { fetchParams } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function FlowPage() {
  const engine = await fetchParams();
  return (
    <>
      <Header engine={engine} screen="Flow" />
      <main className="page">
        <div className="page-head">
          <h1>One hour of the plant</h1>
          <p>
            Static shell. The diagram is fixed; every figure is a placeholder until the engine behind it has a
            passing test.
          </p>
        </div>
        <FlowDiagram />
      </main>
    </>
  );
}
