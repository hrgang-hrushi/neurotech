export const MORSE_MAP: Record<string, string> = {
  '.-': 'A', '-...': 'B', '-.-.': 'C', '-..': 'D', '.': 'E', '..-.': 'F',
  '--.': 'G', '....': 'H', '..': 'I', '.---': 'J', '-.-': 'K', '.-..': 'L',
  '--': 'M', '-.': 'N', '---': 'O', '.--.': 'P', '--.-': 'Q', '.-.': 'R',
  '...': 'S', '-': 'T', '..-': 'U', '...-': 'V', '.--': 'W', '-..-': 'X',
  '-.--': 'Y', '--..': 'Z',
  '-----': '0', '.----': '1', '..---': '2', '...--': '3', '....-': '4',
  '.....': '5', '-....': '6', '--...': '7', '---..': '8', '----.': '9',
  '.-.-.-': '.', '--..--': ',', '..--..': '?',
};

export const REVERSE_MORSE: Record<string, string> = Object.fromEntries(
  Object.entries(MORSE_MAP).map(([code, char]) => [char, code])
);

/** Text -> Morse: letters separated by spaces, words by ' / '. Characters without a code are skipped. */
export function encodeMorse(text: string): string {
  return text
    .toUpperCase()
    .split(/\s+/)
    .map((word) => Array.from(word).map((ch) => REVERSE_MORSE[ch]).filter(Boolean).join(' '))
    .filter(Boolean)
    .join(' / ');
}

export interface MorseSnapshot {
  pendingSymbols: string;
  writtenMorse: string;
  text: string;
  decoderState: string;
  spokenWord?: string;
}

export function speakText(text: string, onEnd?: () => void) {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.0;
  utterance.pitch = 1.0;
  if (onEnd) utterance.onend = onEnd;
  window.speechSynthesis.speak(utterance);
}

export interface MorseController {
  symbol: (val: '.' | '-') => boolean;
  commitLetter: () => void;
  commitWord: () => void;
  backspace: () => void;
  clear: () => void;
  getSnapshot: () => MorseSnapshot;
  loadText: (presetText: string) => void;
}

export function createMorseController(
  onUpdate: (snapshot: MorseSnapshot) => void,
  options: { letterGapMs?: number; wordGapMs?: number } = {}
): MorseController {
  const letterGapMs = options.letterGapMs ?? 950;
  const wordGapMs = options.wordGapMs ?? 2200;

  let letters: Array<{ symbols: string; character: string } | null> = [];
  let pending = '';
  let state = 'Ready for a symbol';
  let letterTimer: NodeJS.Timeout | null = null;
  let wordTimer: NodeJS.Timeout | null = null;

  function snapshot(spokenWord?: string): MorseSnapshot {
    const sequences = letters.map((l) => (l ? l.symbols : '/'));
    if (pending) sequences.push(pending);
    return {
      pendingSymbols: pending,
      writtenMorse: sequences.join(' '),
      text: letters.map((l) => (l ? l.character : ' ')).join('').trimEnd(),
      decoderState: state,
      spokenWord,
    };
  }

  function publish(spokenWord?: string) {
    onUpdate(snapshot(spokenWord));
  }

  function dispose() {
    if (letterTimer) clearTimeout(letterTimer);
    if (wordTimer) clearTimeout(wordTimer);
    letterTimer = null;
    wordTimer = null;
  }

  function recordLetter(): boolean {
    if (!pending) return false;
    const char = MORSE_MAP[pending] ?? '';
    letters.push({ symbols: pending, character: char });
    pending = '';
    state = char === '' ? 'Unrecognized sequence' : 'Letter translated';
    return true;
  }

  function commitLetter() {
    if (letterTimer) clearTimeout(letterTimer);
    letterTimer = null;
    if (recordLetter()) publish();
  }

  function commitWord() {
    dispose();
    recordLetter();
    const boundary = letters.lastIndexOf(null);
    const word = letters.slice(boundary + 1).map((l) => l?.character ?? '').join('');
    if (!word) return;

    letters.push(null);
    const recognized = !word.includes('');
    state = recognized ? 'Word translated' : 'Word contains unrecognized sequence';
    publish(recognized && /[A-Z0-9]/.test(word) ? word : undefined);
  }

  function symbol(val: '.' | '-'): boolean {
    if (pending.length >= 6) {
      state = 'Sequence full. End letter or backspace.';
      publish();
      return false;
    }
    dispose();
    pending += val;
    state = 'Listening for more symbols';
    letterTimer = setTimeout(commitLetter, letterGapMs);
    wordTimer = setTimeout(commitWord, wordGapMs);
    publish();
    return true;
  }

  function backspace() {
    dispose();
    if (pending) {
      pending = pending.slice(0, -1);
      if (pending) letterTimer = setTimeout(commitLetter, letterGapMs);
    } else {
      if (letters.at(-1) === null) letters.pop();
      letters.pop();
    }
    state = 'Backspace applied';
    publish();
  }

  function clear() {
    dispose();
    letters = [];
    pending = '';
    state = 'Ready for a symbol';
    publish();
  }

  function loadText(presetText: string) {
    dispose();
    letters = [];
    pending = '';
    const upper = presetText.toUpperCase();
    for (let i = 0; i < upper.length; i++) {
      const ch = upper[i];
      if (ch === ' ') {
        letters.push(null);
      } else if (REVERSE_MORSE[ch]) {
        letters.push({ symbols: REVERSE_MORSE[ch], character: ch });
      }
    }
    state = 'Loaded pre-set phrase';
    publish();
  }

  return {
    symbol,
    commitLetter,
    commitWord,
    backspace,
    clear,
    getSnapshot: () => snapshot(),
    loadText,
  };
}
