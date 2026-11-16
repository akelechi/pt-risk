import type { ReactNode } from "react";
import { Icon } from "./Icon";
import type { HourView } from "@/lib/api";
import {
  NODES,
  PLACEHOLDER,
  VIEW_BOX,
  arrowsFor,
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
  // A price ($/MWh, $/MMBtu) is a label, not a flow: it takes the text color (docs/brand.md §2).
  const role = item.unit.startsWith("$/") ? "price" : item.kind;
  return `figure-value ${role}${value === null ? " empty" : ""}`;
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
  const plantText = isPlant && hour
    ? `${hour.forced_outage ? "forced outage, " : ""}${hour.committed ? "on" : "off"}, thermal state ${hour.thermal_state}, fuel ${hour.fuel ?? "none"}`
    : null;
  const label = [node.title, node.subtitle, plantText, ...node.figures.map((item) => `${item.label} ${describeFigure(item, hour)}`)]
    .filter(Boolean)
    .join(", ");
  const outage = isPlant && hour?.forced_outage === true;
  const lit = (isPlant && hour?.committed ? " on" : "") + (outage ? " outage" : "");
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
      {outage && (
        // outage marker: a crossed box and the word, so it does not rely on colour
        <g className="outage-mark" transform={`translate(${node.x + node.width - 96} ${node.y + 10})`}>
          <rect width={86} height={18} rx={2} />
          <path d="M5 5 L13 13 M13 5 L5 13" />
          <text x={19} y={13}>OUTAGE</text>
        </g>
      )}
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
        // inventory gauge: outline = tank capacity, fill = the engine's fill fraction
        <g>
          <rect x={node.x + 12} y={node.y + 172} width={node.width - 24} height={8} rx={1} className="gauge" />
          {hour?.oil_inventory_fill_fraction != null && (
            <rect
              x={node.x + 12} y={node.y + 172} height={8} rx={1} className="gauge-fill"
              width={(node.width - 24) * Math.max(0, Math.min(1, hour.oil_inventory_fill_fraction))}
            />
          )}
        </g>
      )}
      {isPlant && <FuelSwitch node={node} hour={hour} />}
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
          className={`state state-${state.name.toLowerCase()}${state.active ? " active" : ""}`}
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

/**
 * Fuel switch indicator: which fuel the unit is burning this hour. Flame = gas, drop = oil;
 * the one in use is filled and bold, so it reads without colour.
 */
function FuelSwitch({ node, hour }: { node: FlowNode; hour: HourView | null }) {
  const fuels: { name: "gas" | "oil"; shape: ReactNode }[] = [
    { name: "gas", shape: <path d="M0 -6 C4 -2 5 1 5 3 A5 5 0 0 1 -5 3 C-5 1 -4 -2 0 -6 Z" /> },
    { name: "oil", shape: <rect x={-5} y={-5} width={10} height={10} rx={5} /> },
  ];
  return (
    <g className="fuel-switch">
      <text x={node.x + 12} y={node.y + 200} className="state-name">
        FUEL
      </text>
      {fuels.map((item, index) => (
        <g key={item.name} transform={`translate(${node.x + 58 + index * 52} ${node.y + 196})`}
          className={`state fuel-${item.name}${hour?.fuel === item.name ? " active" : ""}`}>
          {item.shape}
          <text x={10} y={4} className="state-name">
            {item.name.toUpperCase()}
          </text>
        </g>
      ))}
    </g>
  );
}

const SUPPLY_FUEL: Record<string, "gas" | "oil"> = { gas_supply: "gas", oil_supply: "oil" };

function Arrow({ arrow, hour }: { arrow: FlowArrow; hour: HourView | null }) {
  const supplies = SUPPLY_FUEL[arrow.id];
  const burning = supplies !== undefined && hour?.fuel ? (hour.fuel === supplies ? " burning" : " idle") : "";
  return (
    <g role="img" aria-label={describeArrow(arrow, hour)} className={`arrow ${arrow.kind}${burning}${arrow.note ? " unmodeled" : ""}`}>
      <path d={arrow.path} className="arrow-line" markerEnd={`url(#head-${arrow.kind})`} />
      {arrow.note && (
        <text x={arrow.labelX} y={arrow.labelY} textAnchor={arrow.labelAnchor} className="figure figure-note">
          {arrow.note}
        </text>
      )}
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
      {arrowsFor(hour).map((arrow) => (
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
                {hour.forced_outage ? "FORCED OUTAGE · " : ""}
                {hour.committed ? "ON" : "OFF"} · {hour.thermal_state.toUpperCase()} · fuel {hour.fuel ?? "none"}
              </dd>
            </div>
          </dl>
        </li>
      )}
      {arrowsFor(hour).map((arrow) => (
        <li key={arrow.id} className={`stack-item ${arrow.kind}`}>
          <div className="stack-route">
            <span>{title(arrow.from)}</span>
            <span className="stack-arrow" aria-hidden="true">
              →
            </span>
            <span>{title(arrow.to)}</span>
          </div>
          <dl>
            {arrow.note && <div className="stack-figure stack-note">{arrow.note}</div>}
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
