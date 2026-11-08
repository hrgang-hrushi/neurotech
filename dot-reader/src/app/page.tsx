'use client';

import React, { useState, useEffect } from 'react';
import { Navbar, ActiveTab, Source } from '@/components/Navbar';
import { MessageStudio } from '@/components/MessageStudio';
import { PhraseBoard } from '@/components/PhraseBoard';
import { EegMonitor } from '@/components/EegMonitor';
import { ShortcutsModal } from '@/components/ShortcutsModal';
import { useSignalStream } from '@/lib/useSignalStream';

export default function DotReaderApp() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('Message Studio');
  const [source, setSource] = useState<Source>('manual');
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [activeChannel, setActiveChannel] = useState<'C3 (Left Motor)' | 'C4 (Right Motor)'>('C3 (Left Motor)');

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const hash = window.location.hash.toLowerCase();
      if (hash.includes('phrase')) setActiveTab('Phrase Board');
      else if (hash.includes('eeg')) setActiveTab('EEG Monitor');
    }
  }, []);

  const {
    wsConnected,
    decoderConnected,
    eegConnected,
    bridgeStatus,
    channels,
    c3Points,
    c4Points,
    lastPrediction,
    morseState,
    recentMessages,
    isSpeaking,
    sendSymbol,
    commitLetter,
    commitWord,
    backspace,
    clear,
    loadPreset,
    handleSpeak,
  } = useSignalStream(source, autoSpeak);

  // Keyboard shortcut listener for BCI triggers
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      if (e.key === '.' || e.key === 'd' || e.key === 'ArrowLeft') {
        e.preventDefault();
        sendSymbol('.');
      } else if (e.key === '-' || e.key === '_' || e.key === 'f' || e.key === 'ArrowRight') {
        e.preventDefault();
        sendSymbol('-');
      } else if (e.key === ' ') {
        e.preventDefault();
        commitLetter();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        commitWord();
      } else if (e.key === 'Backspace') {
        e.preventDefault();
        backspace();
      } else if (e.key === 'Escape') {
        setIsHelpOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [sendSymbol, commitLetter, commitWord, backspace]);

  const activePoints = activeChannel.startsWith('C3') ? c3Points : c4Points;

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
        wsConnected={wsConnected}
        decoderConnected={decoderConnected}
        eegConnected={eegConnected}
        bridgeStatus={bridgeStatus}
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
            onSymbol={sendSymbol}
            onCommitLetter={commitLetter}
            onCommitWord={commitWord}
            onBackspace={backspace}
            onClear={clear}
            onSpeak={() => handleSpeak(morseState.text)}
            recentMessages={recentMessages}
            onSelectRecent={handleSpeak}
            realtimePoints={activePoints}
            isLiveFeed={source !== 'manual' && eegConnected}
            activeChannel={activeChannel}
            onChannelChange={setActiveChannel}
            prediction={lastPrediction}
          />
        )}

        {activeTab === 'Phrase Board' && (
          <PhraseBoard
            onSpeakPhrase={loadPreset}
            activePhrase={morseState.text}
          />
        )}

        {activeTab === 'EEG Monitor' && (
          <EegMonitor
            channels={channels}
            isLiveFeed={source !== 'manual' && eegConnected}
          />
        )}
      </main>

      {/* 3. Shortcuts Modal */}
      <ShortcutsModal isOpen={isHelpOpen} onClose={() => setIsHelpOpen(false)} />
    </div>
  );
}
