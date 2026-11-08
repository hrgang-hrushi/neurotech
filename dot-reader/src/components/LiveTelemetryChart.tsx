'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  LiveLineChart,
  LiveLine,
  ChartTooltip,
  LiveXAxis,
  LiveYAxis,
} from '@bklitui/ui/charts';
import { Waves, Play, Pause } from 'lucide-react';

export function LiveTelemetryChart() {
  const [data, setData] = useState<{ time: number; value: number }[]>([]);
  const [currentVal, setCurrentVal] = useState<number>(14.2);
  const [paused, setPaused] = useState<boolean>(false);
  const [channel, setChannel] = useState<'C3 (Left Motor)' | 'C4 (Right Motor)'>('C3 (Left Motor)');

  const baseVoltageRef = useRef(14.0);
  const phaseRef = useRef(0);

  // Initialize with 30 seconds of historical streaming points
  useEffect(() => {
    const now = Date.now() / 1000;
    const initialPoints: { time: number; value: number }[] = [];
    for (let i = 60; i >= 0; i--) {
      const t = now - (i * 0.5);
      const val = 14 + Math.sin(t * 2.5) * 6 + Math.cos(t * 7.1) * 3 + (Math.random() - 0.5) * 2;
      initialPoints.push({ time: t, value: Number(val.toFixed(2)) });
    }
    setData(initialPoints);
    setCurrentVal(initialPoints[initialPoints.length - 1].value);
  }, []);

  // Streaming data generator interval (~150ms per point for fluid EEG telemetry)
  useEffect(() => {
    if (paused) return;

    const interval = setInterval(() => {
      phaseRef.current += 0.25;
      const noise = (Math.random() - 0.5) * 4.5;
      const rhythm = Math.sin(phaseRef.current * 1.6) * 12.0 + Math.cos(phaseRef.current * 3.8) * 6.5;
      const nextVal = Number((baseVoltageRef.current + rhythm + noise).toFixed(1));

      const point = { time: Date.now() / 1000, value: nextVal };
      setData((prev) => [...prev.slice(-300), point]);
      setCurrentVal(nextVal);
    }, 150);

    return () => clearInterval(interval);
  }, [paused]);

  const momentumColors = {
    up: '#8FADE3',
    down: '#f87171',
    flat: '#8FADE3',
  };

  return (
    <section className="ds-card rounded-[8px] flex flex-col gap-5 p-6 sm:p-7" aria-label="Real-time BCI Signal Stream">
      {/* Header with Author Heading & Subheading (No badge around Waves icon) */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ds-border-subtle)] pb-4">
        <div className="flex items-center gap-3">
          <Waves className="w-5 h-5 text-[var(--ds-chart-blue)] shrink-0" />
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base sm:text-lg font-semibold text-[var(--ds-text-primary)] leading-none font-heading">
                Sensorimotor Rhythm Live Stream
              </h2>
              <span className={`ds-stage-dot ${paused ? 'ds-stage-dot-warning' : 'animate-pulse'}`} style={{ backgroundColor: 'var(--ds-chart-blue)' }} />
            </div>
            <p className="text-xs text-[var(--ds-text-muted)] mt-1.5 font-subheading">
              Continuous {channel} sensor micro-voltage stream (μV) at 250Hz sampling
            </p>
          </div>
        </div>

        {/* Controls: 8px Precision Channel toggle, Value pill & Pause */}
        <div className="flex items-center gap-2.5">
          {/* Channel selector tray (8px rounding) */}
          <div className="inline-flex rounded-[8px] border border-[var(--ds-border)] bg-[var(--ds-surface-subtle)] p-1 text-xs">
            <button
              type="button"
              onClick={() => setChannel('C3 (Left Motor)')}
              className={`px-3 py-1 rounded-[6px] text-xs font-medium transition-all ${
                channel.startsWith('C3')
                  ? 'bg-[var(--ds-surface)] text-[var(--ds-text-primary)] shadow-sm border border-[var(--ds-border-subtle)]'
                  : 'text-[var(--ds-text-secondary)] hover:text-[var(--ds-text-primary)]'
              }`}
            >
              C3 (Left)
            </button>
            <button
              type="button"
              onClick={() => setChannel('C4 (Right Motor)')}
              className={`px-3 py-1 rounded-[6px] text-xs font-medium transition-all ${
                channel.startsWith('C4')
                  ? 'bg-[var(--ds-surface)] text-[var(--ds-text-primary)] shadow-sm border border-[var(--ds-border-subtle)]'
                  : 'text-[var(--ds-text-secondary)] hover:text-[var(--ds-text-primary)]'
              }`}
            >
              C4 (Right)
            </button>
          </div>

          {/* Current Value Display (8px rounding) */}
          <div className="h-8 px-3 rounded-[8px] font-mono text-xs flex items-center border border-[var(--ds-blue-tint-border)] bg-[var(--ds-blue-tint-bg)]">
            <span className="text-[var(--ds-chart-blue)] font-sans font-medium">You:</span>
            <span className="font-semibold text-[var(--ds-text-primary)] ml-1">
              {currentVal > 0 ? `+${currentVal.toFixed(1)}` : currentVal.toFixed(1)} μV
            </span>
          </div>

          {/* Pause / Resume Button (8px rounding) */}
          <button
            type="button"
            onClick={() => setPaused(!paused)}
            className="w-8 h-8 rounded-[8px] border border-[var(--ds-border)] bg-[var(--ds-surface)] hover:bg-[var(--ds-surface-hover)] flex items-center justify-center transition-all cursor-pointer"
            title={paused ? 'Resume Live Stream' : 'Pause Live Stream'}
            aria-label={paused ? 'Resume Live Stream' : 'Pause Live Stream'}
          >
            {paused ? <Play className="w-3.5 h-3.5 fill-current text-[var(--ds-chart-blue)]" /> : <Pause className="w-3.5 h-3.5 text-[var(--ds-chart-blue)]" />}
          </button>
        </div>
      </div>

      {/* Chart Canvas Area */}
      <div className="w-full h-56 sm:h-64 relative mb-2">
        {data.length > 0 && (
          <LiveLineChart
            data={data}
            value={currentVal}
            window={25}
            nowOffsetUnits={1}
            margin={{ top: 20, right: 36, bottom: 44, left: 48 }}
            paused={paused}
            className="w-full h-full"
          >
            <LiveLine
              dataKey="value"
              stroke="var(--chart-line-primary)"
              strokeWidth={2}
              fill={true}
              pulse={!paused}
              dotSize={4}
              badge={true}
              momentumColors={momentumColors}
              formatValue={(v) => `${v.toFixed(1)} μV`}
            />
            <ChartTooltip showDatePill={false} />
            <LiveXAxis />
            <LiveYAxis position="left" formatValue={(v) => `${v.toFixed(0)} μV`} />
          </LiveLineChart>
        )}
      </div>

      {/* Footer Meta: Band frequencies */}
      <div className="flex flex-wrap items-center justify-between text-[11px] text-[var(--ds-text-muted)] pt-3.5 mt-4 border-t border-[var(--ds-border-subtle)] gap-2">
        <div className="hidden sm:flex items-center gap-3">
          <span>Band: <strong className="text-[var(--ds-text-primary)]">μ (Mu) 8–12 Hz</strong></span>
          <span>•</span>
          <span>Telemetry: <strong className="text-[var(--ds-chart-blue)]">#8FADE3 (You)</strong></span>
          <span>•</span>
          <span>Impedance: <strong className="text-[var(--ds-text-primary)]">&lt; 5 kΩ (Optimal)</strong></span>
        </div>
        <div className="sm:hidden flex items-center gap-2">
          <span>μ-Band (8–12 Hz) • <strong className="text-[var(--ds-chart-blue)]">#8FADE3 (You)</strong></span>
        </div>
        <div className="font-mono text-[10px]">
          Buffer: {data.length} pts | 4ms
        </div>
      </div>
    </section>
  );
}
