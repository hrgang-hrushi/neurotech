'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Navbar, ActiveTab, Source } from '@/components/Navbar';
import { MessageStudio } from '@/components/MessageStudio';
import { PhraseBoard } from '@/components/PhraseBoard';
import { EegMonitor } from '@/components/EegMonitor';
import { ShortcutsModal } from '@/components/ShortcutsModal';
import { createMorseController, MorseController, MorseSnapshot, speakText } from '@/lib/morse';

export default function DotReaderApp() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('Message Studio');
  const [source, setSource] = useState<Source>('manual');

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const hash = window.location.hash.toLowerCase();
      if (hash.includes('phrase')) setActiveTab('Phrase Board');
      else if (hash.includes('eeg')) setActiveTab('EEG Monitor');
    }
  }, []);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [recentMessages, setRecentMessages] = useState<string[]>([
    'I NEED WATER',
    'THANK YOU',
  ]);

  const [morseState, setMorseState] = useState<MorseSnapshot>({
    pendingSymbols: '',
    writtenMorse: '',
    text: '',
    decoderState: 'Ready for a symbol (use keys . and -)',
  });

  const controllerRef = useRef<MorseController | null>(null);

  // Initialize Morse Decoder Controller
  useEffect(() => {
    controllerRef.current = createMorseController((snap) => {
      setMorseState(snap);
      if (snap.spokenWord && autoSpeak) {
        handleSpeak(snap.spokenWord);
      }
    });

    return () => {
      // cleanup if needed
    };
  }, [autoSpeak]);

  // Voice vocalization helper
  const handleSpeak = (textToSpeak: string) => {
    const trimmed = textToSpeak.trim();
    if (!trimmed) return;
    setIsSpeaking(true);
    setRecentMessages((prev) => [trimmed, ...prev.filter((m) => m !== trimmed)].slice(0, 6));
    speakText(trimmed, () => setIsSpeaking(false));
  };

  // Keyboard shortcut listener for BCI triggers
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      if (e.key === '.' || e.key === 'd' || e.key === 'ArrowLeft') {
        e.preventDefault();
        controllerRef.current?.symbol('.');
      } else if (e.key === '-' || e.key === '_' || e.key === 'f' || e.key === 'ArrowRight') {
        e.preventDefault();
        controllerRef.current?.symbol('-');
      } else if (e.key === ' ') {
        e.preventDefault();
        controllerRef.current?.commitLetter();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        controllerRef.current?.commitWord();
      } else if (e.key === 'Backspace') {
        e.preventDefault();
        controllerRef.current?.backspace();
      } else if (e.key === 'Escape') {
        setIsHelpOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handlePhraseSelect = (phrase: string) => {
    controllerRef.current?.loadText(phrase);
    handleSpeak(phrase);
  };

  return (
    <div className="w-full min-h-screen bg-[var(--ds-bg)] text-[var(--ds-text-primary)] flex flex-col selection:bg-white/20 selection:text-white">
      {/* 1. Full-Width Expanded Top Navigation Bar */}
      <Navbar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        source={source}
        onSourceChange={setSource}
        isSpeaking={isSpeaking}
        onOpenHelp={() => setIsHelpOpen(true)}
      />

      {/* 2. Main Tab View (Expanded to max-w-6xl with Balanced Spacing) */}
      <main className="w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-8 flex-1">
        {activeTab === 'Message Studio' && (
          <MessageStudio
            text={morseState.text}
            writtenMorse={morseState.writtenMorse}
            pendingSymbols={morseState.pendingSymbols}
            decoderState={morseState.decoderState}
            autoSpeak={autoSpeak}
            onToggleAutoSpeak={() => setAutoSpeak(!autoSpeak)}
            onSymbol={(val) => controllerRef.current?.symbol(val)}
            onCommitLetter={() => controllerRef.current?.commitLetter()}
            onCommitWord={() => controllerRef.current?.commitWord()}
            onBackspace={() => controllerRef.current?.backspace()}
            onClear={() => controllerRef.current?.clear()}
            onSpeak={() => handleSpeak(morseState.text)}
            recentMessages={recentMessages}
            onSelectRecent={handleSpeak}
          />
        )}

        {activeTab === 'Phrase Board' && (
          <PhraseBoard
            onSpeakPhrase={handlePhraseSelect}
            activePhrase={morseState.text}
          />
        )}

        {activeTab === 'EEG Monitor' && <EegMonitor />}
      </main>

      {/* 3. Shortcuts Modal */}
      <ShortcutsModal isOpen={isHelpOpen} onClose={() => setIsHelpOpen(false)} />
    </div>
  );
}
