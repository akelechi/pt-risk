import { Icon } from "./Icon";
import {
  ARROWS,
  NODES,
  VIEW_BOX,
  describeArrow,
  describeFigure,
  type Figure,
  type FlowArrow,
  type FlowNode,
} from "@/lib/flow-model";

const PLACEHOLDER = "—";
const LINE_HEIGHT = 17;
const STATE_OFFSETS = [0, 43, 88, 143];

function FigureText({ item, x, y, anchor }: { item: Figure; x: number; y: number; anchor: "start" | "middle" | "end" }) {
  return (
    <text x={x} y={y} textAnchor={anchor} className="figure">
      <tspan className="figure-label">{item.label}</tspan>
      <tspan dx={5} className={`figure-value ${item.kind}${item.value === null ? " empty" : ""}`}>
        {item.value ?? PLACEHOLDER}
      </tspan>
      <tspan dx={5} className="figure-unit">
        {item.unit}
      </tspan>
    </text>
  );
}

function NodeBox({ node }: { node: FlowNode }) {
  const label = [node.title, node.subtitle, ...node.figures.map((item) => `${item.label} ${describeFigure(item)}`)].join(", ");
  const isPlant = node.id === "plant";
  return (
    <g role="img" aria-label={label} className={`node node-${node.id}`}>
      <rect x={node.x} y={node.y} width={node.width} height={node.height} rx={3} className="node-box" />
      <line x1={node.x} y1={node.y + 36} x2={node.x + node.width} y2={node.y + 36} className="node-rule" />
      <g className="node-icon">
        <Icon name={node.icon} x={node.x + 10} y={node.y + 7} />
      </g>
      <text x={node.x + 40} y={node.y + 23} className="node-title">
        {node.title}
      </text>
      <text x={node.x + 12} y={node.y + 56} className="node-subtitle">
        {node.subtitle}
      </text>
      {isPlant && <PlantState node={node} />}
      {node.figures.map((item, index) => (
        <FigureText
          key={item.label}
          item={item}
          x={node.x + 12}
          y={node.y + (isPlant ? 132 : 84) + index * (isPlant ? 22 : 24)}
          anchor="start"
        />
      ))}
      {isPlant && (
        // inventory gauge: an empty outline until the engine supplies a level
        <rect x={node.x + 12} y={node.y + 172} width={node.width - 24} height={8} rx={1} className="gauge" />
      )}
    </g>
  );
}

/** State badge: off / hot / warm / cold, each with its own shape. None is lit in milestone 0. */
function PlantState({ node }: { node: FlowNode }) {
  const states: { name: string; shape: React.ReactNode }[] = [
    { name: "OFF", shape: <rect x={-5} y={-5} width={10} height={10} /> },
    { name: "HOT", shape: <path d="M0 -6 L6 5 H-6 Z" /> },
    { name: "WARM", shape: <path d="M0 -6 L6 0 L0 6 L-6 0 Z" /> },
    { name: "COLD", shape: <circle r={5.5} /> },
  ];
  return (
    <g className="state-row">
      {states.map((state, index) => (
        <g key={state.name} transform={`translate(${node.x + 20 + STATE_OFFSETS[index]} ${node.y + 82})`} className="state">
          {state.shape}
          <text x={10} y={4} className="state-name">
            {state.name}
          </text>
        </g>
      ))}
      <text x={node.x + 12} y={node.y + 108} className="node-subtitle">
        state {PLACEHOLDER} · fuel {PLACEHOLDER}
      </text>
    </g>
  );
}

function Arrow({ arrow }: { arrow: FlowArrow }) {
  return (
    <g role="img" aria-label={describeArrow(arrow)} className={`arrow ${arrow.kind}`}>
      <path d={arrow.path} className="arrow-line" markerEnd={`url(#head-${arrow.kind})`} />
      {arrow.figures.map((item, index) => (
        <FigureText
          key={item.label}
          item={item}
          x={arrow.labelX}
          y={arrow.labelY + index * LINE_HEIGHT}
          anchor={arrow.labelAnchor}
        />
      ))}
    </g>
  );
}

/** The wide layout: a fixed left-to-right diagram. */
function Diagram() {
  return (
    <svg
      className="flow-svg"
      viewBox={`0 0 ${VIEW_BOX.width} ${VIEW_BOX.height}`}
      role="group"
      aria-labelledby="flow-title"
    >
      <title id="flow-title">Flow of offers, bids, prices, dispatch and cash for one hour</title>
      <defs>
        {(["money", "physical"] as const).map((kind) => (
          <marker key={kind} id={`head-${kind}`} viewBox="0 0 10 10" refX={8} refY={5} markerWidth={8} markerHeight={8} orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 Z" className={`arrow-head ${kind}`} />
          </marker>
        ))}
      </defs>
      {ARROWS.map((arrow) => (
        <Arrow key={arrow.id} arrow={arrow} />
      ))}
      {NODES.map((node) => (
        <NodeBox key={node.id} node={node} />
      ))}
    </svg>
  );
}

/** The narrow layout: the same nodes and arrows, stacked in flow order. */
function Stacked() {
  const title = (id: string) => NODES.find((node) => node.id === id)?.title ?? id;
  return (
    <ol className="flow-stack" aria-label="Flow of offers, bids, prices, dispatch and cash for one hour">
      {ARROWS.map((arrow) => (
        <li key={arrow.id} className={`stack-item ${arrow.kind}`}>
          <div className="stack-route">
            <span>{title(arrow.from)}</span>
            <span className="stack-arrow" aria-hidden="true">
              →
            </span>
            <span>{title(arrow.to)}</span>
          </div>
          <dl>
            {arrow.figures.map((item) => (
              <div key={item.label} className="stack-figure">
                <dt>{item.label}</dt>
                <dd>
                  <span className={`figure-value ${item.kind}${item.value === null ? " empty" : ""}`}>
                    {item.value ?? PLACEHOLDER}
                  </span>{" "}
                  <span className="figure-unit">{item.unit}</span>
                </dd>
              </div>
            ))}
          </dl>
        </li>
      ))}
    </ol>
  );
}

export function FlowDiagram() {
  return (
    <section className="flow" aria-label="Flow diagram">
      <Diagram />
      <Stacked />
      <ul className="legend" aria-label="Legend">
        <li>
          <svg width="44" height="10" aria-hidden="true">
            <line x1="0" y1="5" x2="44" y2="5" className="arrow-line legend-money" />
          </svg>
          price or cash (dashed)
        </li>
        <li>
          <svg width="44" height="10" aria-hidden="true">
            <line x1="0" y1="5" x2="44" y2="5" className="arrow-line legend-physical" />
          </svg>
          physical quantity (solid)
        </li>
        <li>
          <span className="figure-value empty">{PLACEHOLDER}</span> placeholder: no engine value behind this figure yet
        </li>
      </ul>
    </section>
  );
}
