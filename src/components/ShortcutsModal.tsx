'use client';

import React from 'react';
import {
  X,
  Keyboard,
  BrainCircuit,
  Waves,
  Space,
  CornerDownLeft,
  Delete,
  Info,
} from 'lucide-react';

interface ShortcutsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const shortcuts = [
  { key: '.', desc: 'Trigger Morse Dot (·) / Left Hand', icon: BrainCircuit },
  { key: '-', desc: 'Trigger Morse Dash (—) / Right Hand', icon: Waves },
  { key: 'Space', desc: 'Commit current letter sequence', icon: Space },
  { key: 'Enter', desc: 'Commit current word sequence', icon: CornerDownLeft },
  { key: 'Backspace', desc: 'Delete previous symbol or character', icon: Delete },
  { key: 'Esc', desc: 'Close dialog or modal', icon: X },
];

export function ShortcutsModal({ isOpen, onClose }: ShortcutsModalProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-150"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcuts-title"
    >
      <div
        className="w-full max-w-md ds-card rounded-[8px] p-6 shadow-2xl flex flex-col gap-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between pb-3.5 border-b border-[var(--ds-border-subtle)]">
          <div className="flex items-center gap-2.5">
            <Keyboard className="w-4 h-4 text-[var(--ds-chart-blue)] shrink-0" />
            <h3 id="shortcuts-title" className="text-sm font-semibold text-[var(--ds-text-primary)] font-heading">
              Keyboard & BCI Shortcuts
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 rounded-[8px] border border-[var(--ds-border)] bg-[var(--ds-surface)] hover:bg-[var(--ds-surface-hover)] flex items-center justify-center transition-all cursor-pointer"
            aria-label="Close dialog"
          >
            <X className="w-4 h-4 text-[var(--ds-text-muted)] hover:text-[var(--ds-text-primary)]" />
          </button>
        </div>

        <div className="flex flex-col gap-2.5">
          {shortcuts.map((s) => {
            const Icon = s.icon;
            return (
              <div
                key={s.key}
                className="flex items-center justify-between p-3 rounded-[8px] ds-tile text-xs"
              >
                <div className="flex items-center gap-2.5">
                  <Icon className="w-3.5 h-3.5 text-[var(--ds-chart-blue)] shrink-0" />
                  <span className="text-[var(--ds-text-secondary)]">{s.desc}</span>
                </div>
                <kbd className="px-2.5 py-1 rounded-[6px] bg-[var(--ds-surface)] border border-[var(--ds-border)] text-[var(--ds-text-primary)] font-mono font-medium text-xs">
                  {s.key}
                </kbd>
              </div>
            );
          })}
        </div>

        <div className="pt-3 border-t border-[var(--ds-border-subtle)] text-[11px] text-[var(--ds-text-muted)] flex items-start gap-2">
          <Info className="w-3.5 h-3.5 text-[var(--ds-chart-blue)] shrink-0 mt-0.5" />
          <span>In Live EEG mode, physical keyboard shortcuts run concurrently with automated neural classifier triggers.</span>
        </div>
      </div>
    </div>
  );
}
