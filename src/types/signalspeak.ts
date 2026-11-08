export type Source = 'live' | 'replay' | 'manual';

export type NavTab = 'Message Studio' | 'EEG Monitor' | 'Decoder' | 'Phrase Board' | 'Sessions' | 'Settings';

export interface EegChannelSample {
  channel: string;
  index: number;
  impedanceKohm: number;
  sampleRateHz: number;
  microvolts: number;
}

export interface DecoderProbs {
  rest: number;
  left: number;
  right: number;
  feet: number;
}

export interface MovementEvent {
  timestampMs: number;
  state: 'rest' | 'left' | 'right' | 'feet';
  event: 'left' | 'right' | null;
  confidence: number;
  latencyMs: number;
  probs: DecoderProbs;
}

export interface PhraseOption {
  id: string;
  phrase: string;
  subtitle: string;
  category: 'urgent' | 'social' | 'comfort';
}
