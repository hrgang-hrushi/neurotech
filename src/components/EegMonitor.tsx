'use client';

import React, { useState, useEffect } from 'react';
import { Pause, Play, Activity, Info, Waves } from 'lucide-react';
import { SegmentedControl } from './ui/SegmentedControl';

type ChartMode = 'Waveform' | 'Spectrum';
type ChannelSelection = 'All Channels' | 'C3 (Left)' | 'Cz (Midline)' | 'C4 (Right)';

interface ChannelTelemetry {
  name: string;
  region: string;
  impedance: string;
  amplitude: string;
  erdPower: string;
}

const channelsData: ChannelTelemetry[] = [
  {
    name: 'C3',
    region: 'Left Sensorimotor Cortex',
    impedance: '4.2 kΩ',
    amplitude: '-12.8 μV',
    erdPower: '-11.4 dB (Mu rhythm)',
  },
  {
    name: 'Cz',
    region: 'Vertex Midline Reference',
    impedance: '5.1 kΩ',
    amplitude: '+4.2 μV',
    erdPower: '-2.1 dB (Baseline)',
  },
  {
    name: 'C4',
    region: 'Right Sensorimotor Cortex',
    impedance: '3.9 kΩ',
    amplitude: '+9.4 μV',
    erdPower: '-9.8 dB (Mu rhythm)',
  },
];

export function EegMonitor() {
  const [chartMode, setChartMode] = useState<ChartMode>('Waveform');
  const [channelSel, setChannelSel] = useState<ChannelSelection>('All Channels');
  const [isPaused, setIsPaused] = useState(false);
  const [timeOffset, setTimeOffset] = useState(0);

  // Smooth live tick when not paused
  useEffect(() => {
    if (isPaused) return;
    const timer = setInterval(() => {
      setTimeOffset((t) => (t + 1) % 100);
    }, 120);
    return () => clearInterval(timer);
  }, [isPaused]);

  return (
    <div className="w-full flex flex-col gap-6 py-2" role="region" aria-label="EEG Neural Telemetry Monitor">
      {/* Top Header & Controls (No icon badge container) */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Activity className="w-5 h-5 text-[var(--ds-chart-blue)] shrink-0" />
          <div>
            <h2 className="text-xl font-semibold text-[var(--ds-text-primary)] tracking-tight font-heading">
              Motor Cortex Neural Telemetry
            </h2>
            <p className="text-sm text-[var(--ds-text-secondary)] font-normal mt-0.5 font-subheading">
              Real-time sensorimotor rhythm (C3 · Cz · C4) from 24-channel ANT cap.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* §7.11 Lane Switch / Segmented Control */}
          <SegmentedControl<ChartMode>
            options={[
              { value: 'Waveform', label: 'Waveform (Time)' },
              { value: 'Spectrum', label: 'Spectrum (PSD)' },
            ]}
            value={chartMode}
            onChange={setChartMode}
            size="sm"
            variant="tray"
          />

          <button
            type="button"
            onClick={() => setIsPaused(!isPaused)}
            className="ds-btn ds-btn-outline rounded-[8px] h-9 text-xs px-4"
            aria-label={isPaused ? 'Resume streaming' : 'Pause streaming'}
          >
            {isPaused ? <Play className="w-3.5 h-3.5 fill-current text-[var(--ds-chart-blue)]" /> : <Pause className="w-3.5 h-3.5 text-[var(--ds-chart-blue)]" />}
            <span>{isPaused ? 'Resume' : 'Pause'}</span>
          </button>
        </div>
      </div>

      {/* Main Signal Display Canvas (§7.5 Card Surface, 8px rounding) */}
      <section className="w-full ds-card rounded-[8px] p-5 sm:p-6 flex flex-col gap-4">
        {/* Sub-header inside canvas */}
        <div className="flex items-center justify-between text-xs text-[var(--ds-text-secondary)] pb-3 border-b border-[var(--ds-border-subtle)]">
          <div className="flex items-center gap-2">
            <span className="ds-stage-dot ds-stage-dot-success" aria-hidden="true" />
            <span className="text-[var(--ds-text-primary)]">
              {chartMode === 'Waveform'
                ? 'Rolling 2.0-second time series (-2.0s to 0.0s)'
                : 'Welch Power Spectral Density (0 Hz to 45 Hz)'}
            </span>
          </div>

          <div className="flex items-center gap-4 text-xs font-mono text-[var(--ds-text-muted)]">
            <span>Sample rate: 500 S/s</span>
            <span>Filter: 0.5–45 Hz</span>
          </div>
        </div>

        {/* Signals Stack (§7.6 Tiles) */}
        <div className="flex flex-col gap-4 mt-2">
          {channelsData
            .filter((c) => {
              if (channelSel === 'All Channels') return true;
              if (channelSel === 'C3 (Left)' && c.name === 'C3') return true;
              if (channelSel === 'Cz (Midline)' && c.name === 'Cz') return true;
              if (channelSel === 'C4 (Right)' && c.name === 'C4') return true;
              return false;
            })
            .map((ch, idx) => {
              const seed = (timeOffset + idx * 30) % 100;
              const points = Array.from({ length: 40 }).map((_, i) => {
                const x = (i / 39) * 800;
                const phase = (i * 0.4 + seed * 0.1);
                const isDip = i > 15 && i < 26 && ch.name !== 'Cz';
                const amp = isDip ? 4 : 14;
                const y = 30 + Math.sin(phase) * amp + Math.cos(phase * 2.3) * (amp * 0.4);
                return `${x},${y.toFixed(1)}`;
              });
              const wavePath = `M ${points.join(' L ')}`;

              return (
                <div
                  key={ch.name}
                  className="ds-tile p-4 flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4"
                >
                  {/* Channel Meta */}
                  <div className="w-full md:w-56 shrink-0 flex flex-col justify-center">
                    <div className="flex items-center gap-2">
                      <span className="text-base font-semibold text-[var(--ds-text-primary)] font-mono">
                        {ch.name}
                      </span>
                      <span className="text-xs text-[var(--ds-text-muted)] font-normal">
                        {ch.region}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 mt-1.5 text-xs text-[var(--ds-text-muted)] font-mono">
                      <span>Contact: {ch.impedance}</span>
                      <span>Amp: {ch.amplitude}</span>
                    </div>
                  </div>

                  {/* SVG Waveform Line */}
                  <div className="flex-1 h-16 bg-[var(--ds-surface)] rounded-lg border border-[var(--ds-border-subtle)] p-2 flex items-center overflow-hidden">
                    {chartMode === 'Waveform' ? (
                      <svg viewBox="0 0 800 60" preserveAspectRatio="none" className="w-full h-full">
                        <line x1="0" y1="30" x2="800" y2="30" stroke="var(--ds-border-subtle)" strokeWidth="1" strokeDasharray="4 4" />
                        <path
                          d={wavePath}
                          fill="none"
                          stroke="var(--ds-chart-blue)"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    ) : (
                      /* Spectrum FFT Power Bars */
                      <div className="w-full h-full flex items-end gap-1 px-2">
                        {Array.from({ length: 32 }).map((_, binIdx) => {
                          const freq = binIdx * 1.5;
                          const isMu = freq >= 8 && freq <= 14;
                          const heightPct = isMu ? (ch.name === 'Cz' ? 75 : 45) : 15 + Math.random() * 20;
                          return (
                            <div
                              key={binIdx}
                              className="flex-1 rounded-t-sm transition-all"
                              style={{
                                height: `${heightPct}%`,
                                backgroundColor: isMu ? 'var(--ds-text-primary)' : 'var(--ds-border-strong)',
                              }}
                              title={`${freq.toFixed(1)} Hz`}
                            />
                          );
                        })}
                      </div>
                    )}
                  </div>

                  {/* Metrics Readout */}
                  <div className="w-full md:w-44 shrink-0 text-right text-xs">
                    <span className="text-[var(--ds-text-muted)] block font-normal text-[11px]">
                      {chartMode === 'Waveform' ? 'Extrema range' : 'Mu Band (8–13Hz)'}
                    </span>
                    <span className="text-[var(--ds-text-primary)] font-mono font-medium block mt-0.5">
                      {ch.erdPower}
                    </span>
                  </div>
                </div>
              );
            })}
        </div>

        {/* Timeline Bottom Legend */}
        <div className="flex items-center justify-between text-xs text-[var(--ds-text-muted)] font-mono pt-3 border-t border-[var(--ds-border-subtle)]">
          {chartMode === 'Waveform' ? (
            <>
              <span>-2.0s</span>
              <span>-1.5s</span>
              <span>-1.0s</span>
              <span>-0.5s</span>
              <span>0.0s (Now)</span>
            </>
          ) : (
            <>
              <span>0 Hz</span>
              <span>8 Hz (Mu Onset)</span>
              <span>12 Hz (Beta Transition)</span>
              <span>30 Hz</span>
              <span>45 Hz</span>
            </>
          )}
        </div>
      </section>

      {/* Explanatory Context Card (8px rounding) */}
      <section className="ds-tile rounded-[8px] p-5 text-xs text-[var(--ds-text-secondary)] leading-relaxed flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Info className="w-4 h-4 text-[var(--ds-chart-blue)] shrink-0" />
          <h4 className="text-[var(--ds-text-primary)] font-semibold font-heading">How Motor Imagery Morse Decoding Works</h4>
        </div>
        <p>
          When the user imagines moving their <strong>left hand</strong>, the contralateral motor cortex (electrode C3) exhibits Event-Related Desynchronization (ERD)—a localized drop in 8–13 Hz mu power. The decoder detects this drop and translates it into a Morse <strong>Dot (·)</strong>.
        </p>
        <p>
          Similarly, imagined <strong>right hand</strong> movement triggers ERD over electrode C4, registering a Morse <strong>Dash (—)</strong>. Pausing without motor imagery commits the completed character or word.
        </p>
      </section>
    </div>
  );
}
