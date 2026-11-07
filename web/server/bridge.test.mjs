import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import dgram from 'node:dgram'
import WebSocket from 'ws'

function waitFor(predicate, timeout = 5000) {
  return new Promise((resolve, reject) => {
    const started = Date.now()
    const timer = setInterval(() => {
      if (predicate()) { clearInterval(timer); resolve() }
      else if (Date.now() - started > timeout) { clearInterval(timer); reject(new Error('Timed out waiting for bridge event')) }
    }, 20)
  })
}

test('native EEG UDP packets and Morse updates reach the WebSocket with source and disconnect state', async () => {
  const base = 21000 + (process.pid % 10000) * 3
  const eegPort = base
  const morsePort = base + 1
  const wsPort = base + 2
  const commandPort = base + 3
  const child = spawn(process.execPath, ['server/bridge.mjs', '--source', 'replay',
    '--eeg-port', String(eegPort), '--morse-port', String(morsePort), '--ws-port', String(wsPort),
    '--command-port', String(commandPort)],
  { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'pipe'] })
  const eeg = dgram.createSocket('udp4')
  const morse = dgram.createSocket('udp4')
  const commands = dgram.createSocket('udp4')
  let socket
  try {
    await new Promise((resolve) => commands.bind(commandPort, '127.0.0.1', resolve))
    await new Promise((resolve, reject) => {
      child.stdout.once('data', resolve)
      child.once('error', reject)
      child.once('exit', (code) => reject(new Error('Bridge exited early: ' + code)))
    })
    socket = new WebSocket('ws://127.0.0.1:' + wsPort)
    const seen = []
    socket.on('message', (bytes) => seen.push(JSON.parse(bytes.toString())))
    await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject) })
    await waitFor(() => seen.some((event) => event.type === 'status' && !event.connected))
    eeg.send(JSON.stringify({
      t: 1.2, probs: { rest: 0.1, left: 0.8, right: 0.1 },
      state: 'left', event: 'left', latency_ms: 40,
    }), eegPort, '127.0.0.1')
    await waitFor(() => seen.some((event) => event.type === 'movement_start'))
    const movement = seen.find((event) => event.type === 'movement_start')
    assert.equal(movement.source, 'replay')
    assert.equal(movement.movement, 'left')
    assert.equal(movement.confidence, 0.8)
    assert.ok(seen.some((event) => event.type === 'status' && event.connected))
    morse.send(JSON.stringify({ pending_symbols: '.-', text: 'A' }), morsePort, '127.0.0.1')
    await waitFor(() => seen.some((event) => event.type === 'decoder_update'))
    assert.equal(seen.find((event) => event.type === 'decoder_update').text, 'A')
    let command
    commands.once('message', (raw) => { command = JSON.parse(raw.toString()) })
    socket.send(JSON.stringify({ type: 'decoder_command', action: 'backspace' }))
    await waitFor(() => command)
    assert.deepEqual(command, { type: 'decoder_command', action: 'backspace' })
    eeg.send(JSON.stringify({ probs: { rest: 0.9, left: 0.1 }, state: 'rest', event: null }),
      eegPort, '127.0.0.1')
    await waitFor(() => seen.some((event) => event.type === 'movement_end'))
    await waitFor(() => seen.filter((event) => event.type === 'status' && !event.connected).length >= 2)
  } finally {
    socket?.close()
    eeg.close()
    morse.close()
    commands.close()
    child.kill()
  }
})
