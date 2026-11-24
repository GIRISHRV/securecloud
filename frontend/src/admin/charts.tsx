import { useEffect, useId, useRef, useState, type ReactNode } from "react";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => setWidth(node.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function niceMax(value: number, ticks = 4) {
  if (value <= 0) return ticks;
  const raw = value / ticks;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((candidate) => candidate >= raw) ?? raw;
  return step * ticks;
}

export type SeriesPoint = { label: string; value: number; detail?: ReactNode };

/** Single-series area chart with a crosshair tooltip. One axis, recessive grid. */
export function AreaChart({ points, format, height = 260, ariaLabel, threshold, fixedMax }: {
  points: SeriesPoint[]; format: (value: number) => string; height?: number; ariaLabel: string;
  threshold?: { value: number; label: string }; fixedMax?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const gradient = useId().replace(/:/g, "");
  const margin = { top: 14, right: 12, bottom: 28, left: 56 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = height - margin.top - margin.bottom;
  const max = fixedMax ?? niceMax(Math.max(0, threshold?.value ?? 0, ...points.map((point) => point.value)));
  const x = (index: number) => margin.left + (points.length <= 1 ? innerW / 2 : (index / (points.length - 1)) * innerW);
  const y = (value: number) => margin.top + innerH - (value / max) * innerH;
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
  const area = points.length ? `${line} L${x(points.length - 1).toFixed(1)},${margin.top + innerH} L${x(0).toFixed(1)},${margin.top + innerH} Z` : "";
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => max * ratio);
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(innerW / 70))));
  const active = hover !== null ? points[hover] : null;

  function move(clientX: number, rect: DOMRect) {
    if (!points.length || innerW <= 0) return;
    const ratio = (clientX - rect.left - margin.left) / innerW;
    setHover(Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1)))));
  }

  return (
    <div className="ad-chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}
          onMouseMove={(event) => move(event.clientX, event.currentTarget.getBoundingClientRect())}
          onMouseLeave={() => setHover(null)}>
          <defs>
            <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--ad-chart)" stopOpacity="0.22" />
              <stop offset="100%" stopColor="var(--ad-chart)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map((tick) => (
            <g key={tick}>
              <line className="ad-grid" x1={margin.left} x2={margin.left + innerW} y1={y(tick)} y2={y(tick)} />
              <text className="ad-axis" x={margin.left - 10} y={y(tick)} textAnchor="end" dominantBaseline="middle">{format(tick)}</text>
            </g>
          ))}
          {points.map((point, index) => (index % labelEvery === 0 || index === points.length - 1) && (
            <text key={point.label + index} className="ad-axis" x={x(index)} y={height - 8} textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"}>{point.label}</text>
          ))}
          <path d={area} fill={`url(#${gradient})`} />
          {threshold && (
            <g>
              <line className="ad-threshold" x1={margin.left} x2={margin.left + innerW} y1={y(threshold.value)} y2={y(threshold.value)} />
              <text className="ad-axis ad-threshold-label" x={margin.left + innerW} y={y(threshold.value) - 6} textAnchor="end">{threshold.label}</text>
            </g>
          )}
          <path d={line} className="ad-line" />
          {hover !== null && active && (
            <g>
              <line className="ad-crosshair" x1={x(hover)} x2={x(hover)} y1={margin.top} y2={margin.top + innerH} />
              <circle className="ad-dot" cx={x(hover)} cy={y(active.value)} r={5} />
            </g>
          )}
          {hover === null && points.length > 0 && (
            <circle className="ad-dot" cx={x(points.length - 1)} cy={y(points[points.length - 1].value)} r={4} />
          )}
        </svg>
      )}
      {active && hover !== null && (
        <div className="ad-tooltip" style={{ left: Math.min(Math.max(x(hover), 90), width - 90), top: Math.max(0, y(active.value) - 70) }}>
          <span>{active.label}</span>
          <strong>{format(active.value)}</strong>
          {active.detail && <small>{active.detail}</small>}
        </div>
      )}
    </div>
  );
}

/** Tiny trend line for KPI tiles. Decorative: the tile states the number. */
export function Sparkline({ values }: { values: number[] }) {
  const width = 120, height = 36;
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const pts = values.map((value, index) => [index * step, height - 3 - (value / max) * (height - 6)]);
  const line = pts.map(([px, py], index) => `${index ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg className="ad-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      {pts.length > 1 && <path d={`${line} L${width},${height} L0,${height} Z`} className="ad-spark-area" />}
      <path d={line} className="ad-spark-line" />
      {last && <circle cx={last[0]} cy={last[1]} r={2.5} className="ad-spark-dot" />}
    </svg>
  );
}

/** Horizontal bars for ranked or pipeline magnitudes; labels and values are text. */
export function BarList({ items, format = String }: {
  items: Array<{ key: string; label: ReactNode; value: number; hint?: string }>; format?: (value: number) => string;
}) {
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <ul className="ad-barlist">
      {items.map((item) => (
        <li key={item.key} title={item.hint}>
          <div className="ad-barlist-row"><span>{item.label}</span><strong>{format(item.value)}</strong></div>
          <div className="ad-barlist-track"><i style={{ width: `${(item.value / max) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}
