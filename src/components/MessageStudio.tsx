'use client';

import React, { useState } from 'react';
import {
  AudioLines,
  RotateCcw,
  CornerDownLeft,
  Space,
  Delete,
  BookOpen,
  BrainCircuit,
  Waves,
  Speech,
  Sparkles,
} from 'lucide-react';
import { MORSE_MAP } from '../lib/morse';
import { LiveTelemetryChart } from './LiveTelemetryChart';

interface MessageStudioProps {
  text: string;
  writtenMorse: string;
  pendingSymbols: string;
  decoderState: string;
  autoSpeak: boolean;
  onToggleAutoSpeak: () => void;
  onSymbol: (val: '.' | '-') => void;
  onCommitLetter: () => void;
  onCommitWord: () => void;
  onBackspace: () => void;
  onClear: () => void;
  onSpeak: () => void;
  recentMessages: string[];
  onSelectRecent: (msg: string) => void;
}

export function MessageStudio({
  text,
  writtenMorse,
  pendingSymbols,
  decoderState,
  autoSpeak,
  onToggleAutoSpeak,
  onSymbol,
  onCommitLetter,
  onCommitWord,
  onBackspace,
  onClear,
  onSpeak,
  recentMessages,
  onSelectRecent,
}: MessageStudioProps) {
  const [showReference, setShowReference] = useState(false);
  const alphabetPairs = Object.entries(MORSE_MAP).slice(0, 26);
  const pendingChar = pendingSymbols ? MORSE_MAP[pendingSymbols] || '…' : null;

  return (
    <div className="w-full flex flex-col gap-8 py-2">
      {/* 1. Main Communication Canvas (Unified 8px Rounding, Balanced Spacing) */}
      <section className="ds-card rounded-[8px] flex flex-col justify-between min-h-[260px] p-6 sm:p-7" aria-label="Morse Communication Canvas">
        {/* Top: Header & Auto-speak Toggle (Removed cluttered debug string) */}
        <div className="flex items-center justify-between pb-4 border-b border-[var(--ds-border-subtle)] text-xs text-[var(--ds-text-secondary)]">
          <span className="font-heading font-semibold text-xs tracking-wider uppercase text-[var(--ds-text-muted)]">
            Live Message Studio
          </span>

          <label className="flex items-center gap-2.5 cursor-pointer select-none text-[var(--ds-text-secondary)] hover:text-[var(--ds-text-primary)] transition-colors">
            <input
              type="checkbox"
              checked={autoSpeak}
              onChange={onToggleAutoSpeak}
              className="w-4 h-4 rounded-[4px] border-[var(--ds-border)] accent-[var(--ds-chart-blue)] cursor-pointer"
            />
            <span>Auto-speak completed words</span>
          </label>
        </div>

        {/* Center: Large Communication Text with Refined Vertical Balance */}
        <div className="my-7 sm:my-9">
          <div className="min-h-[76px] flex items-center">
            {text ? (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-3xl sm:text-4xl md:text-5xl font-semibold text-[var(--ds-text-primary)] tracking-tight leading-tight select-text font-heading">
                  {text}
                </span>
                <span className="w-0.5 h-8 sm:h-10 bg-[var(--ds-chart-blue)] animate-pulse shrink-0" aria-hidden="true" />
              </div>
            ) : (
              <span className="text-2xl sm:text-3xl text-[var(--ds-text-muted)] font-normal font-heading">
                Type or trigger Morse code to communicate…
              </span>
            )}
          </div>

          {/* Pending & Written Morse Buffer with 8px rounding */}
          <div className="mt-4 flex items-center gap-3 font-mono text-sm">
            <span className="text-[var(--ds-text-muted)] font-sans text-xs">Morse stream:</span>
            <span className="text-[var(--ds-text-secondary)] tracking-wider">
              {writtenMorse ? writtenMorse : <span className="text-[var(--ds-text-muted)]">—</span>}
            </span>
            {pendingSymbols && (
              <span className="px-2.5 py-0.5 rounded-[6px] bg-[var(--ds-blue-tint-bg)] border border-[var(--ds-blue-tint-border)] text-[var(--ds-blue-tint-text)] font-mono text-xs font-semibold flex items-center gap-1.5 animate-pulse">
                <span>{pendingSymbols}</span>
                {pendingChar && <span className="opacity-80">({pendingChar})</span>}
              </span>
            )}
          </div>
        </div>

        {/* Bottom Actions: 8px Precision Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-5 border-t border-[var(--ds-border-subtle)]">
          <div className="flex items-center gap-3">
            {/* Top of queue: Solid Primary Button (8px rounding) */}
            <button
              type="button"
              onClick={onSpeak}
              disabled={!text.trim()}
              className="ds-btn ds-btn-large-primary rounded-[8px]"
              aria-label="Speak current message"
            >
              <AudioLines className="w-4 h-4" />
              <span>Speak message</span>
            </button>

            {/* Outlined Button (8px rounding) */}
            <button
              type="button"
              onClick={onClear}
              disabled={!text && !pendingSymbols && !writtenMorse}
              className="ds-btn ds-btn-outline rounded-[8px]"
              aria-label="Clear current message"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Clear</span>
            </button>
          </div>

          {/* Outlined Button (8px rounding) */}
          <button
            type="button"
            onClick={() => setShowReference(!showReference)}
            className="ds-btn ds-btn-outline rounded-[8px]"
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>{showReference ? 'Hide alphabet' : 'Show alphabet'}</span>
          </button>
        </div>
      </section>

      {/* 2. Real-Time Streaming Live Line Chart (@bklitui/ui/charts) */}
      <LiveTelemetryChart />

      {/* 3. Accessible Neural & Manual Trigger Pads */}
      <section className="w-full flex flex-col gap-4" aria-label="Signal Triggers">
        <div className="flex items-center justify-between text-xs text-[var(--ds-text-secondary)] px-1">
          <span className="font-semibold text-[var(--ds-text-primary)] font-heading">Signal Triggers</span>
          <span className="font-subheading">Keyboard shortcuts: <kbd className="px-2 py-0.5 rounded-full bg-[var(--ds-surface-subtle)] border border-[var(--ds-border)] text-[var(--ds-text-primary)] font-mono text-[11px]">.</kbd> for Dot, <kbd className="px-2 py-0.5 rounded-full bg-[var(--ds-surface-subtle)] border border-[var(--ds-border)] text-[var(--ds-text-primary)] font-mono text-[11px]">-</kbd> for Dash</span>
        </div>

        {/* Primary Dot and Dash Touch Targets with 8px rounding */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Dot Trigger (8px rounding) */}
          <button
            type="button"
            onClick={() => onSymbol('.')}
            className="h-32 rounded-[8px] ds-tile hover:border-[var(--ds-border-strong)] active:scale-[0.96] transition-all p-5 flex flex-col justify-between text-left group cursor-pointer"
            aria-label="Trigger Morse Dot (Left Hand)"
          >
            <div className="flex items-center justify-between text-xs text-[var(--ds-text-secondary)]">
              <div className="flex items-center gap-2">
                <BrainCircuit className="w-4 h-4 text-[var(--ds-chart-blue)] shrink-0" />
                <span className="font-medium text-[var(--ds-text-secondary)] group-hover:text-[var(--ds-text-primary)] transition-colors">
                  Left Hand Motor Imagery
                </span>
              </div>
              <kbd className="px-2 py-0.5 rounded-[6px] bg-[var(--ds-surface)] border border-[var(--ds-border)] text-[var(--ds-text-primary)] font-mono text-xs">
                .
              </kbd>
            </div>
            <div className="flex items-baseline gap-3">
              <span className="text-4xl font-mono font-bold text-[var(--ds-text-primary)] leading-none">
                ·
              </span>
              <span className="text-xl font-medium text-[var(--ds-text-secondary)] group-hover:text-[var(--ds-text-primary)] transition-colors">
                Dot
              </span>
            </div>
          </button>

          {/* Dash Trigger (8px rounding) */}
          <button
            type="button"
            onClick={() => onSymbol('-')}
            className="h-32 rounded-[8px] ds-tile hover:border-[var(--ds-border-strong)] active:scale-[0.96] transition-all p-5 flex flex-col justify-between text-left group cursor-pointer"
            aria-label="Trigger Morse Dash (Right Hand)"
          >
            <div className="flex items-center justify-between text-xs text-[var(--ds-text-secondary)]">
              <div className="flex items-center gap-2">
                <Waves className="w-4 h-4 text-[var(--ds-chart-blue)] shrink-0" />
                <span className="font-medium text-[var(--ds-text-secondary)] group-hover:text-[var(--ds-text-primary)] transition-colors">
                  Right Hand Motor Imagery
                </span>
              </div>
              <kbd className="px-2 py-0.5 rounded-[6px] bg-[var(--ds-surface)] border border-[var(--ds-border)] text-[var(--ds-text-primary)] font-mono text-xs">
                -
              </kbd>
            </div>
            <div className="flex items-baseline gap-3">
              <span className="text-4xl font-mono font-bold text-[var(--ds-text-primary)] leading-none">
                —
              </span>
              <span className="text-xl font-medium text-[var(--ds-text-secondary)] group-hover:text-[var(--ds-text-primary)] transition-colors">
                Dash
              </span>
            </div>
          </button>
        </div>

        {/* Boundary Controls Row - 8px Rounded Buttons */}
        <div className="grid grid-cols-3 gap-3 mt-2">
          <button
            type="button"
            onClick={onCommitLetter}
            className="ds-btn ds-btn-outline rounded-[8px] h-11"
          >
            <Space className="w-4 h-4 text-[var(--ds-text-muted)]" />
            <span>End letter</span>
            <kbd className="text-[10px] text-[var(--ds-text-muted)] font-mono ml-1">Space</kbd>
          </button>

          <button
            type="button"
            onClick={onCommitWord}
            className="ds-btn ds-btn-outline rounded-[8px] h-11"
          >
            <CornerDownLeft className="w-3.5 h-3.5 text-[var(--ds-text-muted)]" />
            <span>End word</span>
            <kbd className="text-[10px] text-[var(--ds-text-muted)] font-mono ml-1">Enter</kbd>
          </button>

          <button
            type="button"
            onClick={onBackspace}
            className="ds-btn ds-btn-outline rounded-[8px] h-11"
          >
            <Delete className="w-3.5 h-3.5 text-[var(--ds-text-muted)]" />
            <span>Backspace</span>
          </button>
        </div>
      </section>

      {/* 4. Collapsible Morse Alphabet Reference (§7.6 Tile Grid with 8px rounding) */}
      {showReference && (
        <section className="ds-card rounded-[8px] p-5 sm:p-6 animate-in fade-in duration-200" aria-label="Morse Reference Table">
          <h3 className="text-xs font-semibold text-[var(--ds-text-secondary)] uppercase tracking-wider mb-4 font-heading">
            International Morse Reference
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2.5 text-xs">
            {alphabetPairs.map(([code, char]) => (
              <div
                key={char}
                className="ds-tile p-2.5 flex items-center justify-between font-mono rounded-[8px]"
              >
                <span className="font-bold text-[var(--ds-text-primary)] text-sm">{char}</span>
                <span className="text-[var(--ds-text-muted)] text-xs">{code}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 5. Recent Spoken Messages (8px rounding) */}
      {recentMessages.length > 0 && (
        <section className="w-full flex flex-col gap-3" aria-label="Recent Spoken Messages">
          <span className="text-xs font-semibold text-[var(--ds-text-secondary)] px-1 font-heading">Recent Spoken Messages</span>
          <div className="flex flex-col gap-2">
            {recentMessages.map((msg, i) => (
              <div
                key={i}
                className="w-full ds-tile p-4 flex items-center justify-between text-xs rounded-[8px]"
              >
                <span className="font-medium text-[var(--ds-text-primary)] text-sm">{msg}</span>
                <button
                  type="button"
                  onClick={() => onSelectRecent(msg)}
                  className="ds-btn ds-btn-outline rounded-[8px] h-9 text-xs px-4"
                  aria-label={`Repeat message: ${msg}`}
                >
                  <Speech className="w-3.5 h-3.5 text-[var(--ds-chart-blue)]" />
                  <span>Repeat</span>
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
