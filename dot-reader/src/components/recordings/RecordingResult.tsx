'use client';

import React from 'react';
import { AlertTriangle, ArrowRight, AudioLines, CheckCircle2, XCircle } from 'lucide-react';
import type { DecodeResult, LetterStatus } from '@/lib/recordingApi';
import { ActivationTrace } from './ActivationTrace';

interface RecordingResultProps {
  result: DecodeResult;
  onSpeak: (text: string) => void;
  isSpeaking: boolean;
}

const STATUS_STYLE: Record<LetterStatus, string> = {
  ok: 'border-[var(--ds-border)] bg-[var(--ds-surface-subtle)] text-[var(--ds-text-primary)]',
  split: 'border-[var(--ds-blue-tint-border)] bg-[var(--ds-blue-tint-bg)] text-[var(--ds-blue-tint-text)]',
  nearest: 'border-[var(--ds-status-warning)] text-[var(--ds-status-warning)]',
  unknown: 'border-[var(--ds-status-error)] text-[var(--ds-status-error)]',
};

const STATUS_LABEL: Record<LetterStatus, string> = {
  ok: 'valid Morse',
  split: 'two letters sent without a gap, split',
  nearest: 'invalid code, nearest letter used',
  unknown: 'could not be decoded',
};

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="font-heading font-semibold text-xs tracking-wider uppercase text-[var(--ds-text-muted)] mb-3">
      {children}
    </h3>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[11px] text-[var(--ds-text-muted)]">{label}</dt>
      <dd className="font-mono text-sm text-[var(--ds-text-primary)]">{value}</dd>
    </div>
  );
}

function Progression({ result }: { result: DecodeResult }) {
  const steps = [
    { label: 'Raw Morse decode', value: result.raw_text },
    { label: 'Dictionary corrected', value: result.corrected_text },
    { label: 'Final', value: result.text },
  ];
  return (
    <ol className="flex flex-col md:flex-row md:items-stretch gap-2 md:gap-3">
      {steps.map((s, i) => (
        <li key={s.label} className="flex-1 flex items-center gap-2 md:gap-3">
          <div className="flex-1 h-full rounded-[8px] border border-[var(--ds-border)] bg-[var(--ds-surface-subtle)] px-3 py-2.5">
            <div className="text-[11px] text-[var(--ds-text-muted)] mb-1">{s.label}</div>
            <div className="font-mono text-sm text-[var(--ds-text-primary)] break-words">{s.value || '—'}</div>
          </div>
          {i < steps.length - 1 && (
            <ArrowRight className="hidden md:block w-4 h-4 text-[var(--ds-text-muted)] shrink-0" aria-hidden="true" />
          )}
        </li>
      ))}
    </ol>
  );
}

function ScoreBadge({ score }: { score: NonNullable<DecodeResult['score']> }) {
  const Icon = score.exact ? CheckCircle2 : XCircle;
  const tone = score.exact ? 'text-[var(--ds-status-success)]' : 'text-[var(--ds-status-warning)]';
  return (
    <div className="flex items-center gap-2 text-sm">
      <Icon className={`w-4 h-4 ${tone}`} aria-hidden="true" />
      <span className={tone}>{score.exact ? 'Exact match' : 'Not exact'}</span>
      <span className="text-[var(--ds-text-muted)]">
        · character error rate {(score.cer * 100).toFixed(1)}% vs “{score.expected}”
      </span>
    </div>
  );
}

/** Everything the decoder found in one recording. */
export function RecordingResult({ result, onSpeak, isSpeaking }: RecordingResultProps) {
  const sentenceInfo = result.sentence_types.length ? result.sentence_types.join(', ') : null;
  const removed = result.artifacts;

  return (
    <div className="flex flex-col gap-6">
      <section className="ds-card rounded-[8px] p-6 sm:p-7" aria-labelledby="decoded-heading">
        <div className="flex items-center justify-between gap-3 pb-4 border-b border-[var(--ds-border-subtle)]">
          <h2 id="decoded-heading" className="font-heading font-semibold text-xs tracking-wider uppercase text-[var(--ds-text-muted)] truncate">
            Decoded · <span className="normal-case tracking-normal font-mono">{result.file}</span>
          </h2>
          <span className="text-xs text-[var(--ds-text-muted)] shrink-0">model {result.model}</span>
        </div>

        <p className="my-7 text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight leading-tight font-heading text-[var(--ds-text-primary)] break-words select-text">
          {result.text || (
            <span className="text-[var(--ds-text-muted)] font-normal text-2xl">
              {result.reliable
                ? 'No message found in this recording.'
                : 'No clear Morse signal in this recording. See the warnings and the activation chart below.'}
            </span>
          )}
        </p>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => onSpeak(result.text)}
            disabled={!result.text.trim() || isSpeaking}
            className="ds-btn ds-btn-large-primary rounded-[8px]"
          >
            <AudioLines className="w-4 h-4" aria-hidden="true" />
            <span>{isSpeaking ? 'Speaking…' : 'Speak message'}</span>
          </button>
          {sentenceInfo && <span className="text-xs text-[var(--ds-text-muted)]">Sentence type: {sentenceInfo}</span>}
        </div>

        {result.score && <div className="mt-5"><ScoreBadge score={result.score} /></div>}
      </section>

      <section className="ds-card rounded-[8px]" aria-label="Decoding steps">
        <SectionLabel>From signal to sentence</SectionLabel>
        <Progression result={result} />
        {result.corrections.length > 0 && (
          <ul className="mt-4 flex flex-wrap gap-2 text-xs" aria-label="Word corrections">
            {result.corrections.map((c, i) => (
              <li key={`${c.from}-${i}`} className="px-2.5 py-1 rounded-[6px] border border-[var(--ds-border)] font-mono">
                <span className="line-through text-[var(--ds-text-muted)]">{c.from}</span>
                <span className="mx-1.5 text-[var(--ds-text-muted)]">→</span>
                <span className="text-[var(--ds-text-primary)]">{c.to}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-5">
          <div className="text-[11px] text-[var(--ds-text-muted)] mb-1">Morse</div>
          <div className="font-mono text-sm tracking-wider text-[var(--ds-text-secondary)] break-words">{result.morse || '—'}</div>
        </div>
        {result.letters.length > 0 && (
          <ul className="mt-4 flex flex-wrap gap-1.5" aria-label="Decoded letters">
            {result.letters.map((l, i) => (
              <li
                key={`${l.t_start}-${i}`}
                title={`${l.code} → ${l.char}: ${STATUS_LABEL[l.status]} (${l.t_start.toFixed(2)} s)`}
                className={`flex flex-col items-center min-w-9 px-2 py-1 rounded-[6px] border ${STATUS_STYLE[l.status]}`}
              >
                <span className="text-sm font-semibold font-heading">{l.char}</span>
                <span className="font-mono text-[10px] opacity-80">{l.code}</span>
                <span className="sr-only">{STATUS_LABEL[l.status]}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="ds-card rounded-[8px]" aria-label="Activation trace">
        <SectionLabel>Jaw-clench activation</SectionLabel>
        <ActivationTrace trace={result.trace} elements={result.elements} artifacts={result.artifacts} durationS={result.duration_s} />
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="ds-card rounded-[8px]">
          <SectionLabel>Signal quality</SectionLabel>
          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <Stat label="Separability" value={result.quality.separability.toFixed(2)} />
            <Stat label="Key-downs" value={String(result.quality.n_key_downs)} />
            <Stat label="Artifacts removed" value={String(result.quality.n_artifacts || removed.length)} />
            <Stat label="Duration" value={`${result.duration_s.toFixed(1)} s`} />
            <Stat label="Sampling" value={`${result.sfreq} Hz`} />
            <Stat label="Channels" value={String(result.n_channels)} />
          </dl>
          <div className="mt-4 text-xs text-[var(--ds-text-muted)] leading-relaxed">
            Used: <span className="font-mono">{result.channels_used.join(', ') || '—'}</span>
            {result.bad_channels.length > 0 && (
              <> · Excluded: <span className="font-mono">{result.bad_channels.join(', ')}</span></>
            )}
          </div>
        </div>
        <div className="ds-card rounded-[8px]">
          <SectionLabel>Timing</SectionLabel>
          <dl className="grid grid-cols-2 gap-4">
            <Stat label="Unit (dot length)" value={`${result.timing.unit_s.toFixed(3)} s`} />
            <Stat label="Dash if longer than" value={`${result.timing.dash_threshold_s.toFixed(3)} s`} />
            <Stat label="Letter gap" value={`${result.timing.letter_gap_s.toFixed(3)} s`} />
            <Stat label="Word gap" value={`${result.timing.word_gap_s.toFixed(3)} s`} />
          </dl>
        </div>
      </section>

      {result.quality.warnings.length > 0 && (
        <section className="ds-card rounded-[8px] border-[var(--ds-status-warning)]" aria-label="Warnings">
          <SectionLabel>Warnings</SectionLabel>
          <ul className="flex flex-col gap-2">
            {result.quality.warnings.map((w, i) => (
              <li key={i} className="flex gap-2 text-sm text-[var(--ds-text-secondary)]">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-[var(--ds-status-warning)]" aria-hidden="true" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
