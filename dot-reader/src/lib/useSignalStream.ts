'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { Source } from '@/components/Navbar';
import { createMorseController, MorseController, MorseSnapshot, speakText } from './morse';

export interface EegChannel {
  type: 'eeg_channel';
  source: 'live' | 'replay';
  timestamp_ms: number;
  stream_id: string;
  stream_name: string;
  channel: string;
  channel_index: number;
  channel_count: number;
  sample_rate_hz: number;
  unit: string | null;
  waveform: { time_s: number[]; values: number[] };
  spectrum: { frequency_hz: number[]; power_density: number[] } | null;
}

export interface SignalEvent {
  type: 'status' | 'prediction' | 'movement_start' | 'movement_end' | 'decoder_update' | 'eeg_status' | 'eeg_frame';
  source: Source;
  timestamp_ms: number;
  connected?: boolean;
  message?: string;
  movement?: string;
  confidence?: number;
  state?: string;
  latency_ms?: number;
  pending_symbols?: string;
  written_morse?: string;
  text?: string;
  decoder_state?: string;
  spoken_word?: string;
  morse_mode?: 'built-in' | 'external';
  channels?: EegChannel[];
}

export interface PredictionState {
  state: string;
  confidence: number;
  latency_ms: number;
}

export function useSignalStream(source: Source, autoSpeak: boolean) {
  const [wsConnected, setWsConnected] = useState(false);
  const [decoderConnected, setDecoderConnected] = useState(false);
  const [eegConnected, setEegConnected] = useState(false);
  const [bridgeStatus, setBridgeStatus] = useState('Idle');
  const [channels, setChannels] = useState<EegChannel[]>([]);
  const [lastPrediction, setLastPrediction] = useState<PredictionState | null>(null);

  // Streaming waveform buffer for C3 & C4 (points: { time, value })
  const [c3Points, setC3Points] = useState<{ time: number; value: number }[]>([]);
  const [c4Points, setC4Points] = useState<{ time: number; value: number }[]>([]);

  // Morse state
  const [morseState, setMorseState] = useState<MorseSnapshot>({
    pendingSymbols: '',
    writtenMorse: '',
    text: '',
    decoderState: 'Ready for a symbol (use keys . and -)',
  });

  const [recentMessages, setRecentMessages] = useState<string[]>([
    'I NEED WATER',
    'THANK YOU',
  ]);

  const [isSpeaking, setIsSpeaking] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const manualControllerRef = useRef<MorseController | null>(null);

  // Vocalization handler
  const handleSpeak = useCallback((textToSpeak: string) => {
    const trimmed = textToSpeak.trim();
    if (!trimmed) return;
    setIsSpeaking(true);
    setRecentMessages((prev) => [trimmed, ...prev.filter((m) => m !== trimmed)].slice(0, 6));
    speakText(trimmed, () => setIsSpeaking(false));
  }, []);

  // Initialize local Morse controller for manual mode & fallback
  useEffect(() => {
    manualControllerRef.current = createMorseController((snap) => {
      if (source === 'manual') {
        setMorseState(snap);
        if (snap.spokenWord && autoSpeak) {
          handleSpeak(snap.spokenWord);
        }
      }
    });
  }, [source, autoSpeak, handleSpeak]);

  // WebSocket management for Live & Replay sources
  useEffect(() => {
    if (source === 'manual') {
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
      setWsConnected(false);
      setDecoderConnected(false);
      setEegConnected(false);
      setBridgeStatus('Manual Input Mode');
      return;
    }

    let active = true;
    let reconnectTimer: NodeJS.Timeout;

    const wsUrl = process.env.NEXT_PUBLIC_SIGNAL_WS_URL || 'ws://127.0.0.1:8765';

    function connect() {
      if (!active) return;
      try {
        const ws = new WebSocket(wsUrl);
        socketRef.current = ws;

        ws.onopen = () => {
          if (!active) return;
          setWsConnected(true);
          setBridgeStatus(`Connected to Bridge (${source})`);
          // Arm the bridge decoder for this client
          ws.send(JSON.stringify({ type: 'decoder_command', action: 'arm' }));
        };

        ws.onclose = () => {
          if (!active) return;
          setWsConnected(false);
          setDecoderConnected(false);
          setEegConnected(false);
          setBridgeStatus('Bridge disconnected (reconnecting...)');
          reconnectTimer = setTimeout(connect, 2000);
        };

        ws.onerror = () => {
          if (!active) return;
          ws.close();
        };

        ws.onmessage = (event) => {
          if (!active) return;
          try {
            const data: SignalEvent = JSON.parse(event.data);
            if (data.type === 'status') {
              setDecoderConnected(Boolean(data.connected));
              if (data.message) setBridgeStatus(data.message);
            } else if (data.type === 'eeg_status') {
              setEegConnected(Boolean(data.connected));
            } else if (data.type === 'prediction') {
              setLastPrediction({
                state: data.state || 'rest',
                confidence: data.confidence ?? 0,
                latency_ms: data.latency_ms ?? 0,
              });
            } else if (data.type === 'decoder_update') {
              setMorseState({
                pendingSymbols: data.pending_symbols || '',
                writtenMorse: data.written_morse || '',
                text: data.text || '',
                decoderState: data.decoder_state || 'Translating...',
                spokenWord: data.spoken_word,
              });
              if (data.spoken_word && autoSpeak) {
                handleSpeak(data.spoken_word);
              }
            } else if (data.type === 'eeg_frame' && Array.isArray(data.channels)) {
              setChannels(data.channels);

              // Extract real waveform points for C3 and C4
              const now = Date.now() / 1000;
              for (const ch of data.channels) {
                const normName = ch.channel.toUpperCase();
                if (normName.includes('C3') || ch.channel_index === 0) {
                  const values = ch.waveform.values;
                  const times = ch.waveform.time_s;
                  const newPts = values.map((val, i) => ({
                    time: now + (times[i] ?? 0),
                    value: Number(val.toFixed(2)),
                  }));
                  setC3Points((prev) => [...prev.slice(-250), ...newPts.slice(-10)]);
                } else if (normName.includes('C4') || ch.channel_index === 1) {
                  const values = ch.waveform.values;
                  const times = ch.waveform.time_s;
                  const newPts = values.map((val, i) => ({
                    time: now + (times[i] ?? 0),
                    value: Number(val.toFixed(2)),
                  }));
                  setC4Points((prev) => [...prev.slice(-250), ...newPts.slice(-10)]);
                }
              }
            }
          } catch (err) {
            console.error('Failed to parse WebSocket message:', err);
          }
        };
      } catch (err) {
        console.error('WebSocket connection error:', err);
        reconnectTimer = setTimeout(connect, 2000);
      }
    }

    connect();

    return () => {
      active = false;
      clearTimeout(reconnectTimer);
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [source, autoSpeak, handleSpeak]);

  // Actions that work seamlessly in both manual and WebSocket modes
  const sendSymbol = useCallback((symbol: '.' | '-') => {
    if (source !== 'manual' && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'decoder_command', action: 'symbol', value: symbol }));
    }
    // Also feed manual controller so local feedback is instantaneous
    manualControllerRef.current?.symbol(symbol);
  }, [source]);

  const commitLetter = useCallback(() => {
    if (source !== 'manual' && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'decoder_command', action: 'commitLetter' }));
    }
    manualControllerRef.current?.commitLetter();
  }, [source]);

  const commitWord = useCallback(() => {
    if (source !== 'manual' && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'decoder_command', action: 'commitWord' }));
    }
    manualControllerRef.current?.commitWord();
  }, [source]);

  const backspace = useCallback(() => {
    if (source !== 'manual' && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'decoder_command', action: 'backspace' }));
    }
    manualControllerRef.current?.backspace();
  }, [source]);

  const clear = useCallback(() => {
    if (source !== 'manual' && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'decoder_command', action: 'clear' }));
    }
    manualControllerRef.current?.clear();
  }, [source]);

  const loadPreset = useCallback((phrase: string) => {
    manualControllerRef.current?.loadText(phrase);
    handleSpeak(phrase);
  }, [handleSpeak]);

  return {
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
  };
}
