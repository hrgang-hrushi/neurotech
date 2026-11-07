export type Source = 'live' | 'replay' | 'manual'

export type SignalEvent = {
  type: 'status' | 'prediction' | 'movement_start' | 'movement_end' | 'decoder_update'
  source: Source
  timestamp_ms: number
  connected?: boolean
  message?: string
  movement?: string
  confidence?: number
  state?: string
  latency_ms?: number
  pending_symbols?: string
  text?: string
  decoder_state?: string
}

export const WS_URL = import.meta.env.VITE_SIGNAL_WS_URL || 'ws://127.0.0.1:8765'

function isSignalEvent(value: unknown): value is SignalEvent {
  if (!value || typeof value !== 'object') return false
  const event = value as Record<string, unknown>
  return typeof event.type === 'string'
    && ['status', 'prediction', 'movement_start', 'movement_end', 'decoder_update'].includes(event.type)
    && ['live', 'replay', 'manual'].includes(String(event.source))
    && typeof event.timestamp_ms === 'number'
}

export function connectSignals(
  onEvent: (event: SignalEvent) => void,
  onError: (message: string) => void,
): WebSocket {
  const socket = new WebSocket(WS_URL)
  socket.onmessage = (message) => {
    try {
      const event: unknown = JSON.parse(message.data)
      if (isSignalEvent(event)) onEvent(event)
      else onError('Received an invalid event from the bridge')
    } catch {
      onError('Received an unreadable event from the bridge')
    }
  }
  return socket
}

export function requestDecoderEdit(socket: WebSocket | null, action: 'backspace' | 'clear'): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false
  socket.send(JSON.stringify({ type: 'decoder_command', action }))
  return true
}
