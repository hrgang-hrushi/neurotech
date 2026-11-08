'use client';

import React from 'react';
import {
  AudioLines,
  Speech,
  Keyboard,
  ChevronDown,
  Check,
  Sun,
  Moon,
  Radio,
  SlidersHorizontal,
  History,
  BrainCircuit,
} from 'lucide-react';
import { SegmentedControl } from './ui/SegmentedControl';

export type ActiveTab = 'Recordings' | 'Message Studio' | 'Phrase Board' | 'EEG Monitor';
export type Source = 'manual' | 'live' | 'replay';

interface NavbarProps {
  activeTab: ActiveTab;
  onTabChange: (tab: ActiveTab) => void;
  source: Source;
  onSourceChange: (source: Source) => void;
  isSpeaking?: boolean;
  onOpenHelp?: () => void;
  wsConnected?: boolean;
  decoderConnected?: boolean;
  eegConnected?: boolean;
  bridgeStatus?: string;
}

const sourceLabels: Record<Source, { title: string; subtitle: string; icon: React.ElementType }> = {
  manual: { title: 'Manual Input', subtitle: 'Keys . and - or tactile pads', icon: SlidersHorizontal },
  live: { title: 'Live EEG', subtitle: 'ANT eego 24ch amplifier', icon: Radio },
  replay: { title: 'Recorded Replay', subtitle: 'Motor imagery session dataset', icon: History },
};

export function Navbar({
  activeTab,
  onTabChange,
  source,
  onSourceChange,
  isSpeaking = false,
  onOpenHelp,
  wsConnected = false,
  decoderConnected = false,
  eegConnected = false,
  bridgeStatus,
}: NavbarProps) {
  const [isSourceOpen, setIsSourceOpen] = React.useState(false);
  const [isDark, setIsDark] = React.useState(true);

  React.useEffect(() => {
    if (typeof window !== 'undefined') {
      setIsDark(document.documentElement.classList.contains('dark'));
    }
  }, []);

  const toggleTheme = () => {
    const nextDark = !isDark;
    setIsDark(nextDark);
    if (nextDark) {
      document.documentElement.classList.add('dark');
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      document.documentElement.setAttribute('data-theme', 'light');
    }
  };

  return (
    <header className="ds-topbar" role="banner">
      <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-full flex items-center justify-between gap-4">
        {/* Left: Brand Identity */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex items-center gap-1.5" aria-hidden="true" title="SignalSpeech">
            <span className="w-2.5 h-2.5 rounded-[2px] bg-[var(--ds-chart-blue)] shadow-[0_0_8px_rgba(143,173,227,0.5)]" />
            <span className="w-5 h-1.5 rounded-[2px] bg-[var(--ds-chart-blue)] opacity-80" />
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight text-[var(--ds-text-primary)] leading-tight font-heading whitespace-nowrap">
              SignalSpeech
            </h1>
            <p className="text-[11px] text-[var(--ds-text-muted)] leading-tight font-subheading whitespace-nowrap hidden sm:block">
              Assistive Neural Morse Communicator
            </p>
          </div>
        </div>

        {/* Center: §7.11 Lane Switch / Segmented Control Tabs */}
        <div className="hidden sm:flex items-center justify-center flex-1 max-w-xl mx-auto">
          <SegmentedControl<ActiveTab>
            options={[
              { value: 'Recordings', label: 'Recordings' },
              { value: 'Message Studio', label: 'Message Studio' },
              { value: 'Phrase Board', label: 'Phrase Board' },
              { value: 'EEG Monitor', label: 'EEG Monitor' },
            ]}
            value={activeTab}
            onChange={onTabChange}
            size="md"
            variant="tray"
          />
        </div>

        {/* Right Controls: §6.2 40px Circles, Pills & §4.3 Status Dots */}
        <div className="flex items-center gap-2.5 shrink-0 relative">
          {/* Source Switcher 40px Pill */}
          <div className="relative shrink-0">
            <button
              type="button"
              onClick={() => setIsSourceOpen(!isSourceOpen)}
              className="ds-pill cursor-pointer whitespace-nowrap shrink-0"
              aria-haspopup="true"
              aria-expanded={isSourceOpen}
            >
              {React.createElement(sourceLabels[source].icon, {
                className: `w-3.5 h-3.5 shrink-0 ${source === 'live' ? 'text-[var(--ds-chart-blue)]' : 'text-[var(--ds-text-muted)]'}`,
              })}
              <span className="whitespace-nowrap">{sourceLabels[source].title}</span>
              <ChevronDown className="w-3.5 h-3.5 text-[var(--ds-text-muted)] shrink-0" />
            </button>

            {isSourceOpen && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setIsSourceOpen(false)}
                />
                <div
                  className="absolute right-0 top-12 z-50 w-64 rounded-[8px] p-2 shadow-2xl border border-[var(--ds-border)] bg-[var(--ds-surface)] animate-in fade-in duration-100"
                  role="menu"
                >
                  <div className="px-3 py-1.5 text-xs font-semibold text-[var(--ds-text-muted)] uppercase tracking-wider border-b border-[var(--ds-border-subtle)] font-heading">
                    Signal Input Source
                  </div>
                  {(['manual', 'live', 'replay'] as Source[]).map((src) => {
                    const Icon = sourceLabels[src].icon;
                    return (
                      <button
                        key={src}
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          onSourceChange(src);
                          setIsSourceOpen(false);
                        }}
                        className={`w-full text-left px-3 py-2.5 rounded-[8px] text-xs flex items-center justify-between transition-all ${
                          source === src
                            ? 'bg-[var(--ds-surface-subtle)] text-[var(--ds-text-primary)] font-medium'
                            : 'text-[var(--ds-text-secondary)] hover:text-[var(--ds-text-primary)] hover:bg-[var(--ds-surface-hover)]'
                        }`}
                      >
                        <div className="flex items-center gap-2.5">
                          <Icon className={`w-4 h-4 shrink-0 ${source === src ? 'text-[var(--ds-chart-blue)]' : 'text-[var(--ds-text-muted)]'}`} />
                          <div>
                            <div className="font-medium whitespace-nowrap">{sourceLabels[src].title}</div>
                            <div className="text-[11px] text-[var(--ds-text-muted)] whitespace-nowrap">{sourceLabels[src].subtitle}</div>
                          </div>
                        </div>
                        {source === src && <Check className="w-4 h-4 text-[var(--ds-chart-blue)] shrink-0" />}
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          {/* Theme Toggle 40px Circle */}
          <button
            type="button"
            onClick={toggleTheme}
            className="ds-circle cursor-pointer shrink-0"
            title={isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
            aria-label={isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          >
            {isDark ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-slate-700" />}
          </button>

          {/* Keyboard Help 40px Circle */}
          <button
            type="button"
            onClick={onOpenHelp}
            className="ds-circle cursor-pointer shrink-0"
            title="Keyboard Shortcuts & Reference"
            aria-label="Keyboard Shortcuts"
          >
            <Keyboard className="w-4 h-4 text-[var(--ds-text-secondary)]" />
          </button>

          {/* Signal Stream Status (when not manual) */}
          {source !== 'manual' && (
            <div
              className="ds-pill cursor-default whitespace-nowrap shrink-0 hidden md:flex"
              title={bridgeStatus || (wsConnected ? 'Connected to bridge' : 'Connecting to bridge...')}
            >
              <span
                className={`ds-stage-dot ${eegConnected ? 'ds-stage-dot-success animate-pulse' : wsConnected ? 'animate-pulse' : 'ds-stage-dot-warning'}`}
                style={{ backgroundColor: eegConnected ? '#2ee59d' : wsConnected ? 'var(--ds-chart-blue)' : undefined }}
                aria-hidden="true"
              />
              <span className="text-xs font-mono">
                {eegConnected ? 'EEG Streaming' : wsConnected ? 'Bridge Active' : 'Waiting for LSL'}
              </span>
            </div>
          )}

          {/* §4.3 Status Words + Icon + Stage Dot */}
          <div
            className="ds-pill cursor-default whitespace-nowrap shrink-0"
            title={isSpeaking ? 'Voice synthesizer active' : 'Voice synthesizer ready'}
          >
            <span
              className={`ds-stage-dot ${isSpeaking ? 'ds-stage-dot-success animate-pulse' : ''}`}
              style={{ backgroundColor: isSpeaking ? 'var(--ds-status-success)' : 'var(--ds-chart-blue)' }}
              aria-hidden="true"
            />
            {isSpeaking ? (
              <AudioLines className="w-4 h-4 text-[var(--ds-chart-blue)] animate-pulse shrink-0" />
            ) : (
              <Speech className="w-4 h-4 text-[var(--ds-text-muted)] shrink-0" />
            )}
            <span className="hidden sm:inline whitespace-nowrap">{isSpeaking ? 'Speaking' : 'Voice Ready'}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
