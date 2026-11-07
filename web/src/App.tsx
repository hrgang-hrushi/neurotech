import { useEffect, useRef, useState } from 'react'
import {
  Activity, AudioLines, ChevronDown, Delete, Keyboard,
  List, Pause, Play, Trash2, Volume2,
} from 'lucide-react'
import MorseKeys from './MorseKeys'
import SignalPanel from './SignalPanel'
import { createMorseDecoder, morseReference, type MorseDecoder, type MorseUpdate } from './morse.mjs'
import { connectSignals, requestDecoderEdit, type EegChannel, type SignalEvent, type Source } from './signalAdapter'
import './App.css'

const phrases = [
  'Yes', 'No', 'Please repeat that', 'I need a break', 'Thank you', 'Can we talk?',
]

const sourceNames: Record<Source, string> = {
  live: 'Live EEG',
  replay: 'Recorded replay',
  manual: 'Manual test',
}

type Mode = 'morse' | 'phrases'
type LogEntry = { text: string; time: number; id: number }

const emptyMorse: MorseUpdate = {
  pending_symbols: '', written_morse: '', text: '', decoder_state: 'Ready for a symbol',
}

function formatTime(time: number) {
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(time)
}

function useBridge(source: Source, onEvent: (event: SignalEvent) => void, onClose: () => void) {
  const socketRef = useRef<WebSocket | null>(null)
  const handlers = useRef({ onEvent, onClose })
  const [bridgeState, setBridgeState] = useState('Connecting to the local bridge')
  const [matched, setMatched] = useState(false)

  useEffect(() => { handlers.current = { onEvent, onClose } })

  useEffect(() => {
    if (source === 'manual') return
    let active = true
    let retry: ReturnType<typeof setTimeout>

    function connect() {
      const socket = connectSignals((event) => {
        if (!active) return
        if (event.source === source) {
          setMatched(true)
          handlers.current.onEvent(event)
        } else setBridgeState(`Bridge is sending ${sourceNames[event.source].toLowerCase()}.`)
      }, (message) => { if (active) setBridgeState(message) })

      socketRef.current = socket
      socket.onopen = () => {
        if (!active) return
        setBridgeState('Local bridge connected')
      }
      socket.onclose = () => {
        if (!active) return
        setMatched(false)
        setBridgeState('Local bridge unavailable. Reconnecting…')
        handlers.current.onClose()
        retry = setTimeout(connect, 1800)
      }
    }

    connect()
    return () => {
      active = false
      clearTimeout(retry)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [source])

  return { socketRef, matched, bridgeState }
}

function Workspace({ source, setSource, mode, setMode }: {
  source: Source
  setSource: (source: Source) => void
  mode: Mode
  setMode: (mode: Mode) => void
}) {
  const [morse, setMorse] = useState(emptyMorse)
  const [manualDecoder, setManualDecoder] = useState<MorseDecoder | null>(null)
  const [channels, setChannels] = useState<EegChannel[]>([])
  const [signalConnected, setSignalConnected] = useState(false)
  const [decoderConnected, setDecoderConnected] = useState(false)
  const [morseMode, setMorseMode] = useState<'built-in' | 'external'>('built-in')
  const [movement, setMovement] = useState('')
  const [confidence, setConfidence] = useState<number | null>(null)
  const [latency, setLatency] = useState<number | null>(null)
  const [phrase, setPhrase] = useState('')
  const [scanIndex, setScanIndex] = useState(0)
  const [scanMs, setScanMs] = useState(1500)
  const [paused, setPaused] = useState(false)
  const [autoSpeak, setAutoSpeak] = useState(false)
  const [speechState, setSpeechState] = useState('')
  const [activity, setActivity] = useState<LogEntry[]>([])
  const logId = useRef(0)
  const lastSelection = useRef(0)
  const gestureActive = useRef(false)
  const onMorseUpdate = useRef<(update: MorseUpdate) => void>(() => {})
  const speechSupported = typeof window.speechSynthesis !== 'undefined'

  function log(text: string) {
    const entry = { text, time: Date.now(), id: ++logId.current }
    setActivity((previous) => [entry, ...previous].slice(0, 5))
  }

  function speak(text: string, interrupt = true) {
    if (!text.trim() || !speechSupported) return
    if (interrupt) window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.rate = 0.95
    utterance.onstart = () => setSpeechState('Speaking…')
    utterance.onend = () => {
      setSpeechState('Spoken')
      log(`Spoken · ${text}`)
    }
    utterance.onerror = ({ error }) => {
      if (error !== 'canceled' && error !== 'interrupted') setSpeechState('Speech is unavailable on this device.')
    }
    window.speechSynthesis.speak(utterance)
  }

  useEffect(() => {
    onMorseUpdate.current = (update) => {
      setMorse(update)
      if (update.spoken_word && mode === 'morse' && autoSpeak) speak(update.spoken_word, false)
    }
  })

  useEffect(() => {
    if (source !== 'manual') return
    const decoder = createMorseDecoder((update) => onMorseUpdate.current(update))
    setManualDecoder(decoder)
    return () => decoder.dispose()
  }, [source])

  useEffect(() => () => {
    if (speechSupported) window.speechSynthesis.cancel()
  }, [speechSupported])

  function selectPhrase(value: string) {
    setPhrase(value)
    setPaused(true)
    setSpeechState('')
    lastSelection.current = Date.now()
    log(`Selected · ${value}`)
  }

  function selectHighlighted() {
    if (!paused && Date.now() - lastSelection.current >= 900) selectPhrase(phrases[scanIndex])
  }

  const { socketRef, matched, bridgeState } = useBridge(source, (event) => {
    switch (event.type) {
      case 'eeg_status':
        setSignalConnected(event.connected === true)
        return
      case 'eeg_frame': {
        const incoming = event.channels ?? []
        if (!incoming.length) return
        setChannels((previous) => {
          const sameStream = previous[0]?.stream_id === incoming[0].stream_id
          const next = new Map((sameStream ? previous : []).map((channel) => [channel.channel_index, channel]))
          for (const channel of incoming) next.set(channel.channel_index, channel)
          return [...next.values()].sort((a, b) => a.channel_index - b.channel_index)
        })
        return
      }
      case 'status':
        setDecoderConnected(event.connected === true)
        if (event.morse_mode) setMorseMode(event.morse_mode)
        return
      case 'prediction':
        setLatency(Number.isFinite(event.latency_ms) ? event.latency_ms! : null)
        return
      case 'movement_end':
        gestureActive.current = false
        return
      case 'movement_start':
        setMovement(event.movement || 'Movement')
        setConfidence(Number.isFinite(event.confidence) ? event.confidence! : null)
        log(`Movement · ${event.movement || 'Detected'}`)
        if (mode === 'phrases' && !gestureActive.current && (event.confidence ?? 1) >= 0.6) {
          selectHighlighted()
        }
        gestureActive.current = true
        return
      case 'decoder_update':
        onMorseUpdate.current({
          pending_symbols: event.pending_symbols ?? '',
          written_morse: event.written_morse ?? '',
          text: event.text ?? '',
          decoder_state: event.decoder_state ?? 'Decoder update received',
          spoken_word: event.spoken_word,
        })
    }
  }, () => {
    setSignalConnected(false)
    setDecoderConnected(false)
    gestureActive.current = false
  })

  useEffect(() => {
    if (!matched || morseMode === 'external') return
    requestDecoderEdit(socketRef.current, mode === 'morse' ? 'arm' : 'disarm')
  }, [matched, mode, morseMode, socketRef])

  useEffect(() => {
    if (mode !== 'phrases' || paused) return
    const timer = window.setInterval(() => setScanIndex((index) => (index + 1) % phrases.length), scanMs)
    return () => window.clearInterval(timer)
  }, [mode, paused, scanMs])

  useEffect(() => {
    if (mode !== 'phrases' || source !== 'manual' || paused) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.code !== 'Space' || event.repeat || event.metaKey || event.ctrlKey || event.altKey) return
      if ((event.target as HTMLElement | null)?.closest('button, input, select, textarea, [contenteditable]')) return
      event.preventDefault()
      if (Date.now() - lastSelection.current >= 900) {
        const value = phrases[scanIndex]
        lastSelection.current = Date.now()
        setPhrase(value)
        setPaused(true)
        setSpeechState('')
        log(`Selected · ${value}`)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [source, mode, paused, scanIndex])

  function edit(action: 'backspace' | 'clear') {
    setSpeechState('')
    if (mode === 'phrases') {
      setPhrase('')
      if (action === 'backspace') setPaused(false)
      return
    }
    if (source === 'manual') {
      if (action === 'backspace') manualDecoder?.backspace()
      else manualDecoder?.clear()
    } else if (!matched || !requestDecoderEdit(socketRef.current, action)) {
      setSpeechState('Connect the local bridge to edit the transcript.')
    }
  }

  function selectMode(next: Mode) {
    if (mode === next) return
    if (next === 'phrases') manualDecoder?.pause()
    setMode(next)
    setSpeechState('')
    if (speechSupported) window.speechSynthesis.cancel()
  }

  const output = mode === 'morse' ? morse.text : phrase
  const symbols = morse.written_morse || morse.pending_symbols
  const hasEditContent = Boolean(output || (mode === 'morse' && symbols))
  const sourceStatus = source === 'manual'
    ? 'Keyboard ready'
    : signalConnected ? (source === 'live' ? 'EEG receiving' : 'Replay receiving') : 'No EEG samples'
  const morseHint = morseMode === 'external'
    ? 'Translating updates from the external Morse decoder.'
    : 'Left movement sends a dot. Right movement sends a dash.'

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <h1 className="brand"><AudioLines size={20} aria-hidden="true" />SignalSpeak</h1>
          <span className="brand-context">ANT Neuro <span aria-hidden="true">/</span> Team 04</span>
          <div className="source-control">
            <span className={signalConnected ? 'connection receiving' : 'connection'} role="status">
              <span className="status-dot" />{sourceStatus}
            </span>
            <label className="source-select">
              <span className="sr-only">Input source</span>
              <select value={source} onChange={(event) => setSource(event.target.value as Source)}>
                <option value="live">Live EEG</option>
                <option value="replay">Recorded replay</option>
                <option value="manual">Manual test</option>
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </label>
          </div>
        </div>
      </header>

      <main className="workspace">
        <div className="work-grid">
          <section className="panel composer" aria-labelledby="composer-heading">
            <div className="panel-heading">
              <h2 id="composer-heading">Message</h2>
            </div>

            <div className="segmented composer-tabs" role="group" aria-label="Message mode">
              <button type="button" aria-pressed={mode === 'morse'} onClick={() => selectMode('morse')}>
                <Keyboard size={16} aria-hidden="true" /> Morse
              </button>
              <button type="button" aria-pressed={mode === 'phrases'} onClick={() => selectMode('phrases')}>
                <List size={16} aria-hidden="true" /> Phrase board
              </button>
            </div>

            <div className="spotlight">
              {mode === 'morse' && (
                <div className="written">
                  <div className="spotlight-label">Morse input</div>
                  <p className={symbols ? 'morse-text' : 'morse-text placeholder'}>{symbols || 'Waiting for dots and dashes'}</p>
                </div>
              )}
              <div className="translation">
                <div className="spotlight-label">{mode === 'morse' ? 'Translation' : 'Selected phrase'}</div>
                <p className={output ? 'output' : 'output placeholder'} aria-live="polite">
                  {output || (mode === 'morse' ? 'Your message appears here.' : 'Select a phrase to speak.')}
                </p>
              </div>
              <div className="spotlight-actions">
                <button type="button" className="primary-button" disabled={!output || !speechSupported} onClick={() => speak(output)}>
                  <Volume2 size={17} aria-hidden="true" /> Speak message
                </button>
                <button type="button" className="icon-button" disabled={!hasEditContent} onClick={() => edit('backspace')} aria-label={mode === 'morse' ? 'Backspace' : 'Undo phrase selection'} title={mode === 'morse' ? 'Backspace' : 'Undo selection'}>
                  <Delete size={18} aria-hidden="true" />
                </button>
                <button type="button" className="icon-button" disabled={!hasEditContent} onClick={() => edit('clear')} aria-label="Clear message" title="Clear message">
                  <Trash2 size={17} aria-hidden="true" />
                </button>
              </div>
            </div>

            {mode === 'morse' ? (
              <div className="mode-controls">
                <div className="mode-meta">
                  <span role="status">{speechState || (!speechSupported ? 'Speech unavailable in this browser' : morse.decoder_state)}</span>
                  <label className="check">
                    <input type="checkbox" checked={autoSpeak} onChange={(event) => {
                      setAutoSpeak(event.target.checked)
                      if (!event.target.checked && speechSupported) window.speechSynthesis.cancel()
                    }} disabled={!speechSupported} />
                    Auto-speak words
                  </label>
                </div>
                {source === 'manual' && manualDecoder
                  ? <MorseKeys decoder={manualDecoder} />
                  : <p className="mode-hint">{morseHint}</p>}
                <details className="morse-reference">
                  <summary>Morse reference</summary>
                  <dl>
                    {morseReference.map(([sequence, letter]) => (
                      <div key={letter}>
                        <dt>{letter}</dt>
                        <dd aria-label={Array.from(sequence, (symbol) => symbol === '.' ? 'dot' : 'dash').join(' ')}>
                          {sequence.replaceAll('.', '·').replaceAll('-', '−')}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </div>
            ) : (
              <div className="mode-controls">
                <div className="phrase-grid">
                  {phrases.map((value, index) => (
                    <button type="button" key={value} aria-pressed={phrase === value}
                      className={scanIndex === index && !paused ? 'is-scanning' : ''}
                      aria-disabled={source !== 'manual'}
                      onClick={() => { if (source === 'manual') selectPhrase(value) }}>
                      <span className="phrase-index">{String(index + 1).padStart(2, '0')}</span>{value}
                    </button>
                  ))}
                </div>
                <div className="phrase-controls">
                  <button type="button" className="quiet-button" onClick={() => setPaused(!paused)}>
                    {paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}
                    {paused ? 'Resume scan' : 'Pause scan'}
                  </button>
                  {source === 'manual' && <button type="button" className="quiet-button" onClick={selectHighlighted} disabled={paused}>Select highlight</button>}
                  <label className="scan-speed">Scan <input aria-label="Seconds per phrase" type="range" min="700" max="3000" step="100" value={scanMs} onChange={(event) => setScanMs(Number(event.target.value))} /><span>{(scanMs / 1000).toFixed(1)} s</span></label>
                </div>
                {speechState && <p className="mode-hint" role="status">{speechState}</p>}
              </div>
            )}
          </section>

          <SignalPanel channels={channels} connected={signalConnected} source={source} />
        </div>

        <section className="panel session" aria-labelledby="session-heading">
          <div className="session-status">
            <div className="panel-heading">
              <div><h2 id="session-heading">Session</h2><p>{source === 'manual' ? 'Manual input is active' : bridgeState}</p></div>
            </div>
            <dl className="metrics">
              <div><dt>Movement decoder</dt><dd>{source === 'manual' ? 'Manual' : decoderConnected ? 'Receiving' : 'Waiting'}</dd></div>
              <div><dt>Last movement</dt><dd>{movement || '—'}</dd></div>
              <div><dt>Confidence</dt><dd>{confidence === null ? '—' : `${Math.round(confidence * 100)}%`}</dd></div>
              <div><dt>Last decoder latency</dt><dd>{latency === null ? '—' : `${Math.round(latency)} ms`}</dd></div>
            </dl>
          </div>
          <div className="session-activity">
            <div className="activity-heading"><Activity size={16} aria-hidden="true" /><h3>Recent activity</h3></div>
            {activity.length
              ? <ol>{activity.map(({ text, time, id }) => <li key={id}><time dateTime={new Date(time).toISOString()}>{formatTime(time)}</time><span>{text}</span></li>)}</ol>
              : <p>Movement, phrase selections, and speech will appear here.</p>}
          </div>
        </section>

        <footer>ANT Neuro · Research prototype</footer>
      </main>
    </div>
  )
}

export default function App() {
  const [source, setSource] = useState<Source>('live')
  const [mode, setMode] = useState<Mode>('morse')
  return <Workspace key={source} source={source} setSource={setSource} mode={mode} setMode={setMode} />
}
