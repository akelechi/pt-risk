import type { IconName } from "@/lib/flow-model";

/** Simple 24 x 24 line icons. Stroke only; colour comes from `currentColor`. */
const PATHS: Record<IconName, string[]> = {
  // transmission tower: load-serving entities
  load: ["M12 3 L7 21", "M12 3 L17 21", "M5 9 H19", "M7.5 14 H16.5", "M9 9 L16.5 14", "M15 9 L7.5 14"],
  // price ticks crossing a level: a market clearing
  market: ["M4 20 V4", "M4 20 H20", "M7 15 L11 10 L14 13 L19 6", "M16 6 H19 V9"],
  // boiler house with stack
  plant: ["M3 21 H21", "M5 21 V11 H13 V21", "M13 21 V14 H19 V21", "M7 11 V4 H10 V11", "M7.5 15 H10.5"],
  // ruled page
  ledger: ["M6 3 H18 V21 H6 Z", "M9 8 H15", "M9 12 H15", "M9 16 H13"],
  // pipe with valve
  gas: ["M3 14 H9", "M15 14 H21", "M9 10 H15 V18 H9 Z", "M12 10 V6", "M9.5 6 H14.5"],
  // storage tank
  tank: ["M5 7 C5 4.5 19 4.5 19 7 V18 C19 20.5 5 20.5 5 18 Z", "M5 7 C5 9.5 19 9.5 19 7", "M5 13 C5 15.5 19 15.5 19 13"],
};

export function Icon({ name, x, y, size = 22 }: { name: IconName; x: number; y: number; size?: number }) {
  return (
    <g
      transform={`translate(${x} ${y}) scale(${size / 24})`}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </g>
  );
}
