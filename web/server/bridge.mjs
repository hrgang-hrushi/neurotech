import dgram from 'node:dgram'
import { WebSocketServer } from 'ws'

const args = process.argv.slice(2)
function option(name, fallback) {
  const index = args.indexOf(name)
  return index >= 0 ? args[index + 1] : fallback
}

const source = option('--source', 'live')
if (!['live', 'replay'].includes(source)) {
  console.error('Use --source live or --source replay')
  process.exit(2)
}
const eegPort = Number(option('--eeg-port', '9999'))
const morsePort = Number(option('--morse-port', '9998'))
const commandPort = Number(option('--command-port', '9997'))
const wsPort = Number(option('--ws-port', '8765'))
const host = '127.0.0.1'
const timeoutMs = 3000
let lastEegAt = 0
let connected = false
let lastState = 'rest'

const websocket = new WebSocketServer({ host, port: wsPort })
const eegSocket = dgram.createSocket('udp4')
const morseSocket = dgram.createSocket('udp4')

function broadcast(event) {
  const payload = JSON.stringify({ ...event, source, timestamp_ms: Date.now() })
  for (const client of websocket.clients) {
    if (client.readyState === 1) client.send(payload)
  }
}
function status(isConnected, message) {
  connected = isConnected
  broadcast({ type: 'status', connected, message })
}

websocket.on('connection', (client) => {
  client.send(JSON.stringify({
    type: 'status', source, timestamp_ms: Date.now(), connected,
    message: connected ? 'EEG packets arriving from the local decoder'
      : 'Bridge ready; waiting for EEG packets on UDP port ' + eegPort,
  }))
  client.on('message', (raw) => {
    let request
    try { request = JSON.parse(raw.toString('utf8')) } catch { return }
    if (request?.type !== 'decoder_command' || !['backspace', 'clear'].includes(request.action)) return
    morseSocket.send(JSON.stringify({ type: 'decoder_command', action: request.action }), commandPort, host)
  })
})

eegSocket.on('message', (raw) => {
  let packet
  try { packet = JSON.parse(raw.toString('utf8')) } catch { return }
  if (!packet || typeof packet !== 'object') return
  lastEegAt = Date.now()
  if (!connected) status(true, 'EEG packets arriving from the local decoder')
  const probs = packet.probs && typeof packet.probs === 'object' ? packet.probs : {}
  const state = typeof packet.state === 'string' ? packet.state : 'unknown'
  const score = typeof probs[state] === 'number' ? probs[state] : undefined
  broadcast({
    type: 'prediction', state, confidence: score,
    latency_ms: typeof packet.latency_ms === 'number' ? packet.latency_ms : undefined,
  })
  if (typeof packet.event === 'string' && packet.event) {
    const eventScore = typeof probs[packet.event] === 'number' ? probs[packet.event] : undefined
    broadcast({ type: 'movement_start', movement: packet.event, confidence: eventScore })
  }
  if (state === 'rest' && lastState !== 'rest') {
    broadcast({ type: 'movement_end', movement: lastState })
  }
  lastState = state
})

morseSocket.on('message', (raw) => {
  let packet
  try { packet = JSON.parse(raw.toString('utf8')) } catch { return }
  if (!packet || typeof packet !== 'object') return
  broadcast({
    type: 'decoder_update',
    pending_symbols: typeof packet.pending_symbols === 'string' ? packet.pending_symbols : '',
    text: typeof packet.text === 'string' ? packet.text : '',
    decoder_state: typeof packet.decoder_state === 'string' ? packet.decoder_state : undefined,
    confidence: typeof packet.confidence === 'number' ? packet.confidence : undefined,
  })
})

eegSocket.bind(eegPort, host)
morseSocket.bind(morsePort, host)
setInterval(() => {
  if (connected && Date.now() - lastEegAt > timeoutMs) {
    if (lastState !== 'rest') broadcast({ type: 'movement_end', movement: lastState })
    status(false, 'No EEG packets for 3 seconds; check the decoder or LSL stream')
    lastState = 'rest'
  }
}, 500).unref()

websocket.on('listening', () => {
  console.log(`SignalSpeak bridge: EEG udp://${host}:${eegPort}, Morse udp://${host}:${morsePort}, Morse commands udp://${host}:${commandPort}, UI ws://${host}:${wsPort}, source=${source}`)
  console.log('Run this instead of eegmove listen; both cannot bind UDP port 9999.')
})
