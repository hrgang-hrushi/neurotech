'use client';

import React, { useId, useMemo } from 'react';
import type { Artifact, DecodeResult, MorseElement } from '@/lib/recordingApi';

interface ActivationTraceProps {
  trace: DecodeResult['trace'];
  elements: MorseElement[];
  artifacts: Artifact[];
  durationS: number;
}

const WIDTH = 1000;
const HEIGHT = 220;
const PAD = { top: 12, right: 12, bottom: 26, left: 44 };
const PLOT_W = WIDTH - PAD.left - PAD.right;
const PLOT_H = HEIGHT - PAD.top - PAD.bottom;
const X_TICKS = 6;

interface Scales { x: (t: number) => number; y: (v: number) => number; t0: number; t1: number; v0: number; v1: number }

function buildScales(trace: DecodeResult['trace'], durationS: number): Scales | null {
  const { t, activation, lo, hi } = trace;
  if (t.length < 2) return null;
  const t0 = t[0];
  const last = t[t.length - 1];
  // Prefer the reported duration when it extends past the trace; never collapse to zero width.
  const t1 = Math.max(last, durationS > last ? durationS : last, t0 + 1e-3);
  const limits = [lo, hi].filter((v): v is number => v !== null);
  let v0 = Math.min(...limits, activation[0]);
  let v1 = Math.max(...limits, activation[0]);
  for (const v of activation) {
    if (v < v0) v0 = v;
    if (v > v1) v1 = v;
  }
  const pad = (v1 - v0) * 0.06 || 1;
  v0 -= pad;
  v1 += pad;
  const span = t1 - t0 || 1;
  return {
    x: (tt) => PAD.left + ((tt - t0) / span) * PLOT_W,
    y: (v) => PAD.top + (1 - (v - v0) / (v1 - v0)) * PLOT_H,
    t0, t1, v0, v1,
  };
}

function linePath(trace: DecodeResult['trace'], s: Scales): string {
  return trace.t
    .map((tt, i) => `${i === 0 ? 'M' : 'L'}${s.x(tt).toFixed(1)},${s.y(trace.activation[i]).toFixed(1)}`)
    .join('');
}

/** Activation over time with thresholds, key-down spans and removed artifacts. */
export function ActivationTrace({ trace, elements, artifacts, durationS }: ActivationTraceProps) {
  const hatchId = useId().replace(/:/g, '');
  const scales = useMemo(() => buildScales(trace, durationS), [trace, durationS]);
  const path = useMemo(() => (scales ? linePath(trace, scales) : ''), [trace, scales]);

  if (!scales) {
    return (
      <div className="ds-empty text-sm text-[var(--ds-text-muted)] py-10 text-center">
        No activation trace was returned for this recording.
      </div>
    );
  }

  const ticks = Array.from({ length: X_TICKS }, (_, i) => scales.t0 + ((scales.t1 - scales.t0) * i) / (X_TICKS - 1));
  const tickDecimals = tickPrecision(scales.t1 - scales.t0);
  const inView = (a: number, b: number) => b >= scales.t0 && a <= scales.t1;
  const span = (a: number, b: number) => ({
    x: scales.x(Math.max(a, scales.t0)),
    w: Math.max(1, scales.x(Math.min(b, scales.t1)) - scales.x(Math.max(a, scales.t0))),
  });
  const removed = artifacts.filter((a) => inView(a.t_on, a.t_off));
  const shownElements = elements.filter((e) => inView(e.t_on, e.t_off));
  const thresholds = [
    { v: trace.hi, label: 'on' },
    { v: trace.lo, label: 'off' },
  ].filter((th): th is { v: number; label: string } => th.v !== null);

  return (
    <figure className="w-full">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full h-auto"
        role="img"
        aria-label={`Activation trace over ${durationS.toFixed(1)} seconds with ${elements.length} key-downs and ${removed.length} removed artifacts`}
      >
        <defs>
          <pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--ds-status-error)" fillOpacity="0.08" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ds-status-error)" strokeOpacity="0.55" strokeWidth="2" />
          </pattern>
        </defs>

        {ticks.map((tt, i) => (
          <g key={i}>
            <line x1={scales.x(tt)} x2={scales.x(tt)} y1={PAD.top} y2={PAD.top + PLOT_H} stroke="var(--chart-grid)" />
            <text x={scales.x(tt)} y={HEIGHT - 8} textAnchor="middle" fontSize="11" fill="var(--ds-text-muted)">
              {tt.toFixed(tickDecimals)}s
            </text>
          </g>
        ))}

        {removed.map((a, i) => {
          const { x, w } = span(a.t_on, a.t_off);
          return (
            <rect key={`a${i}`} x={x} y={PAD.top} width={w} height={PLOT_H} fill={`url(#${hatchId})`}>
              <title>{`${a.kind.replace('_', ' ')}${a.channel ? ` on ${a.channel}` : ''} removed, ${a.t_on.toFixed(2)}–${a.t_off.toFixed(2)} s`}</title>
            </rect>
          );
        })}

        {shownElements.map((e, i) => {
          const { x, w } = span(e.t_on, e.t_off);
          const isDash = e.symbol === '-';
          return (
            <rect
              key={`e${i}`}
              x={x}
              y={PAD.top + PLOT_H - 10}
              width={w}
              height={10}
              rx={2}
              fill={isDash ? 'var(--ds-status-warning)' : 'var(--ds-chart-blue)'}
              fillOpacity={0.85}
            >
              <title>{`${isDash ? 'dash' : 'dot'} ${(e.t_off - e.t_on).toFixed(2)} s at ${e.t_on.toFixed(2)} s`}</title>
            </rect>
          );
        })}

        {thresholds.map(({ v, label }) => (
          <g key={label}>
            <line
              x1={PAD.left}
              x2={PAD.left + PLOT_W}
              y1={scales.y(v)}
              y2={scales.y(v)}
              stroke="var(--ds-text-muted)"
              strokeDasharray="4 4"
              strokeWidth="1"
            />
            <text x={PAD.left - 6} y={scales.y(v) + 4} textAnchor="end" fontSize="11" fill="var(--ds-text-muted)">
              {label}
            </text>
          </g>
        ))}

        <path d={path} fill="none" stroke="var(--chart-line-primary)" strokeWidth="1.4" strokeLinejoin="round" />
      </svg>

      <figcaption className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-[var(--ds-text-muted)]">
        <LegendSwatch className="bg-[var(--ds-chart-blue)]" label="Dot (short clench)" />
        <LegendSwatch className="bg-[var(--ds-status-warning)]" label="Dash (long clench)" />
        <LegendSwatch className="border border-[var(--ds-status-error)] bg-[var(--ds-status-error)]/20" label="Removed artifact" />
        <span>Dashed lines: on/off thresholds</span>
      </figcaption>
    </figure>
  );
}

/** Enough decimals that 6 evenly spaced tick labels don't repeat. */
function tickPrecision(spanS: number): number {
  const step = spanS / (X_TICKS - 1);
  if (step >= 1) return 0;
  if (step >= 0.1) return 1;
  return 2;
}

function LegendSwatch({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-3 h-2.5 rounded-[2px] ${className}`} aria-hidden="true" />
      {label}
    </span>
  );
}
