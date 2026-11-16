/**
 * The fixed shape of the flow diagram: nodes, and the arrows between them.
 *
 * This file holds geometry and labels only. It contains no values: every figure on an
 * arrow comes from the engine (the `/runs/{id}/hour/{ts}` payload from milestone 1).
 * Until then a figure is `null` and renders as a placeholder dash with its unit.
 */

/** money = prices and dollars (amber, dashed); physical = MW, MMBtu, bbl (teal, solid). */
export type Kind = "money" | "physical";

export type Figure = {
  /** What the number is, e.g. "DA LBMP". */
  label: string;
  unit: string;
  kind: Kind;
  /** Formatted by the engine's payload later; null = no engine value yet. */
  value: string | null;
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

const figure = (label: string, unit: string, kind: Kind): Figure => ({ label, unit, kind, value: null });

export const NODES: FlowNode[] = [
  {
    id: "lse",
    title: "LSE BIDS",
    subtitle: "Load-serving entities",
    icon: "load",
    x: 20, y: 180, width: 130, height: 110,
    figures: [],
  },
  {
    id: "da_market",
    title: "DA MARKET",
    subtitle: "NYISO day-ahead · price-taker",
    icon: "market",
    x: 250, y: 150, width: 170, height: 170,
    figures: [figure("DA LBMP", "$/MWh", "money")],
  },
  {
    id: "plant",
    title: "PLANT",
    subtitle: "Roseton · Zone G",
    icon: "plant",
    x: 540, y: 130, width: 210, height: 210,
    figures: [figure("Output", "MW", "physical"), figure("Oil inventory", "bbl", "physical")],
  },
  {
    id: "rt_market",
    title: "RT MARKET",
    subtitle: "NYISO real-time",
    icon: "market",
    x: 870, y: 150, width: 150, height: 170,
    figures: [figure("RT LBMP", "$/MWh", "money")],
  },
  {
    id: "ledger",
    title: "LEDGER",
    subtitle: "This hour's lines",
    icon: "ledger",
    x: 1100, y: 110, width: 160, height: 250,
    figures: [
      figure("DA energy", "$", "money"),
      figure("RT balancing", "$", "money"),
      figure("Fuel", "$", "money"),
      figure("Start + no-load", "$", "money"),
    ],
  },
  {
    id: "gas",
    title: "GAS",
    subtitle: "Henry + basis",
    icon: "gas",
    x: 500, y: 480, width: 120, height: 100,
    figures: [],
  },
  {
    id: "oil",
    title: "OIL",
    subtitle: "Tank",
    icon: "tank",
    x: 670, y: 480, width: 120, height: 100,
    figures: [],
  },
];

export const ARROWS: FlowArrow[] = [
  {
    id: "lse_bids",
    from: "lse", to: "da_market",
    path: "M150 235 H242",
    kind: "physical",
    figures: [figure("Load bids", "MW", "physical")],
    labelX: 198, labelY: 208, labelAnchor: "middle",
    milestone: 1,
  },
  {
    id: "plant_offer",
    from: "plant", to: "da_market",
    path: "M540 195 H428",
    kind: "money",
    figures: [figure("Plant offer", "$/MWh", "money"), figure("Offered", "MW", "physical")],
    labelX: 482, labelY: 152, labelAnchor: "middle",
    milestone: 1,
  },
  {
    id: "da_lbmp",
    from: "da_market", to: "plant",
    path: "M420 275 H532",
    kind: "money",
    figures: [figure("DA LBMP", "$/MWh", "money"), figure("DA schedule", "MW", "physical")],
    labelX: 478, labelY: 300, labelAnchor: "middle",
    milestone: 1,
  },
  {
    id: "rt_deviation",
    from: "plant", to: "rt_market",
    path: "M750 235 H862",
    kind: "physical",
    figures: [figure("Deviation", "± MW", "physical")],
    labelX: 808, labelY: 208, labelAnchor: "middle",
    milestone: 3,
  },
  {
    id: "rt_balancing",
    from: "rt_market", to: "ledger",
    path: "M945 320 V398 Q945 410 957 410 H1168 Q1180 410 1180 398 V368",
    kind: "money",
    figures: [figure("RT balancing", "± $", "money")],
    labelX: 1062, labelY: 434, labelAnchor: "middle",
    milestone: 3,
  },
  {
    id: "da_energy_rev",
    from: "da_market", to: "ledger",
    path: "M335 150 V74 Q335 62 347 62 H1168 Q1180 62 1180 74 V102",
    kind: "money",
    figures: [figure("DA energy revenue", "$", "money")],
    labelX: 757, labelY: 30, labelAnchor: "middle",
    milestone: 1,
  },
  {
    id: "gas_supply",
    from: "gas", to: "plant",
    path: "M560 480 V412 Q560 400 572 400 H588 Q600 400 600 388 V348",
    kind: "money",
    figures: [figure("Delivered gas", "$/MMBtu", "money"), figure("Gas burn", "MMBtu", "physical")],
    labelX: 486, labelY: 392, labelAnchor: "end",
    milestone: 1,
  },
  {
    id: "oil_supply",
    from: "oil", to: "plant",
    path: "M730 480 V412 Q730 400 718 400 H702 Q690 400 690 388 V348",
    kind: "money",
    figures: [figure("Oil", "$/MMBtu", "money"), figure("Oil burn", "MMBtu", "physical")],
    labelX: 804, labelY: 392, labelAnchor: "start",
    milestone: 4,
  },
];

/** Text for screen readers: names the arrow and its current values. */
export function describeArrow(arrow: FlowArrow, nodes: FlowNode[] = NODES): string {
  const title = (id: string) => nodes.find((node) => node.id === id)?.title ?? id;
  const values = arrow.figures.map((item) => `${item.label} ${describeFigure(item)}`).join(", ");
  return `${title(arrow.from)} to ${title(arrow.to)}: ${values}`;
}

export function describeFigure(item: Figure): string {
  return item.value === null ? `no value yet (${item.unit})` : `${item.value} ${item.unit}`;
}
