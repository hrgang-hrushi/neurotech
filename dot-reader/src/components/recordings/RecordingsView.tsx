'use client';

import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { AlertCircle, FileAudio2, RotateCw } from 'lucide-react';
import {
  DecodeAbortedError,
  DecoderError,
  decodeRecording,
  effectiveModel,
  groupFiles,
  type DecodeResult,
} from '@/lib/recordingApi';
import { RecordingDropzone } from './RecordingDropzone';
import { RecordingResult } from './RecordingResult';
import { useDecoderHealth, type DecoderStatus } from './useDecoderHealth';

interface RecordingsViewProps {
  onSpeak: (text: string) => void;
  isSpeaking: boolean;
}

interface HistoryEntry { id: string; result: DecodeResult }

const MAX_HISTORY = 8;

function errorMessage(err: unknown): string {
  if (err instanceof DecoderError) return err.message;
  if (err instanceof Error) return `Unexpected error: ${err.message}`;
  return 'Unexpected error while decoding.';
}

/** Stop the browser from opening a file dropped next to (not on) the dropzone. */
function usePreventStrayDrops(): void {
  useEffect(() => {
    const stop = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes('Files')) e.preventDefault();
    };
    window.addEventListener('dragover', stop);
    window.addEventListener('drop', stop);
    return () => {
      window.removeEventListener('dragover', stop);
      window.removeEventListener('drop', stop);
    };
  }, []);
}

function StatusPill({ status }: { status: DecoderStatus }) {
  const color =
    status === 'online' ? 'var(--ds-status-success)' : status === 'offline' ? 'var(--ds-status-error)' : 'var(--ds-chart-blue)';
  const label = status === 'online' ? 'Decoder online' : status === 'offline' ? 'Decoder offline' : 'Checking decoder…';
  return (
    <span className="ds-pill cursor-default whitespace-nowrap" role="status">
      <span className={`ds-stage-dot ${status === 'checking' ? 'animate-pulse' : ''}`} style={{ backgroundColor: color }} aria-hidden="true" />
      <span className="text-xs font-mono">{label}</span>
    </span>
  );
}

/** Drag-and-drop recordings, decode them on the eeg_morse server, browse results. */
export function RecordingsView({ onSpeak, isSpeaking }: RecordingsViewProps) {
  const expectedId = useId();
  const modelId = useId();
  const [busy, setBusy] = useState(false);
  const { status, models, retry } = useDecoderHealth(busy);
  const [expected, setExpected] = useState('');
  const [model, setModel] = useState('clench');
  const [progress, setProgress] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  usePreventStrayDrops();

  useEffect(() => () => abortRef.current?.abort(), []);
  const [errors, setErrors] = useState<string[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const modelOptions = models.length ? models : ['clench'];
  const activeModel = effectiveModel(model, modelOptions);
  const selected = history.find((h) => h.id === selectedId) ?? history[0] ?? null;

  const handleFiles = useCallback(
    async (files: File[]) => {
      const { groups, errors: groupErrors } = groupFiles(files);
      setErrors(groupErrors);
      if (!groups.length) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const phrase = expected;
      setBusy(true);
      const failures: string[] = [];
      let decoded = 0;
      for (const [i, group] of groups.entries()) {
        if (controller.signal.aborted) return;
        setProgress(`Decoding ${group.main.name} (${i + 1} of ${groups.length})…`);
        try {
          const result = await decodeRecording(group, { expected: phrase, model: activeModel, signal: controller.signal });
          const id = `${group.stem}-${Date.now()}-${i}`;
          setHistory((prev) => [{ id, result }, ...prev].slice(0, MAX_HISTORY));
          setSelectedId(id);
          decoded += 1;
        } catch (err) {
          if (err instanceof DecodeAbortedError) return;
          failures.push(`${group.main.name}: ${errorMessage(err)}`);
        }
      }
      setErrors((prev) => [...prev, ...failures]);
      // The phrase described the files just decoded. Clear it unless the user already typed a new one.
      if (decoded > 0) setExpected((cur) => (cur === phrase ? '' : cur));
      setProgress(
        decoded > 0
          ? `Decoded ${decoded} recording${decoded === 1 ? '' : 's'}${failures.length ? `, ${failures.length} failed` : ''}.`
          : 'No recordings could be decoded.',
      );
      setBusy(false);
    },
    [expected, activeModel],
  );

  return (
    <div className="w-full flex flex-col gap-8 py-2">
      <section className="ds-card rounded-[8px] p-6 sm:p-7 flex flex-col gap-5" aria-labelledby="recordings-heading">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-[var(--ds-border-subtle)]">
          <div>
            <h2 id="recordings-heading" className="font-heading font-semibold text-xs tracking-wider uppercase text-[var(--ds-text-muted)]">
              Decode a recording
            </h2>
            <p className="text-sm text-[var(--ds-text-secondary)] mt-1">
              Short jaw clench = dot, long clench = dash. Blinks and eye movements are filtered out.
            </p>
          </div>
          <StatusPill status={status} />
        </div>

        {status === 'offline' && (
          <div className="text-sm text-[var(--ds-text-secondary)] flex flex-wrap items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-[var(--ds-status-error)]" aria-hidden="true" />
            <span className="flex-1 min-w-0">
              The decoder isn’t answering. From the repository root, start it with{' '}
              <code className="font-mono px-1.5 py-0.5 rounded-[4px] bg-[var(--ds-surface-subtle)]">uv run eeg-morse serve</code>.
            </span>
            <button type="button" onClick={retry} className="ds-pill cursor-pointer text-xs">
              <RotateCw className="w-3.5 h-3.5" aria-hidden="true" />
              Retry
            </button>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-4">
          <label htmlFor={expectedId} className="flex flex-col gap-1.5 text-xs text-[var(--ds-text-secondary)]">
            Expected phrase (optional, for scoring)
            <input
              id={expectedId}
              type="text"
              value={expected}
              onChange={(e) => setExpected(e.target.value)}
              maxLength={200}
              placeholder="e.g. HOW ARE YOU"
              className="h-10 px-3 rounded-[8px] border border-[var(--ds-border)] bg-[var(--ds-surface)] text-sm text-[var(--ds-text-primary)] focus:outline-none focus:border-[var(--ds-border-focus)]"
            />
          </label>
          <label htmlFor={modelId} className="flex flex-col gap-1.5 text-xs text-[var(--ds-text-secondary)]">
            Model
            <select
              id={modelId}
              value={activeModel}
              onChange={(e) => setModel(e.target.value)}
              className="h-10 px-3 rounded-[8px] border border-[var(--ds-border)] bg-[var(--ds-surface)] text-sm text-[var(--ds-text-primary)] focus:outline-none focus:border-[var(--ds-border-focus)]"
            >
              {modelOptions.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
        </div>

        <RecordingDropzone onFiles={handleFiles} busy={busy} />

        <div aria-live="polite" className="text-sm text-[var(--ds-text-secondary)] min-h-5">{progress}</div>

        {errors.length > 0 && (
          <ul role="alert" className="flex flex-col gap-1.5">
            {errors.map((e, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-[var(--ds-status-error)]">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
                <span>{e}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {history.length > 1 && (
        <div role="group" aria-label="Decoded recordings this session" className="flex flex-wrap gap-2">
          {history.map((h) => (
            <button
              key={h.id}
              type="button"
              onClick={() => setSelectedId(h.id)}
              aria-pressed={selected?.id === h.id}
              className={`ds-pill cursor-pointer max-w-full ${selected?.id === h.id ? 'border-[var(--ds-chart-blue)]' : ''}`}
            >
              <FileAudio2 className="w-3.5 h-3.5 shrink-0 text-[var(--ds-text-muted)]" aria-hidden="true" />
              <span className="truncate text-xs">{h.result.file}</span>
              <span className="truncate text-xs text-[var(--ds-text-muted)] max-w-40">{h.result.text}</span>
            </button>
          ))}
        </div>
      )}

      {selected ? (
        <RecordingResult result={selected.result} onSpeak={onSpeak} isSpeaking={isSpeaking} />
      ) : (
        <div className="ds-empty text-center text-sm text-[var(--ds-text-muted)] py-8">
          Decoded messages will appear here.
        </div>
      )}
    </div>
  );
}
