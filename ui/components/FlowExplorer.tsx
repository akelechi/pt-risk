"use client";

import { useEffect, useState } from "react";
import { FlowDiagram } from "./FlowDiagram";
import { PriceStrip } from "./PriceStrip";
import type { HourView } from "@/lib/api";
import { formatHour } from "@/lib/format";

const PLAY_INTERVAL_MS = 100; // one hour per 100 ms

/**
 * Hour scrubber over one unit's hours. Holds only which hour is selected and whether it
 * is playing; every figure shown comes from the engine's payload for that hour.
 * `initialIndex` lets a URL open on a given hour (`?hour=N`, zero-based).
 */
export function FlowExplorer({ hours, initialIndex = 0 }: { hours: HourView[]; initialIndex?: number }) {
  const [index, setIndex] = useState(Math.max(0, Math.min(hours.length - 1, initialIndex)));
  const [playing, setPlaying] = useState(false);
  const last = hours.length - 1;
  const hour = hours[Math.min(index, last)];

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setIndex((current) => {
        if (current >= last) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, PLAY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [playing, last]);

  const step = (delta: number) => {
    setPlaying(false);
    setIndex((current) => Math.max(0, Math.min(last, current + delta)));
  };

  const label = formatHour(hour.ts_utc);

  return (
    <>
      <FlowDiagram hour={hour} />
      <p className="decision">
        <span className="decision-label">Decision</span> {hour.reason}
      </p>
      <div className="scrubber" role="group" aria-label="Hour scrubber">
        <div className="scrubber-buttons">
          <button type="button" onClick={() => step(-1)} disabled={index === 0} aria-label="Previous hour">
            ◀
          </button>
          <button
            type="button"
            className="play"
            onClick={() => {
              if (!playing && index >= last) setIndex(0);
              setPlaying(!playing);
            }}
            aria-pressed={playing}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button type="button" onClick={() => step(1)} disabled={index === last} aria-label="Next hour">
            ▶
          </button>
        </div>
        <input
          className="scrubber-range"
          type="range"
          min={0}
          max={last}
          step={1}
          value={index}
          onChange={(event) => {
            setPlaying(false);
            setIndex(Number(event.target.value));
          }}
          aria-label="Hour"
          aria-valuetext={label}
        />
        <output className="scrubber-time num" aria-live="off">
          {label}
        </output>
        <span className="scrubber-count num">
          hour {index + 1} of {hours.length}
        </span>
      </div>
      <PriceStrip
        hours={hours}
        index={Math.min(index, last)}
        onSelect={(position) => {
          setPlaying(false);
          setIndex(position);
        }}
      />
      {/* On/off strip: one tick per hour, tall where the unit runs; the selected hour is marked. */}
      <svg className="strip" viewBox={`0 0 ${hours.length} 12`} preserveAspectRatio="none" aria-hidden="true">
        {hours.map((item, position) =>
          item.committed ? <rect key={position} x={position} y={0} width={1} height={12} className="strip-on" /> : null,
        )}
        <rect x={index} y={0} width={1} height={12} className="strip-cursor" />
      </svg>
    </>
  );
}
