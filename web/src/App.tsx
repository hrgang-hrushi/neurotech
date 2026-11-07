import { useEffect, useRef, useState } from 'react'
import { connectSignals, requestDecoderEdit, WS_URL, type SignalEvent, type Source } from './signalAdapter'
import './App.css'

type Mode = 'phrases' | 'morse'
type Connection = 'waiting' | 'connected' | 'disconnected'

const PHRASES = [
  { text: 'Yes', hint: 'Confirm' },
  { text: 'No', hint: 'Decline' },
  { text: 'Please repeat that', hint: 'Clarify' },
  { text: 'I need a break', hint: 'Pause' },
  { text: 'Thank you', hint: 'Appreciate' },
  { text: 'Can we talk?', hint: 'Connect' },
]
const SOURCE_LABEL: Record<Source, string> = {
  live: 'LIVE EEG', replay: 'RECORDED REPLAY', manual: 'MANUAL TEST',
}
const COOLDOWN_MS = 900
const MIN_CONFIDENCE = 0.6

function formatTime(timestamp: number | null): string {
  return timestamp === null ? '—' : new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function App() {
  const [mode, setMode] = useState<Mode>('phrases')
  const [source, setSource] = useState<Source>('manual')
  const [connection, setConnection] = useState<Connection>('connected')
  const [connectionMessage, setConnectionMessage] = useState('Manual test is ready. No EEG stream is being used.')
  const [scanIndex, setScanIndex] = useState(0)
  const [scanMs, setScanMs] = useState(1500)
  const [paused, setPaused] = useState(false)
  const [selectedPhrase, setSelectedPhrase] = useState('')
  const [morseText, setMorseText] = useState('')
  const [pendingSymbols, setPendingSymbols] = useState('')
  const [decoderState, setDecoderState] = useState('Waiting for decoder')
  const [movement, setMovement] = useState('No movement yet')
  const [confidence, setConfidence] = useState<number | null>(null)
  const [latency, setLatency] = useState<number | null>(null)
  const [lastEventAt, setLastEventAt] = useState<number | null>(null)
  const [trail, setTrail] = useState<string[]>(['Choose an input source to begin'])
  const [speechMessage, setSpeechMessage] = useState('')
  const speechSupported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const lastSelectionRef = useRef(0)
  const movementActiveRef = useRef(false)
  const eventHandlerRef = useRef<(event: SignalEvent) => void>(() => {})
  const socketRef = useRef<WebSocket | null>(null)

  function addTrail(entry: string) {
    setTrail((current) => [entry, ...current].slice(0, 4))
  }

  function speak(text: string) {
    if (!text.trim()) return
    if (!speechSupported) {
      setSpeechMessage('Speech is unavailable in this browser. The message remains visible.')
      return
    }
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.rate = 0.9
    utterance.onstart = () => setSpeechMessage('Speaking now')
    utterance.onend = () => { setSpeechMessage('Message spoken'); addTrail(`Speech finished: “${text}”`) }
    utterance.onerror = () => setSpeechMessage('Speech could not play. The message remains visible.')
    window.speechSynthesis.speak(utterance)
    addTrail(`Speech requested: “${text}”`)
  }

  function handleSignalEvent(event: SignalEvent) {
    if (event.source !== source) {
      setConnectionMessage(`Ignoring ${event.source} input while ${SOURCE_LABEL[source]} is selected`)
      return
    }
    setLastEventAt(event.timestamp_ms)
    if (event.type === 'status') {
      setConnection(event.connected ? 'connected' : 'disconnected')
      setConnectionMessage(event.message || (event.connected ? 'EEG stream connected' : 'Waiting for EEG stream'))
      return
    }
    if (event.type === 'prediction') {
      if (event.state) setMovement(event.state === 'rest' ? 'Rest' : event.state)
      if (typeof event.confidence === 'number') setConfidence(event.confidence)
      if (typeof event.latency_ms === 'number' && Number.isFinite(event.latency_ms)) setLatency(event.latency_ms)
      return
    }
    if (event.type === 'movement_end') {
      movementActiveRef.current = false
      return
    }
    if (event.type === 'decoder_update') {
      setPendingSymbols(event.pending_symbols || '')
      setMorseText(event.text || '')
      setDecoderState(event.decoder_state || (event.pending_symbols ? 'Composing a letter' : 'Ready for next symbol'))
      if (typeof event.confidence === 'number') setConfidence(event.confidence)
      addTrail(`Decoder updated: ${event.text || event.pending_symbols || 'empty'}`)
      return
    }
    if (movementActiveRef.current) return
    movementActiveRef.current = true
    setMovement(event.movement || 'Movement detected')
    setConfidence(typeof event.confidence === 'number' ? event.confidence : null)
    addTrail(`Movement detected${event.movement ? `: ${event.movement}` : ''}`)
    if (mode !== 'phrases' || paused) return
    if (typeof event.confidence === 'number' && event.confidence < MIN_CONFIDENCE) {
      addTrail('Low-confidence movement ignored')
      return
    }
    if (Date.now() - lastSelectionRef.current < COOLDOWN_MS) return
    lastSelectionRef.current = Date.now()
    const phrase = PHRASES[scanIndex].text
    setSelectedPhrase(phrase)
    setPaused(true)
    addTrail(`Selected: “${phrase}”`)
  }
  useEffect(() => {
    eventHandlerRef.current = handleSignalEvent
  })

  useEffect(() => {
    if (mode !== 'phrases' || paused) return
    const timer = window.setInterval(() => setScanIndex((index) => (index + 1) % PHRASES.length), scanMs)
    return () => window.clearInterval(timer)
  }, [mode, paused, scanMs])

  useEffect(() => {
    if (source === 'manual') return
    let disposed = false
    const socket = connectSignals(
      (event) => { if (!disposed) eventHandlerRef.current(event) },
      (message) => { if (!disposed) setConnectionMessage(message) },
    )
    socketRef.current = socket
    socket.onopen = () => { if (!disposed) setConnectionMessage('Bridge connected; waiting for EEG stream') }
    socket.onerror = () => {
      if (!disposed) {
        setConnection('disconnected')
        setConnectionMessage(`Could not reach the local bridge at ${WS_URL}`)
      }
    }
    socket.onclose = () => {
      if (!disposed) {
        setConnection('disconnected')
        setConnectionMessage('Bridge disconnected. Start or restart the local bridge.')
      }
    }
    return () => { disposed = true; socketRef.current = null; socket.close() }
  }, [source])

  useEffect(() => {
    if (source !== 'manual') return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || event.repeat || event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      if (target?.closest('button, input, select, textarea, [contenteditable="true"]')) return
      event.preventDefault()
      const timestamp_ms = Date.now()
      eventHandlerRef.current({ type: 'movement_start', source: 'manual', timestamp_ms, movement: 'manual press' })
      eventHandlerRef.current({ type: 'movement_end', source: 'manual', timestamp_ms: timestamp_ms + 1 })
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [source])

  function manualMovement() {
    if (source !== 'manual') return
    const timestamp_ms = Date.now()
    eventHandlerRef.current({ type: 'movement_start', source: 'manual', timestamp_ms, movement: 'manual press' })
    eventHandlerRef.current({ type: 'movement_end', source: 'manual', timestamp_ms: timestamp_ms + 1 })
  }

  function clearMessage() {
    if (mode === 'phrases') { setSelectedPhrase(''); setSpeechMessage(''); return }
    if (source === 'manual') { setMorseText(''); setPendingSymbols(''); setSpeechMessage(''); return }
    setSpeechMessage(requestDecoderEdit(socketRef.current, 'clear')
      ? 'Clear requested. Waiting for the decoder to confirm.'
      : 'Decoder bridge unavailable. The current text remains visible.')
  }

  function backspaceMorse() {
    if (source === 'manual') { setMorseText((text) => text.slice(0, -1)); return }
    setSpeechMessage(requestDecoderEdit(socketRef.current, 'backspace')
      ? 'Backspace requested. Waiting for the decoder to confirm.'
      : 'Decoder bridge unavailable. The current text remains visible.')
  }

  function selectSource(next: Source) {
    if (next === source) return
    movementActiveRef.current = false
    lastSelectionRef.current = 0
    setConfidence(null)
    setLatency(null)
    setLastEventAt(null)
    setMovement('No movement yet')
    setSelectedPhrase('')
    setMorseText('')
    setPendingSymbols('')
    setSpeechMessage('')
    setPaused(false)
    setConnection(next === 'manual' ? 'connected' : 'waiting')
    setConnectionMessage(next === 'manual'
      ? 'Manual test is ready. No EEG stream is being used.'
      : `Connecting to local bridge at ${WS_URL}…`)
    setSource(next)
    setTrail([`Source changed to ${SOURCE_LABEL[next]}`])
  }

  const displayText = mode === 'phrases' ? selectedPhrase : morseText
  const sourceDetail = source === 'manual' ? 'Keyboard or button input' : source === 'replay' ? 'Recorded data through local bridge' : 'ANT headset through local bridge'
  const badgeText = source === 'manual' ? SOURCE_LABEL[source] : `${SOURCE_LABEL[source]} · ${connection === 'connected' ? 'CONNECTED' : 'OFFLINE'}`

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark" aria-hidden="true">◎</span><span><strong>SignalSpeak</strong><small>Movement to communication</small></span></div>
        <div className="topbar-right"><span className="prototype-tag">ANT Neuro · Team 4 prototype</span><span className={`source-badge ${source}`}>{badgeText}</span></div>
      </header>
      <main>
        <div className="intro-row">
          <div><p className="eyebrow">Communication interface</p><h1>Make a movement.<br /><em>Make yourself heard.</em></h1></div>
          <p className="intro-note">A detected movement becomes a phrase or message. Choose a mode, then watch the signal become an action.</p>
        </div>
        <div className="workspace">
          <section className="main-panel" aria-label="Communication workspace">
            <div className="mode-tabs" role="group" aria-label="Communication mode">
              <button aria-pressed={mode === 'phrases'} className={mode === 'phrases' ? 'active' : ''} onClick={() => setMode('phrases')}>Phrase board <span>Reliable path</span></button>
              <button aria-pressed={mode === 'morse'} className={mode === 'morse' ? 'active' : ''} onClick={() => setMode('morse')}>Morse text <span>Experimental</span></button>
            </div>
            <div className="message-box" aria-live="polite">
              <div className="section-caption"><span>YOUR MESSAGE</span><span>{mode === 'phrases' ? 'Phrase selection' : 'Decoder output'}</span></div>
              <div className={`message-text ${displayText ? '' : 'placeholder'}`}>{displayText || (mode === 'phrases' ? 'Choose a phrase with one movement' : 'Decoded text will appear here')}</div>
              <div className="message-actions">
                <button className="primary-action" disabled={!displayText} onClick={() => speak(displayText)}>▶ Speak message</button>
                <button className="secondary-action" disabled={!displayText} onClick={() => mode === 'phrases' ? setSelectedPhrase('') : backspaceMorse()}>{mode === 'phrases' ? 'Undo selection' : 'Backspace'}</button>
                <button className="secondary-action" disabled={!displayText && !pendingSymbols} onClick={clearMessage}>Clear</button>
              </div>
              <p className="speech-status" role="status">{speechMessage || (speechSupported ? 'Speech plays through this device.' : 'Speech synthesis is unavailable in this browser.')}</p>
            </div>
            {mode === 'phrases' ? (
              <div className="phrase-area">
                <div className="area-heading"><div><h2>Phrase board</h2><p>The outline moves automatically. One detected movement selects it.</p></div><div className="scan-state">{paused ? 'SCAN PAUSED' : 'SCANNING'}</div></div>
                <div className="phrase-grid">
                  {PHRASES.map((phrase, index) => <button key={phrase.text} disabled={source !== 'manual'} className={`phrase-tile ${index === scanIndex && !paused ? 'scanning' : ''} ${selectedPhrase === phrase.text ? 'selected' : ''}`} onClick={() => { setSelectedPhrase(phrase.text); setPaused(true); addTrail(`Selected manually: “${phrase.text}”`) }}><strong>{phrase.text}</strong><small>{phrase.hint}</small></button>)}
                </div>
                <div className="scan-controls"><button onClick={() => setPaused((value) => !value)}>{paused ? 'Resume scan' : 'Pause scan'}</button><label htmlFor="scan-speed">Scan speed <strong>{(scanMs / 1000).toFixed(1)}s</strong></label><input id="scan-speed" type="range" min="700" max="3000" step="100" value={scanMs} onChange={(event) => setScanMs(Number(event.target.value))} /></div>
              </div>
            ) : (
              <div className="morse-area">
                <div className="area-heading"><div><h2>Morse text</h2><p>The teammate’s decoder supplies symbols and text.</p></div><div className="experimental-tag">EXPERIMENTAL</div></div>
                <div className="morse-readout"><div><span>Current symbols</span><strong>{pendingSymbols || '—'}</strong></div><div><span>Decoder state</span><strong>{decoderState}</strong></div></div>
                {source === 'manual' && <button className="sample-button" onClick={() => eventHandlerRef.current({ type: 'decoder_update', source: 'manual', timestamp_ms: Date.now(), pending_symbols: '.-', text: 'A', decoder_state: 'Sample decoder event' })}>Load a labeled sample decoder event</button>}
              </div>
            )}
          </section>
          <aside className="signal-panel" aria-label="Input status">
            <div className="signal-header"><span className="signal-icon" aria-hidden="true">◉</span><div><h2>Input signal</h2><p>{sourceDetail}</p></div></div>
            <div className="source-picker" role="group" aria-label="Input source">
              {(['manual', 'live', 'replay'] as Source[]).map((option) => <button key={option} className={source === option ? 'chosen' : ''} aria-pressed={source === option} onClick={() => selectSource(option)}>{option === 'manual' ? 'Manual' : option === 'live' ? 'Live EEG' : 'Replay'}</button>)}
            </div>
            <div className={`connection-status ${connection}`} role="status"><span className="status-dot" aria-hidden="true" /><div><strong>{source === 'manual' ? 'Manual test ready' : connection === 'connected' ? 'EEG stream connected' : connection === 'waiting' ? 'Waiting for stream' : 'Stream disconnected'}</strong><p>{connectionMessage}</p></div></div>
            {source === 'manual' && <div className="manual-control"><button onClick={manualMovement}>Trigger one movement</button><p>Press Space when focus is outside a control.</p></div>}
            <div className="signal-metrics"><div><span>Last movement</span><strong>{movement}</strong></div><div><span>Confidence</span><strong>{confidence === null ? 'Not provided' : `${Math.round(confidence * 100)}%`}</strong></div><div><span>Last event</span><strong>{formatTime(lastEventAt)}</strong></div><div><span>Signal latency</span><strong>{latency === null ? '—' : `${Math.round(latency)} ms`}</strong></div></div>
            <div className="event-trail"><h3>What happened</h3><ol>{trail.map((entry, index) => <li key={`${entry}-${index}`}>{entry}</li>)}</ol></div>
            <p className="disclosure">Research prototype. Manual and replay inputs are visibly labeled; no clinical performance is claimed.</p>
          </aside>
        </div>
      </main>
    </div>
  )
}

export default App
