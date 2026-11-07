export const morseReference: ReadonlyArray<readonly [string, string]>

export type MorseUpdate = {
  pending_symbols: string
  written_morse: string
  text: string
  decoder_state: string
  spoken_word?: string
}

export type MorseDecoder = {
  symbol: (symbol: '.' | '-') => boolean
  commitLetter: () => void
  commitWord: () => void
  backspace: () => void
  clear: () => void
  pause: () => void
  dispose: () => void
  snapshot: () => MorseUpdate
}

export function createMorseDecoder(
  onUpdate: (update: MorseUpdate) => void,
  options?: { letterGapMs?: number; wordGapMs?: number },
): MorseDecoder
