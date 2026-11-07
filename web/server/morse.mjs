import { createMorseDecoder } from '../src/morse.mjs'

/** Map the movement decoder's confirmed class events to Morse key presses. */
export function createMovementMorseDecoder(onUpdate, {
  dotMovement = 'left',
  dashMovement = 'right',
  letterGapMs = 2600,
  wordGapMs = 5800,
} = {}) {
  const decoder = createMorseDecoder(onUpdate, { letterGapMs, wordGapMs })

  function movement(event) {
    if (event === dotMovement) return decoder.symbol('.')
    if (event === dashMovement) return decoder.symbol('-')
    return false
  }

  return { ...decoder, movement, disconnect: decoder.pause }
}
