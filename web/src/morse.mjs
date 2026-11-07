const characters = {
  '.-': 'A', '-...': 'B', '-.-.': 'C', '-..': 'D', '.': 'E', '..-.': 'F',
  '--.': 'G', '....': 'H', '..': 'I', '.---': 'J', '-.-': 'K', '.-..': 'L',
  '--': 'M', '-.': 'N', '---': 'O', '.--.': 'P', '--.-': 'Q', '.-.': 'R',
  '...': 'S', '-': 'T', '..-': 'U', '...-': 'V', '.--': 'W', '-..-': 'X',
  '-.--': 'Y', '--..': 'Z',
  '-----': '0', '.----': '1', '..---': '2', '...--': '3', '....-': '4',
  '.....': '5', '-....': '6', '--...': '7', '---..': '8', '----.': '9',
  '.-.-.-': '.', '--..--': ',', '..--..': '?', '.----.': "'", '-.-.--': '!',
  '-..-.': '/', '-.--.': '(', '-.--.-': ')', '.-...': '&', '---...': ':',
  '-.-.-.': ';', '-...-': '=', '.-.-.': '+', '-....-': '-', '..--.-': '_',
  '.-..-.': '"', '...-..-': '$', '.--.-.': '@',
}

const referenceOrder = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
export const morseReference = Object.entries(characters)
  .filter(([, letter]) => referenceOrder.includes(letter))
  .sort(([, a], [, b]) => referenceOrder.indexOf(a) - referenceOrder.indexOf(b))

const unknown = '�'
const maxLetterSymbols = Math.max(...Object.keys(characters).map((sequence) => sequence.length))

/** Translate a stream of dots and dashes without assuming a source or a speech API. */
export function createMorseDecoder(onUpdate, { letterGapMs = 900, wordGapMs = 2200 } = {}) {
  if (!Number.isFinite(letterGapMs) || !Number.isFinite(wordGapMs)
    || letterGapMs <= 0 || wordGapMs <= letterGapMs) {
    throw new RangeError('The Morse word gap must exceed the positive letter gap')
  }

  const letters = []
  let pending = ''
  let state = 'Ready for a symbol'
  let letterTimer
  let wordTimer

  function snapshot() {
    const sequences = letters.map((letter) => letter?.symbols ?? '/')
    if (pending) sequences.push(pending)
    return {
      pending_symbols: pending,
      written_morse: sequences.join(' '),
      text: letters.map((letter) => letter?.character ?? ' ').join('').trimEnd(),
      decoder_state: state,
    }
  }

  function publish(spokenWord) {
    const update = snapshot()
    if (spokenWord) update.spoken_word = spokenWord
    onUpdate(update)
  }

  function dispose() {
    clearTimeout(letterTimer)
    clearTimeout(wordTimer)
  }

  function recordLetter() {
    if (!pending) return false
    const character = characters[pending] ?? unknown
    letters.push({ symbols: pending, character })
    pending = ''
    state = character === unknown ? 'Unrecognized sequence' : 'Letter translated'
    return true
  }

  function commitLetter() {
    clearTimeout(letterTimer)
    if (recordLetter()) publish()
  }

  function commitWord() {
    dispose()
    recordLetter()
    const boundary = letters.lastIndexOf(null)
    const word = letters.slice(boundary + 1).map((letter) => letter.character).join('')
    if (!word) return

    letters.push(null)
    const recognized = !word.includes(unknown)
    state = recognized ? 'Word translated' : 'Word contains an unrecognized sequence'
    publish(recognized && /[A-Z0-9]/.test(word) ? word : undefined)
  }

  function symbol(value) {
    if (value !== '.' && value !== '-') return false
    if (pending.length === maxLetterSymbols) {
      state = 'Sequence is full. End the letter or backspace.'
      publish()
      return false
    }

    dispose()
    pending += value
    state = 'Listening for more symbols'
    letterTimer = setTimeout(commitLetter, letterGapMs)
    wordTimer = setTimeout(commitWord, wordGapMs)
    publish()
    return true
  }

  function backspace() {
    dispose()
    if (pending) {
      pending = pending.slice(0, -1)
      if (pending) letterTimer = setTimeout(commitLetter, letterGapMs)
    } else {
      if (letters.at(-1) === null) letters.pop()
      letters.pop()
    }
    state = 'Backspace applied'
    publish()
  }

  function clear() {
    dispose()
    letters.length = 0
    pending = ''
    state = 'Ready for a symbol'
    publish()
  }

  function pause() {
    dispose()
    if (state === 'Input paused') return
    state = 'Input paused'
    publish()
  }

  return { symbol, commitLetter, commitWord, backspace, clear, pause, dispose, snapshot }
}
