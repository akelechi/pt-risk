import type { ReactNode } from "react";
import { Icon } from "./Icon";
import type { HourView } from "@/lib/api";
import {
  ARROWS,
  NODES,
  PLACEHOLDER,
  VIEW_BOX,
  describeArrow,
  describeFigure,
  figureValue,
  type Figure,
  type FlowArrow,
  type FlowNode,
} from "@/lib/flow-model";

const LINE_HEIGHT = 17;
const STATE_OFFSETS = [0, 43, 88, 143];

function valueClass(item: Figure, value: string | null): string {
  return `figure-value ${item.kind}${value === null ? " empty" : ""}`;
}

function FigureText({ item, hour, x, y, anchor }: {
  item: Figure; hour: HourView | null; x: number; y: number; anchor: "start" | "middle" | "end";
}) {
  const value = figureValue(item, hour);
  return (
    <text x={x} y={y} textAnchor={anchor} className="figure">
      <tspan className="figure-label">{item.label}</tspan>
      <tspan dx={5} className={valueClass(item, value)}>
        {value ?? PLACEHOLDER}
      </tspan>
      <tspan dx={5} className="figure-unit">
        {item.unit}
      </tspan>
    </text>
  );
}

function NodeBox({ node, hour }: { node: FlowNode; hour: HourView | null }) {
  const isPlant = node.id === "plant";
  const plantText = isPlant && hour ? `${hour.committed ? "on" : "off"}, thermal state ${hour.thermal_state}, fuel ${hour.fuel ?? "none"}` : null;
  const label = [node.title, node.subtitle, plantText, ...node.figures.map((item) => `${item.label} ${describeFigure(item, hour)}`)]
    .filter(Boolean)
    .join(", ");
  const lit = isPlant && hour?.committed ? " on" : "";
  return (
    <g role="img" aria-label={label} className={`node node-${node.id}${lit}`}>
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
      {isPlant && <PlantState node={node} hour={hour} />}
      {node.figures.map((item, index) => (
        <FigureText
          key={item.label}
          item={item}
          hour={hour}
          x={node.x + 12}
          y={node.y + (isPlant ? 132 : 84) + index * (isPlant ? 22 : 24)}
          anchor="start"
        />
      ))}
      {isPlant && (
        // inventory gauge: an empty outline until the engine supplies a level (milestone 4)
        <rect x={node.x + 12} y={node.y + 172} width={node.width - 24} height={8} rx={1} className="gauge" />
      )}
    </g>
  );
}

/**
 * State badge. Each state has its own shape, so it reads without colour:
 * square = on/off (filled when on), triangle = hot, diamond = warm, circle = cold.
 */
function PlantState({ node, hour }: { node: FlowNode; hour: HourView | null }) {
  const states: { name: string; active: boolean; shape: ReactNode }[] = [
    { name: hour?.committed ? "ON" : "OFF", active: hour?.committed ?? false, shape: <rect x={-5} y={-5} width={10} height={10} /> },
    { name: "HOT", active: hour?.thermal_state === "hot", shape: <path d="M0 -6 L6 5 H-6 Z" /> },
    { name: "WARM", active: hour?.thermal_state === "warm", shape: <path d="M0 -6 L6 0 L0 6 L-6 0 Z" /> },
    { name: "COLD", active: hour?.thermal_state === "cold", shape: <circle r={5.5} /> },
  ];
  return (
    <g className="state-row">
      {states.map((state, index) => (
        <g
          key={index}
          transform={`translate(${node.x + 20 + STATE_OFFSETS[index]} ${node.y + 82})`}
          className={`state${state.active ? " active" : ""}`}
        >
          {state.shape}
          <text x={10} y={4} className="state-name">
            {state.name}
          </text>
        </g>
      ))}
      <text x={node.x + 12} y={node.y + 108} className="node-subtitle">
        {hour
          ? `${hour.unit_id} · fuel ${hour.fuel ?? "none"} · available ${hour.available_mw} MW`
          : `state ${PLACEHOLDER} · fuel ${PLACEHOLDER}`}
      </text>
    </g>
  );
}

function Arrow({ arrow, hour }: { arrow: FlowArrow; hour: HourView | null }) {
  return (
    <g role="img" aria-label={describeArrow(arrow, hour)} className={`arrow ${arrow.kind}`}>
      <path d={arrow.path} className="arrow-line" markerEnd={`url(#head-${arrow.kind})`} />
      {arrow.figures.map((item, index) => (
        <FigureText
          key={item.label}
          item={item}
          hour={hour}
          x={arrow.labelX}
          y={arrow.labelY + index * LINE_HEIGHT}
          anchor={arrow.labelAnchor}
        />
      ))}
    </g>
  );
}

/** The wide layout: a fixed left-to-right diagram. */
function Diagram({ hour }: { hour: HourView | null }) {
  return (
    <svg className="flow-svg" viewBox={`0 0 ${VIEW_BOX.width} ${VIEW_BOX.height}`} role="group" aria-labelledby="flow-title">
      <title id="flow-title">Flow of offers, bids, prices, dispatch and cash for one hour</title>
      <defs>
        {(["money", "physical"] as const).map((kind) => (
          <marker key={kind} id={`head-${kind}`} viewBox="0 0 10 10" refX={8} refY={5} markerWidth={8} markerHeight={8} orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 Z" className={`arrow-head ${kind}`} />
          </marker>
        ))}
      </defs>
      {ARROWS.map((arrow) => (
        <Arrow key={arrow.id} arrow={arrow} hour={hour} />
      ))}
      {NODES.map((node) => (
        <NodeBox key={node.id} node={node} hour={hour} />
      ))}
    </svg>
  );
}

/** The narrow layout: the same nodes and arrows, stacked in flow order. */
function Stacked({ hour }: { hour: HourView | null }) {
  const title = (id: string) => NODES.find((node) => node.id === id)?.title ?? id;
  return (
    <ol className="flow-stack" aria-label="Flow of offers, bids, prices, dispatch and cash for one hour">
      {hour && (
        <li className={`stack-item stack-plant${hour.committed ? " on" : ""}`}>
          <div className="stack-route">
            <span>PLANT {hour.unit_id}</span>
          </div>
          <dl>
            <div className="stack-figure">
              <dt>State</dt>
              <dd>
                {hour.committed ? "ON" : "OFF"} · {hour.thermal_state.toUpperCase()} · fuel {hour.fuel ?? "none"}
              </dd>
            </div>
          </dl>
        </li>
      )}
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
            {arrow.figures.map((item) => {
              const value = figureValue(item, hour);
              return (
                <div key={item.label} className="stack-figure">
                  <dt>{item.label}</dt>
                  <dd>
                    <span className={valueClass(item, value)}>{value ?? PLACEHOLDER}</span>{" "}
                    <span className="figure-unit">{item.unit}</span>
                  </dd>
                </div>
              );
            })}
          </dl>
        </li>
      ))}
    </ol>
  );
}

/** The flow diagram for one hour. `hour = null` renders every figure as a placeholder. */
export function FlowDiagram({ hour }: { hour: HourView | null }) {
  return (
    <section className="flow" aria-label="Flow diagram">
      <Diagram hour={hour} />
      <Stacked hour={hour} />
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
        <li>(1,350.00) = negative · costs are negative in the ledger</li>
        <li>
          <span className="figure-value empty">{PLACEHOLDER}</span> no engine value behind this figure yet
        </li>
      </ul>
    </section>
  );
}
