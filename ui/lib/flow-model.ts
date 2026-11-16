/**
 * The fixed shape of the flow diagram: nodes, and the arrows between them.
 *
 * This file holds geometry, labels and which engine field each figure shows. It contains
 * no values and no arithmetic: every number comes from the engine's flow payload. A figure
 * with no engine field behind it yet renders as a placeholder dash with its unit.
 */

import type { HourView } from "./api";
import { formatNumber, type NumberFormat } from "./format";

/** money = prices and dollars (amber, dashed); physical = MW, MMBtu, bbl (teal, solid). */
export type Kind = "money" | "physical";

/** Engine fields of an hour that hold a number (or null). */
export type NumericKey = {
  [K in keyof HourView]: HourView[K] extends number | null ? K : never;
}[keyof HourView];

export type Figure = {
  /** What the number is, e.g. "DA LBMP". */
  label: string;
  unit: string;
  kind: Kind;
  /** Engine field shown here; absent = no engine value exists for this figure yet. */
  field?: NumericKey;
  /** Second engine field, shown as the upper end of a range (e.g. an offer's last step). */
  fieldTo?: NumericKey;
  format: NumberFormat;
};

export type IconName = "load" | "market" | "plant" | "ledger" | "gas" | "tank";

export type FlowNode = {
  id: string;
  title: string;
  subtitle: string;
  icon: IconName;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Figures shown inside the node. */
  figures: Figure[];
};

export type FlowArrow = {
  id: string;
  from: string;
  to: string;
  /** SVG path, drawn in the 1280 x 620 viewBox. */
  path: string;
  /** Dominant kind: sets line style and arrow head. */
  kind: Kind;
  figures: Figure[];
  /** Where the label block sits. */
  labelX: number;
  labelY: number;
  labelAnchor: "start" | "middle" | "end";
  /** Milestone whose engine first puts a value on this arrow. */
  milestone: number;
};

export const VIEW_BOX = { width: 1280, height: 620 } as const;

const FORMAT_OF_UNIT: Record<string, NumberFormat> = {
  "$/MWh": "price", "$/MMBtu": "price", "$": "usd", "± $": "usd", MW: "mw", "± MW": "mw", MMBtu: "mmbtu", bbl: "mmbtu",
};

const figure = (label: string, unit: string, kind: Kind, field?: NumericKey, fieldTo?: NumericKey): Figure => ({
  label, unit, kind, field, fieldTo, format: FORMAT_OF_UNIT[unit],
});

export const NODES: FlowNode[] = [
  {
    id: "lse",
    title: "LSE BIDS",
    subtitle: "Load-serving entities",
    icon: "load",
    x: 10, y: 180, width: 130, height: 110,
    figures: [],
  },
  {
    id: "da_market",
    title: "DA MARKET",
    subtitle: "NYISO DA · price-taker",
    icon: "market",
    x: 230, y: 150, width: 160, height: 170,
    figures: [figure("DA LBMP", "$/MWh", "money", "da_lbmp_usd_per_mwh")],
  },
  {
    id: "plant",
    title: "PLANT",
    subtitle: "Roseton · Zone G",
    icon: "plant",
    x: 590, y: 130, width: 210, height: 210,
    figures: [figure("Output", "MW", "physical", "output_mw"), figure("Oil inventory", "bbl", "physical")],
  },
  {
    id: "rt_market",
    title: "RT MARKET",
    subtitle: "NYISO real-time",
    icon: "market",
    x: 910, y: 150, width: 140, height: 170,
    figures: [figure("RT LBMP", "$/MWh", "money")],
  },
  {
    id: "ledger",
    title: "LEDGER",
    subtitle: "This hour's lines",
    icon: "ledger",
    x: 1095, y: 110, width: 175, height: 250,
    figures: [
      figure("DA energy", "$", "money", "da_energy_rev_usd"),
      figure("RT balancing", "$", "money"),
      figure("Fuel", "$", "money", "fuel_cost_usd"),
      figure("VOM", "$", "money", "vom_usd"),
      figure("Start + no-load", "$", "money"),
      figure("Hour margin", "$", "money", "hour_energy_margin_usd"),
    ],
  },
  {
    id: "gas",
    title: "GAS",
    subtitle: "Henry Hub + basis",
    icon: "gas",
    x: 540, y: 480, width: 120, height: 100,
    figures: [],
  },
  {
    id: "oil",
    title: "OIL",
    subtitle: "Tank",
    icon: "tank",
    x: 730, y: 480, width: 120, height: 100,
    figures: [],
  },
];

export const ARROWS: FlowArrow[] = [
  {
    id: "lse_bids",
    from: "lse", to: "da_market",
    path: "M140 235 H222",
    kind: "physical",
    figures: [figure("Load bids", "MW", "physical")],
    labelX: 185, labelY: 208, labelAnchor: "middle",
    milestone: 1,
  },
  {
    id: "plant_offer",
    from: "plant", to: "da_market",
    path: "M590 195 H398",
    kind: "money",
    figures: [
      figure("Offer", "$/MWh", "money", "offer_min_price_usd_per_mwh", "offer_max_price_usd_per_mwh"),
      figure("Offered", "MW", "physical", "offered_mw"),
    ],
    labelX: 490, labelY: 168, labelAnchor: "middle",
    milestone: 1,
  },
  {
    id: "da_lbmp",
    from: "da_market", to: "plant",
    path: "M390 275 H582",
    kind: "money",
    figures: [figure("DA LBMP", "$/MWh", "money", "da_lbmp_usd_per_mwh"), figure("DA schedule", "MW", "physical", "da_schedule_mw")],
    labelX: 490, labelY: 300, labelAnchor: "middle",
    milestone: 1,
  },
  {
    id: "rt_deviation",
    from: "plant", to: "rt_market",
    path: "M800 235 H902",
    kind: "physical",
    figures: [figure("Deviation", "± MW", "physical")],
    labelX: 855, labelY: 208, labelAnchor: "middle",
    milestone: 3,
  },
  {
    id: "rt_balancing",
    from: "rt_market", to: "ledger",
    path: "M980 320 V398 Q980 410 992 410 H1170 Q1182 410 1182 398 V368",
    kind: "money",
    figures: [figure("RT balancing", "± $", "money")],
    labelX: 1081, labelY: 434, labelAnchor: "middle",
    milestone: 3,
  },
  {
    id: "da_energy_rev",
    from: "da_market", to: "ledger",
    path: "M310 150 V74 Q310 62 322 62 H1170 Q1182 62 1182 74 V102",
    kind: "money",
    figures: [figure("DA energy revenue", "$", "money", "da_energy_rev_usd")],
    labelX: 746, labelY: 46, labelAnchor: "middle",
    milestone: 1,
  },
  {
    id: "gas_supply",
    from: "gas", to: "plant",
    path: "M600 480 V412 Q600 400 612 400 H638 Q650 400 650 388 V348",
    kind: "money",
    figures: [figure("Gas, assumed basis", "$/MMBtu", "money", "gas_price_usd_per_mmbtu"), figure("Gas burn", "MMBtu", "physical", "gas_burn_mmbtu")],
    labelX: 586, labelY: 392, labelAnchor: "end",
    milestone: 1,
  },
  {
    id: "oil_supply",
    from: "oil", to: "plant",
    path: "M790 480 V412 Q790 400 778 400 H752 Q740 400 740 388 V348",
    kind: "money",
    figures: [figure("Oil", "$/MMBtu", "money"), figure("Oil burn", "MMBtu", "physical")],
    labelX: 804, labelY: 430, labelAnchor: "start",
    milestone: 4,
  },
];

export const PLACEHOLDER = "—";

/** The figure's value as text, or null when the engine has no value for it (yet, or this hour). */
export function figureValue(item: Figure, hour: HourView | null): string | null {
  if (hour === null || item.field === undefined) return null;
  const from = hour[item.field];
  if (from === null) return null;
  const to = item.fieldTo === undefined ? null : hour[item.fieldTo];
  if (to !== null && to !== from) {
    return `${formatNumber(from, item.format)} – ${formatNumber(to, item.format)}`;
  }
  return formatNumber(from, item.format);
}

export function describeFigure(item: Figure, hour: HourView | null): string {
  const value = figureValue(item, hour);
  return value === null ? `no value yet (${item.unit})` : `${value} ${item.unit}`;
}

/** Text for screen readers: names the arrow and its current values. */
export function describeArrow(arrow: FlowArrow, hour: HourView | null, nodes: FlowNode[] = NODES): string {
  const title = (id: string) => nodes.find((node) => node.id === id)?.title ?? id;
  const values = arrow.figures.map((item) => `${item.label} ${describeFigure(item, hour)}`).join(", ");
  return `${title(arrow.from)} to ${title(arrow.to)}: ${values}`;
}
