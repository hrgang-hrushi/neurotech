import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createMorseDecoder } from '../src/morse.mjs'
import { createMovementMorseDecoder } from './morse.mjs'

test('movement events translate letter gaps and speak each completed word once', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const updates = []
  const decoder = createMovementMorseDecoder((update) => updates.push(update))
  assert.equal(decoder.movement('rest'), false)
  assert.equal(decoder.movement(null), false)

  decoder.movement('left')
  t.mock.timers.tick(1700)
  decoder.movement('right')
  assert.equal(updates.at(-1).pending_symbols, '.-')
  t.mock.timers.tick(2600)
  assert.equal(updates.at(-1).text, 'A')
  assert.equal(updates.at(-1).spoken_word, undefined)
  t.mock.timers.tick(3200)
  assert.equal(updates.at(-1).spoken_word, 'A')
  assert.equal(decoder.snapshot().spoken_word, undefined)

  decoder.movement('left')
  t.mock.timers.tick(2600)
  t.mock.timers.tick(3200)
  assert.equal(updates.at(-1).text, 'A E')
  assert.equal(updates.at(-1).written_morse, '.- / . /')
  assert.deepEqual(updates.flatMap(({ spoken_word }) => spoken_word ?? []), ['A', 'E'])
})

test('invalid sequences are visible and do not emit speech', () => {
  const updates = []
  const decoder = createMorseDecoder((update) => updates.push(update))
  for (const symbol of '------') decoder.symbol(symbol)
  decoder.commitWord()
  assert.equal(updates.at(-1).text, '�')
  assert.equal(updates.at(-1).spoken_word, undefined)
  assert.match(updates.at(-1).decoder_state, /unrecognized/)
})

test('editing and disconnect cancel stale word timers', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const updates = []
  const decoder = createMovementMorseDecoder((update) => updates.push(update))

  decoder.movement('left')
  decoder.movement('right')
  decoder.backspace()
  assert.equal(decoder.snapshot().written_morse, '.')
  t.mock.timers.tick(2600)
  assert.equal(decoder.snapshot().text, 'E')
  decoder.movement('right')
  decoder.disconnect()
  t.mock.timers.tick(10_000)
  assert.equal(decoder.snapshot().text, 'E')
  assert.equal(decoder.snapshot().pending_symbols, '-')
  assert.equal(decoder.snapshot().decoder_state, 'Input paused')
  assert.ok(updates.every((update) => update.spoken_word === undefined))

  decoder.movement('right')
  decoder.clear()
  t.mock.timers.tick(10_000)
  assert.deepEqual(decoder.snapshot(), {
    pending_symbols: '', written_morse: '', text: '', decoder_state: 'Ready for a symbol',
  })
})
