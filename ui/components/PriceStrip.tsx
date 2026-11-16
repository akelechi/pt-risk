"use client";

import { useMemo, type PointerEvent } from "react";
import type { HourView } from "@/lib/api";
import { formatNumber } from "@/lib/format";

const PLOT_HEIGHT = 100; // viewBox units; the SVG is stretched, strokes do not scale
const TICK_STEPS_USD_PER_MWH = [10, 25, 50, 100, 250, 500, 1000];
const MAX_TICKS = 5;

type Scale = { low: number; high: number; ticks: number[] };

/** Axis range and ticks covering the plotted prices. Pixel scaling only; no engine value is altered. */
function priceScale(hours: HourView[]): Scale {
  let low = 0;
  let high = 1;
  for (const hour of hours) {
    low = Math.min(low, hour.da_lbmp_usd_per_mwh, hour.offer_min_price_usd_per_mwh ?? 0);
    high = Math.max(high, hour.da_lbmp_usd_per_mwh, hour.offer_max_price_usd_per_mwh ?? 0);
  }
  const step =
    TICK_STEPS_USD_PER_MWH.find((candidate) => (high - low) / candidate <= MAX_TICKS) ??
    TICK_STEPS_USD_PER_MWH[TICK_STEPS_USD_PER_MWH.length - 1];
  low = Math.floor(low / step) * step;
  high = Math.ceil(high / step) * step;
  const ticks: number[] = [];
  for (let tick = low; tick <= high; tick += step) ticks.push(tick);
  return { low, high, ticks };
}

/** Stepped path through hourly values: each hour is a flat segment one column wide. Gaps where the value is null. */
function stepPath(values: (number | null)[], y: (value: number) => number): string {
  const parts: string[] = [];
  let drawing = false;
  values.forEach((value, position) => {
    if (value === null) {
      drawing = false;
      return;
    }
    parts.push(`${drawing ? "L" : "M"}${position} ${y(value)}H${position + 1}`);
    drawing = true;
  });
  return parts.join("");
}

/**
 * DA LBMP against the unit's offer prices over the run, on the same hour axis as the
 * on/off strip below it. The unit runs where the LBMP line is above the offer line; the
 * filled area between them marks those hours. Every plotted value is an engine field.
 */
export function PriceStrip({ hours, index, onSelect }: { hours: HourView[]; index: number; onSelect: (index: number) => void }) {
  const plot = useMemo(() => {
    const scale = priceScale(hours);
    const y = (value: number) => PLOT_HEIGHT * (1 - (value - scale.low) / (scale.high - scale.low));
    const lbmp = hours.map((hour) => hour.da_lbmp_usd_per_mwh);
    const offerLow = hours.map((hour) => hour.offer_min_price_usd_per_mwh);
    const offerHigh = hours.map((hour) => hour.offer_max_price_usd_per_mwh);
    // Area between the first offer step and the LBMP, in the hours the engine committed the unit.
    const running = hours
      .map((hour, position) =>
        hour.committed && hour.offer_min_price_usd_per_mwh !== null
          ? `M${position} ${y(hour.offer_min_price_usd_per_mwh)}V${y(hour.da_lbmp_usd_per_mwh)}h1V${y(hour.offer_min_price_usd_per_mwh)}Z`
          : "",
      )
      .join("");
    const days: { position: number; label: string }[] = [];
    hours.forEach((hour, position) => {
      const day = hour.ts_local.slice(0, 10);
      if (position === 0 || day !== hours[position - 1].ts_local.slice(0, 10)) {
        days.push({ position, label: day.slice(8, 10) });
      }
    });
    return { scale, y, lbmpPath: stepPath(lbmp, y), offerLowPath: stepPath(offerLow, y), offerHighPath: stepPath(offerHigh, y), running, days };
  }, [hours]);

  const hour = hours[index];
  const select = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const position = Math.floor(((event.clientX - box.left) / box.width) * hours.length);
    onSelect(Math.max(0, Math.min(hours.length - 1, position)));
  };
  const offerText =
    hour.offer_min_price_usd_per_mwh === null || hour.offer_max_price_usd_per_mwh === null
      ? "none"
      : `${formatNumber(hour.offer_min_price_usd_per_mwh, "price")} – ${formatNumber(hour.offer_max_price_usd_per_mwh, "price")}`;
  const percent = (position: number) => `${(position / hours.length) * 100}%`;

  return (
    <section className="price-strip" aria-label="DA LBMP against the unit's offer prices over the run">
      <div className="price-head">
        <span className="price-title">DA price vs offer</span>
        <ul className="price-legend">
          <li>
            <svg width="28" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="28" y2="4" className="price-lbmp" />
            </svg>
            DA LBMP <span className="num price-value">{formatNumber(hour.da_lbmp_usd_per_mwh, "price")}</span>
            <span className="figure-unit">$/MWh</span>
          </li>
          <li>
            <svg width="28" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="28" y2="4" className="price-offer" />
            </svg>
            Offer, first to last step <span className="num price-value">{offerText}</span>
            <span className="figure-unit">$/MWh</span>
          </li>
          <li>
            <span className="price-swatch" aria-hidden="true" />
            unit running
          </li>
        </ul>
      </div>
      <div
        className="price-plot"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          select(event);
        }}
        onPointerMove={(event) => {
          if (event.buttons === 1) select(event);
        }}
      >
        <svg viewBox={`0 0 ${hours.length} ${PLOT_HEIGHT}`} preserveAspectRatio="none" role="img"
          aria-label={`DA LBMP ${formatNumber(hour.da_lbmp_usd_per_mwh, "price")} dollars per megawatt-hour, offer ${offerText}, unit ${hour.committed ? "running" : "off"}`}>
          {plot.scale.ticks.map((tick) => (
            <line key={tick} x1={0} x2={hours.length} y1={plot.y(tick)} y2={plot.y(tick)} className="price-grid" />
          ))}
          {plot.days.map((day) => (
            <line key={day.position} x1={day.position} x2={day.position} y1={0} y2={PLOT_HEIGHT} className="price-grid" />
          ))}
          <path d={plot.running} className="price-running" />
          <path d={plot.offerLowPath} className="price-offer" />
          <path d={plot.offerHighPath} className="price-offer" />
          <path d={plot.lbmpPath} className="price-lbmp" />
          <line x1={index + 0.5} x2={index + 0.5} y1={0} y2={PLOT_HEIGHT} className="price-cursor" />
        </svg>
        {plot.scale.ticks.map((tick) => (
          <span
            key={tick}
            className={`price-tick num${tick === plot.scale.high ? " top" : tick === plot.scale.low ? " bottom" : ""}`}
            style={{ top: `${plot.y(tick)}%` }}
          >
            {formatNumber(tick, "mmbtu")}
          </span>
        ))}
        <span className="price-axis-unit figure-unit">$/MWh</span>
      </div>
      <div className="price-days num" aria-hidden="true">
        {plot.days.map((day) => (
          <span key={day.position} style={{ left: percent(day.position) }}>
            {day.label}
          </span>
        ))}
      </div>
    </section>
  );
}
