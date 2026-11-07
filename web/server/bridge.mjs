import dgram from 'node:dgram'
import { WebSocketServer, WebSocket } from 'ws'
import { createMovementMorseDecoder } from './morse.mjs'

const args = process.argv.slice(2)
function option(name, fallback) {
  const index = args.indexOf(name)
  return index >= 0 ? args[index + 1] : fallback
}

const source = option('--source', 'live')
const morseMode = option('--morse', 'built-in')
if (!['live', 'replay'].includes(source) || !['built-in', 'external'].includes(morseMode)) {
  console.error('Use --source live|replay and --morse built-in|external')
  process.exit(2)
}

const eegPort = Number(option('--eeg-port', '9999'))
const telemetryPort = Number(option('--telemetry-port', '9996'))
const morsePort = Number(option('--morse-port', '9998'))
const commandPort = Number(option('--command-port', '9997'))
const wsPort = Number(option('--ws-port', '8765'))
const host = '127.0.0.1'
const timeoutMs = 3000
let lastPredictionAt = 0
let lastSignalAt = 0
let decoderConnected = false
let signalConnected = false
let lastState = 'rest'
let streamId = ''
const channels = new Map()
const dirty = new Map()
const armed = new Set()

function localOrigin({ origin }) {
  if (!origin) return true // Native clients and the integration tests omit Origin.
  try { return ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(origin).hostname) }
  catch { return false }
}

const websocket = new WebSocketServer({ host, port: wsPort, maxPayload: 4096, verifyClient: localOrigin })
const eegSocket = dgram.createSocket('udp4')
const telemetrySocket = dgram.createSocket('udp4')
const morseSocket = morseMode === 'external' ? dgram.createSocket('udp4') : null

function read(raw) {
  try {
    const data = JSON.parse(raw.toString('utf8'))
    return data && typeof data === 'object' && !Array.isArray(data) ? data : null
  } catch { return null }
}

function encode(event) {
  return JSON.stringify({ ...event, source, timestamp_ms: Date.now() })
}

function broadcast(event) {
  const payload = encode(event)
  for (const client of websocket.clients) {
    if (client.readyState === WebSocket.OPEN && client.bufferedAmount < 512 * 1024) {
      client.send(payload)
    }
  }
}

const decoder = createMovementMorseDecoder((update) => broadcast({ ...update, type: 'decoder_update' }))
let externalSnapshot = null

function disarm(client) {
  if (armed.delete(client) && armed.size === 0) decoder.disconnect()
}

websocket.on('connection', (client) => {
  client.send(encode({
    type: 'status', connected: decoderConnected, morse_mode: morseMode,
    message: decoderConnected ? 'Movement decoder receiving samples' : 'Waiting for movement decoder',
  }))
  client.send(encode({ type: 'eeg_status', connected: signalConnected }))
  if (channels.size) client.send(encode({ type: 'eeg_frame', channels: [...channels.values()] }))
  const snapshot = morseSocket ? externalSnapshot : decoder.snapshot()
  if (snapshot) client.send(encode({ ...snapshot, type: 'decoder_update' }))
  client.on('close', () => disarm(client))
  client.on('message', (raw) => {
    const request = read(raw)
    if (request?.type !== 'decoder_command') return
    if (request.action === 'arm' && !morseSocket) armed.add(client)
    if (request.action === 'disarm' && !morseSocket) disarm(client)
    if (!['backspace', 'clear'].includes(request.action)) return
    if (morseSocket) morseSocket.send(JSON.stringify(request), commandPort, host)
    else if (request.action === 'backspace') decoder.backspace()
    else decoder.clear()
  })
})

eegSocket.on('message', (raw) => {
  const packet = read(raw)
  if (typeof packet?.state !== 'string' || !packet.probs || typeof packet.probs !== 'object') return
  lastPredictionAt = Date.now()
  if (!decoderConnected) {
    decoderConnected = true
    broadcast({ type: 'status', connected: true, message: 'Movement decoder receiving samples' })
  }
  const { state, probs, event, latency_ms: latency } = packet
  broadcast({ type: 'prediction', state, confidence: probs[state], latency_ms: Number.isFinite(latency) ? latency : undefined })
  if (lastState !== 'rest' && state !== lastState) {
    broadcast({ type: 'movement_end', movement: lastState })
  }
  if (typeof event === 'string' && event && event !== 'rest') {
    const confidence = Number.isFinite(probs[event]) ? probs[event] : undefined
    broadcast({ type: 'movement_start', movement: event, confidence })
    // The upstream decoder has already applied its configured confidence threshold.
    if (armed.size && !morseSocket) decoder.movement(event)
  }
  lastState = state
})

telemetrySocket.on('message', (raw) => {
  const packet = read(raw)
  if (packet?.type !== 'eeg_channel' || packet.source !== source ||
      typeof packet.stream_id !== 'string' || typeof packet.channel !== 'string' ||
      !Number.isInteger(packet.channel_count) || packet.channel_count < 1 ||
      !Number.isInteger(packet.channel_index) || packet.channel_index < 0 ||
      packet.channel_index >= packet.channel_count || !Array.isArray(packet.waveform?.values) ||
      !Array.isArray(packet.waveform.time_s) ||
      packet.waveform.values.length !== packet.waveform.time_s.length ||
      !packet.waveform.values.every(Number.isFinite) ||
      !packet.waveform.time_s.every(Number.isFinite)) return
  if (packet.stream_id !== streamId) {
    streamId = packet.stream_id
    channels.clear()
    dirty.clear()
  }
  const frame = { ...packet, timestamp_ms: Date.now() }
  channels.set(packet.channel_index, frame)
  dirty.set(packet.channel_index, frame)
  if (!packet.waveform.values.length) return
  lastSignalAt = frame.timestamp_ms
  if (!signalConnected) {
    signalConnected = true
    broadcast({ type: 'eeg_status', connected: true })
  }
})

morseSocket?.on('message', (raw) => {
  const packet = read(raw)
  if (!packet || typeof packet.text !== 'string') return
  externalSnapshot = {
    pending_symbols: typeof packet.pending_symbols === 'string' ? packet.pending_symbols : '',
    written_morse: typeof packet.written_morse === 'string' ? packet.written_morse : undefined,
    text: packet.text,
    decoder_state: typeof packet.decoder_state === 'string' ? packet.decoder_state : undefined,
    confidence: Number.isFinite(packet.confidence) ? packet.confidence : undefined,
  }
  broadcast({ type: 'decoder_update', ...externalSnapshot,
    spoken_word: typeof packet.spoken_word === 'string' ? packet.spoken_word : undefined })
})

const sockets = [[eegSocket, eegPort], [telemetrySocket, telemetryPort]]
if (morseSocket) sockets.push([morseSocket, morsePort])
for (const [socket, port] of sockets) {
  socket.on('error', (error) => {
    console.error(`SignalSpeak UDP port ${port}: ${error.message}`)
    process.exit(1)
  })
  socket.bind(port, host)
}

setInterval(() => {
  if (dirty.size) {
    broadcast({ type: 'eeg_frame', channels: [...dirty.values()] })
    dirty.clear()
  }
  const now = Date.now()
  if (decoderConnected && now - lastPredictionAt > timeoutMs) {
    if (lastState !== 'rest') broadcast({ type: 'movement_end', movement: lastState })
    decoderConnected = false
    decoder.disconnect()
    broadcast({ type: 'status', connected: false, message: 'Movement decoder stopped sending' })
    lastState = 'rest'
  }
  if (signalConnected && now - lastSignalAt > timeoutMs) {
    signalConnected = false
    broadcast({ type: 'eeg_status', connected: false })
  }
}, 100).unref()

websocket.on('listening', () => {
  console.log(`SignalSpeak · ws://${host}:${wsPort} · decoder UDP ${eegPort} · EEG telemetry UDP ${telemetryPort} · source ${source} · Morse ${morseMode}`)
})
