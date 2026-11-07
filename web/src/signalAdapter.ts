export type Source = 'live' | 'replay' | 'manual'

export type EegChannel = {
  type: 'eeg_channel'
  source: Exclude<Source, 'manual'>
  timestamp_ms: number
  stream_id: string
  stream_name: string
  channel: string
  channel_index: number
  channel_count: number
  sample_rate_hz: number
  unit: string | null
  waveform: { time_s: number[]; values: number[] }
  spectrum: { frequency_hz: number[]; power_density: number[] } | null
}

export type SignalEvent = {
  type: 'status' | 'prediction' | 'movement_start' | 'movement_end' | 'decoder_update' | 'eeg_status' | 'eeg_frame'
  source: Source
  timestamp_ms: number
  connected?: boolean
  message?: string
  movement?: string
  confidence?: number
  state?: string
  latency_ms?: number
  pending_symbols?: string
  written_morse?: string
  text?: string
  decoder_state?: string
  spoken_word?: string
  morse_mode?: 'built-in' | 'external'
  channels?: EegChannel[]
}

export const WS_URL = import.meta.env.VITE_SIGNAL_WS_URL || 'ws://127.0.0.1:8765'

function numericArray(value: unknown): value is number[] {
  return Array.isArray(value) && value.every(Number.isFinite)
}

function isEegChannel(value: unknown): value is EegChannel {
  if (!value || typeof value !== 'object') return false
  const channel = value as EegChannel
  return channel.type === 'eeg_channel'
    && typeof channel.stream_id === 'string'
    && typeof channel.stream_name === 'string'
    && typeof channel.channel === 'string'
    && Number.isInteger(channel.channel_index)
    && Number.isInteger(channel.channel_count)
    && channel.channel_index >= 0
    && channel.channel_index < channel.channel_count
    && Number.isFinite(channel.sample_rate_hz)
    && channel.sample_rate_hz > 0
    && Number.isFinite(channel.timestamp_ms)
    && (channel.unit === null || typeof channel.unit === 'string')
    && numericArray(channel.waveform?.time_s)
    && numericArray(channel.waveform?.values)
    && channel.waveform.time_s.length === channel.waveform.values.length
    && (channel.spectrum === null || (
      numericArray(channel.spectrum?.frequency_hz)
      && numericArray(channel.spectrum?.power_density)
      && channel.spectrum.frequency_hz.length > 0
      && channel.spectrum.frequency_hz.length === channel.spectrum.power_density.length
    ))
}

function isSignalEvent(value: unknown): value is SignalEvent {
  if (!value || typeof value !== 'object') return false
  const event = value as SignalEvent
  return ['status', 'prediction', 'movement_start', 'movement_end', 'decoder_update', 'eeg_status', 'eeg_frame'].includes(event.type)
    && ['live', 'replay', 'manual'].includes(event.source)
    && Number.isFinite(event.timestamp_ms)
    && (event.type !== 'eeg_frame' || (Array.isArray(event.channels)
      && event.channels.length > 0 && event.channels.every((channel) => isEegChannel(channel) && channel.source === event.source)))
}

export function connectSignals(
  onEvent: (event: SignalEvent) => void,
  onError: (message: string) => void,
): WebSocket {
  const socket = new WebSocket(WS_URL)
  socket.onmessage = (message) => {
    let event: unknown
    try { event = JSON.parse(message.data) }
    catch { onError('The bridge sent an unreadable message.'); return }
    if (isSignalEvent(event)) onEvent(event)
    else onError('The bridge sent an unsupported message.')
  }
  return socket
}

export function requestDecoderEdit(socket: WebSocket | null, action: 'backspace' | 'clear' | 'arm' | 'disarm'): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false
  socket.send(JSON.stringify({ type: 'decoder_command', action }))
  return true
}
