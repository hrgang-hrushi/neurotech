'use client';

import React, { useCallback, useId, useRef, useState } from 'react';
import { FileUp, Loader2 } from 'lucide-react';
import { ACCEPTED_EXTENSIONS } from '@/lib/recordingApi';

interface RecordingDropzoneProps {
  onFiles: (files: File[]) => void;
  busy: boolean;
  /** Current processing step, shown next to the loader. */
  busyLabel?: string;
}

const carriesFiles = (e: React.DragEvent) => e.dataTransfer.types.includes('Files');

/** Drag-and-drop or click/keyboard to pick recording files. */
export function RecordingDropzone({ onFiles, busy, busyLabel }: RecordingDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const hintId = useId();
  const [isOver, setIsOver] = useState(false);
  // dragenter/dragleave fire for every child the pointer crosses; count them instead
  // of trusting relatedTarget (null in WebKit, text nodes in Firefox).
  const depth = useRef(0);

  const emit = useCallback(
    (list: FileList | null) => {
      if (!list || list.length === 0 || busy) return;
      onFiles(Array.from(list));
    },
    [onFiles, busy],
  );

  const openPicker = () => {
    if (!busy) inputRef.current?.click();
  };

  const title = busy ? busyLabel ?? 'Decoding recording…' : isOver ? 'Release to upload' : 'Drop recordings here, or click to browse';

  return (
    <div
      role="button"
      tabIndex={0}
      aria-disabled={busy}
      aria-describedby={hintId}
      onClick={openPicker}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openPicker();
        }
      }}
      onDragEnter={(e) => {
        if (!carriesFiles(e)) return;
        e.preventDefault();
        depth.current += 1;
        if (!busy) setIsOver(true);
      }}
      onDragOver={(e) => {
        if (!carriesFiles(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = busy ? 'none' : 'copy';
      }}
      onDragLeave={(e) => {
        if (!carriesFiles(e)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setIsOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        depth.current = 0;
        setIsOver(false);
        emit(e.dataTransfer.files);
      }}
      className={`w-full rounded-[8px] border-2 border-dashed px-6 py-10 sm:py-12 flex flex-col items-center justify-center gap-3 text-center transition-colors outline-none focus-visible:border-[var(--ds-border-focus)] ${
        busy ? 'cursor-progress opacity-70' : 'cursor-pointer'
      } ${
        isOver
          ? 'border-[var(--ds-chart-blue)] bg-[var(--ds-blue-tint-bg)]'
          : 'border-[var(--ds-border-strong)] bg-[var(--ds-surface-subtle)] hover:bg-[var(--ds-surface-hover)]'
      }`}
    >
      {busy ? (
        <div className="flex items-center gap-3" role="status" aria-live="polite">
          <Loader2 className="w-6 h-6 text-[var(--ds-chart-blue)] animate-spin motion-reduce:animate-none shrink-0" aria-hidden="true" />
          <div className="text-base font-medium text-[var(--ds-text-primary)] font-heading">{title}</div>
        </div>
      ) : (
        <>
          <FileUp className="w-7 h-7 text-[var(--ds-chart-blue)]" aria-hidden="true" />
          <div className="text-base font-medium text-[var(--ds-text-primary)] font-heading">{title}</div>
        </>
      )}
      <p id={hintId} className="text-xs text-[var(--ds-text-muted)] max-w-lg leading-relaxed">
        Accepts {ACCEPTED_EXTENSIONS.join(' ')}. For eego files, drop the <span className="font-mono">.cnt</span> together
        with its <span className="font-mono">.evt</span> and <span className="font-mono">.seg</span> files (same name) so
        events and pause/resume segments are used.
      </p>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(',')}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => {
          emit(e.target.files);
          e.target.value = '';
        }}
      />
    </div>
  );
}
