'use client';

import React from 'react';
import { Check, Circle, Loader2 } from 'lucide-react';

/** The real stages of the decoder, shown one by one while a recording is processed. */
export const PROCESSING_STEPS = [
  'Reading the EEG recording',
  'Finding blinks, eye movements and electrode pops',
  'Removing eye-muscle activity from every channel',
  'Detecting jaw clenches',
  'Turning clench timing into Morse code',
  'Correcting words and adding punctuation',
] as const;

/** Time each stage stays on screen, so the steps can be followed. */
export const STEP_MS = 1100;
export const STEP_MS_REDUCED_MOTION = 250;

interface ProcessingStepsProps {
  fileName: string;
  activeIndex: number;
}

export function ProcessingSteps({ fileName, activeIndex }: ProcessingStepsProps) {
  return (
    <section className="ds-card rounded-[8px] p-6 sm:p-7" aria-label="Processing the recording">
      <div className="pb-4 mb-5 border-b border-[var(--ds-border-subtle)]">
        <h2 className="font-heading font-semibold text-xs tracking-wider uppercase text-[var(--ds-text-muted)] truncate">
          Processing · <span className="normal-case tracking-normal font-mono">{fileName}</span>
        </h2>
      </div>
      <ol className="flex flex-col gap-3 list-none">
        {PROCESSING_STEPS.map((step, i) => {
          const done = i < activeIndex;
          const active = i === activeIndex;
          return (
            <li
              key={step}
              className={`flex items-center gap-3 text-sm transition-opacity duration-300 ${
                done || active ? 'opacity-100' : 'opacity-40'
              }`}
              aria-current={active ? 'step' : undefined}
            >
              {done ? (
                <Check className="w-4 h-4 text-[var(--ds-status-success)] shrink-0" aria-hidden="true" />
              ) : active ? (
                <Loader2 className="w-4 h-4 text-[var(--ds-chart-blue)] shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <Circle className="w-4 h-4 text-[var(--ds-text-muted)] shrink-0" aria-hidden="true" />
              )}
              <span className={active ? 'text-[var(--ds-text-primary)] font-medium' : 'text-[var(--ds-text-secondary)]'}>
                {step}
                {done && <span className="sr-only"> (done)</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
