'use client';

import React from 'react';
import { Speech, HeartPulse, HeartHandshake, Coffee } from 'lucide-react';

interface PhraseBoardProps {
  onSpeakPhrase: (phrase: string) => void;
  activePhrase?: string | null;
}

const phraseCategories = [
  {
    id: 'care',
    name: 'Care & Assistance',
    icon: HeartPulse,
    phrases: [
      { text: 'I need assistance, please.', short: 'Need assistance' },
      { text: 'I am in pain and need help.', short: 'In pain' },
      { text: 'Please call the nurse or caregiver.', short: 'Call nurse' },
      { text: 'Help me sit up, please.', short: 'Sit up' },
      { text: 'Please adjust my position.', short: 'Adjust position' },
      { text: 'I am having difficulty breathing.', short: 'Trouble breathing' },
    ],
  },
  {
    id: 'comfort',
    name: 'Physical Comfort & Needs',
    icon: Coffee,
    phrases: [
      { text: 'Can I please have a glass of water?', short: 'Water' },
      { text: 'I am hungry and would like food.', short: 'Hungry' },
      { text: 'I feel cold, please adjust my blanket.', short: 'Cold' },
      { text: 'I feel too warm right now.', short: 'Too warm' },
      { text: 'Please turn down the lights.', short: 'Dim lights' },
      { text: 'I need to rest and sleep.', short: 'Need rest' },
    ],
  },
  {
    id: 'social',
    name: 'Conversational & Social',
    icon: HeartHandshake,
    phrases: [
      { text: 'Yes, thank you.', short: 'Yes' },
      { text: 'No, thank you.', short: 'No' },
      { text: 'Thank you very much.', short: 'Thank you' },
      { text: 'Please repeat that.', short: 'Repeat' },
      { text: 'I understand what you are saying.', short: 'I understand' },
      { text: 'I love you.', short: 'I love you' },
      { text: 'Good morning.', short: 'Good morning' },
      { text: 'Good night.', short: 'Good night' },
    ],
  },
];

export function PhraseBoard({ onSpeakPhrase, activePhrase }: PhraseBoardProps) {
  return (
    <div className="w-full flex flex-col gap-6 py-2" role="region" aria-label="Rapid Phrase Board">
      {/* Intro Description */}
      <div className="flex flex-col gap-1">
        <h2 className="text-xl font-semibold text-[var(--ds-text-primary)] tracking-tight font-heading">
          Rapid Phrase Board
        </h2>
        <p className="text-sm text-[var(--ds-text-secondary)] font-normal font-subheading">
          Tap any phrase below to vocalize immediately via speech synthesis.
        </p>
      </div>

      {/* Categories Grid (§7.5 Card Surface) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5 items-start">
        {phraseCategories.map((cat) => {
          const Icon = cat.icon;
          return (
            <section
              key={cat.id}
              className="ds-card rounded-[8px] p-5 flex flex-col gap-3 min-h-[360px]"
              aria-label={cat.name}
            >
              {/* Category Header (No icon badge container) */}
              <div className="flex items-center gap-2.5 pb-3 border-b border-[var(--ds-border-subtle)]">
                <Icon className="w-4 h-4 text-[var(--ds-chart-blue)] shrink-0" />
                <h3 className="text-sm font-semibold text-[var(--ds-text-primary)] font-heading">
                  {cat.name}
                </h3>
              </div>

              {/* Phrase Buttons List (8px rounding) */}
              <div className="flex flex-col gap-2">
                {cat.phrases.map((item) => {
                  const isActive = activePhrase === item.text;
                  return (
                    <button
                      key={item.text}
                      type="button"
                      onClick={() => onSpeakPhrase(item.text)}
                      className={`w-full text-left p-3 rounded-[8px] border transition-all text-xs flex items-center justify-between group cursor-pointer active:scale-[0.96] ${
                        isActive
                          ? 'bg-[var(--ds-surface-subtle)] border-[var(--ds-chart-blue)] text-[var(--ds-text-primary)] font-semibold shadow-sm'
                          : 'ds-tile hover:border-[var(--ds-border-strong)] text-[var(--ds-text-secondary)] hover:text-[var(--ds-text-primary)]'
                      }`}
                      aria-label={`Speak phrase: ${item.text}`}
                    >
                      <span className="font-medium leading-relaxed pr-2">
                        {item.text}
                      </span>
                      <Speech className="w-3.5 h-3.5 text-[var(--ds-chart-blue)] group-hover:scale-110 shrink-0 transition-transform" />
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
