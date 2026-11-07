import { memo, useId, useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'
import { line } from 'd3-shape'
import { Activity, ChevronLeft, ChevronRight, Pause, Play } from 'lucide-react'
import { fastShapePath } from './charts/bklit-fast-path'
import type { EegChannel, Source } from './signalAdapter'
import './SignalPanel.css'

type View = 'waveform' | 'spectrum'
type Point = { x: number; y: number }
type Snapshot = { source: Source; streamId: string; channels: EegChannel[] }

const PLOT_WIDTH = 1000
const PLOT_HEIGHT = 270
const CHANNELS_PER_PAGE = 4
const tickFractions = [0, 0.25, 0.5, 0.75, 1]

const formatter = new Intl.NumberFormat('en', { maximumSignificantDigits: 4 })
const scientific = new Intl.NumberFormat('en', { notation: 'scientific', maximumSignificantDigits: 3 })

function formatNumber(value: number) {
  if (value !== 0 && (Math.abs(value) < 0.01 || Math.abs(value) >= 10000)) {
    return scientific.format(value)
  }
  return formatter.format(value)
}

function pointsFor(channel: EegChannel, view: View): Point[] {
  const x = view === 'waveform' ? channel.waveform.time_s : channel.spectrum?.frequency_hz
  const y = view === 'waveform' ? channel.waveform.values : channel.spectrum?.power_density
  if (!x || !y) return []
  return x.flatMap((value, index) => Number.isFinite(value) && Number.isFinite(y[index])
    ? [{ x: value, y: y[index] }]
    : [])
}

function plotBounds(points: Point[], view: View) {
  const xMin = points[0].x
  const xMax = points.at(-1)!.x
  const ys = points.map((point) => point.y)
  const min = Math.min(...ys)
  const max = Math.max(...ys)
  if (view === 'spectrum') return { xMin, xMax, yMin: 0, yMax: max > 0 ? max * 1.04 : 1 }
  const padding = max > min ? (max - min) * 0.07 : Math.abs(max) * 0.07 || 1
  return { xMin, xMax, yMin: min - padding, yMax: max + padding }
}

function axisUnit(channel: EegChannel, view: View) {
  const amplitude = channel.unit || 'native units'
  return view === 'waveform' ? amplitude : `${channel.unit || 'native unit'}²/Hz`
}

function Plot({ channel, points, view }: { channel: EegChannel; points: Point[]; view: View }) {
  const instructionsId = useId()
  const [cursor, setCursor] = useState<number | null>(null)
  const { xMin, xMax, yMin, yMax } = plotBounds(points, view)
  const xSpan = xMax - xMin
  const ySpan = yMax - yMin
  const xAt = (point: Point) => xSpan ? (point.x - xMin) / xSpan : 0.5
  const yAt = (point: Point) => (yMax - point.y) / ySpan
  const xUnit = view === 'waveform' ? 's' : 'Hz'
  const yUnit = axisUnit(channel, view)
  const active = cursor === null ? null : points[Math.min(cursor, points.length - 1)]
  const path = fastShapePath(line<Point>()
    .x((point) => xAt(point) * PLOT_WIDTH)
    .y((point) => yAt(point) * PLOT_HEIGHT), points)

  function inspectPointer(event: PointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const targetX = xMin + xSpan * ((event.clientX - bounds.left) / bounds.width)
    let nearest = 0
    for (let index = 1; index < points.length; index++) {
      if (Math.abs(points[index].x - targetX) < Math.abs(points[nearest].x - targetX)) nearest = index
    }
    setCursor(nearest)
  }

  function inspectKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    const current = cursor ?? points.length - 1
    switch (event.key) {
      case 'ArrowLeft': setCursor(Math.max(0, current - 1)); break
      case 'ArrowRight': setCursor(Math.min(points.length - 1, current + 1)); break
      case 'Home': setCursor(0); break
      case 'End': setCursor(points.length - 1); break
      case 'Escape': setCursor(null); break
      default: return
    }
    event.preventDefault()
  }

  return (
    <figure className="scope-figure">
      <figcaption className="scope-plot-meta">
        <span>{view === 'waveform' ? 'Amplitude' : 'Power density'} <span className="scope-unit">({yUnit})</span></span>
        <output>{active ? `${formatNumber(active.x)} ${xUnit} · ${formatNumber(active.y)} ${yUnit}` : 'Auto scale'}</output>
      </figcaption>
      <p className="scope-sr-only" id={instructionsId}>Use the left and right arrow keys to inspect measured points. Freeze the view to hold the data steady.</p>
      <div className="scope-axes">
        <div className="scope-y-ticks" aria-hidden="true">
          {tickFractions.map((fraction) => <span key={fraction}>{formatNumber(yMax - ySpan * fraction)}</span>)}
        </div>
        <div
          className="scope-chart"
          tabIndex={0}
          role="group"
          aria-label={`${channel.channel} ${view} chart`}
          aria-describedby={instructionsId}
          onPointerMove={inspectPointer}
          onPointerDown={inspectPointer}
          onPointerLeave={() => setCursor(null)}
          onBlur={() => setCursor(null)}
          onKeyDown={inspectKeyboard}
        >
          <svg viewBox={`0 0 ${PLOT_WIDTH} ${PLOT_HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
            {tickFractions.map((fraction) => (
              <g key={fraction} className="scope-gridline">
                <line x1={0} y1={fraction * PLOT_HEIGHT} x2={PLOT_WIDTH} y2={fraction * PLOT_HEIGHT} vectorEffect="non-scaling-stroke" />
                <line x1={fraction * PLOT_WIDTH} y1={0} x2={fraction * PLOT_WIDTH} y2={PLOT_HEIGHT} vectorEffect="non-scaling-stroke" />
              </g>
            ))}
            <path className="scope-line" d={path} vectorEffect="non-scaling-stroke" />
          </svg>
          {active && <span className="scope-crosshair" style={{ left: `${xAt(active) * 100}%` }}><span style={{ top: `${yAt(active) * 100}%` }} /></span>}
        </div>
        <div className="scope-x-ticks" aria-hidden="true">
          {tickFractions.map((fraction) => <span key={fraction} style={{ left: `${fraction * 100}%` }}>{formatNumber(xMin + xSpan * fraction)} {xUnit}</span>)}
        </div>
      </div>
    </figure>
  )
}

const MiniTrace = memo(function MiniTrace({ channel, view }: { channel: EegChannel; view: View }) {
  const points = pointsFor(channel, view)
  if (points.length < 2) return <span className="scope-mini-unavailable">—</span>
  const { xMin, xMax, yMin, yMax } = plotBounds(points, view)
  const path = fastShapePath(line<Point>()
    .x((point) => xMax > xMin ? (point.x - xMin) / (xMax - xMin) * 100 : 50)
    .y((point) => (yMax - point.y) / (yMax - yMin) * 22), points)
  return <svg className="scope-mini-trace" viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden="true"><path d={path} vectorEffect="non-scaling-stroke" /></svg>
})

export default function SignalPanel({ channels, connected, source }: {
  channels: EegChannel[]
  connected: boolean
  source: Source
}) {
  const [view, setView] = useState<View>('waveform')
  const [channelIndex, setChannelIndex] = useState<number | null>(null)
  const [page, setPage] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const previewsId = useId()
  const available = channels.filter((channel) => channel.source === source)
  const streamId = available[0]?.stream_id
  const frozen = snapshot?.source === source && snapshot.streamId === streamId
  const ordered = [...(frozen ? snapshot.channels : available)].sort((a, b) => a.channel_index - b.channel_index)
  const selected = ordered.find((channel) => channel.channel_index === channelIndex) ?? ordered[0]
  const points = selected ? pointsFor(selected, view) : []
  const channelCount = selected?.channel_count ?? 0
  const totalPages = Math.ceil(ordered.length / CHANNELS_PER_PAGE)
  const displayedPage = Math.min(page, Math.max(totalPages - 1, 0))
  const previews = showAll ? ordered : ordered.slice(displayedPage * CHANNELS_PER_PAGE, (displayedPage + 1) * CHANNELS_PER_PAGE)
  const hasSamples = available.some((channel) => channel.waveform.values.length > 1)
  const receiving = connected && hasSamples
  const feedState = receiving ? 'Samples arriving'
    : !connected && (hasSamples || frozen) ? 'Stream interrupted'
    : selected ? 'Samples unavailable' : source === 'manual' ? 'Manual source' : 'Awaiting samples'
  const density = selected?.spectrum?.power_density ?? []
  const spectrumPeak = density.reduce((maxIndex, value, index) => value > density[maxIndex] ? index : maxIndex, 0)
  const peakFrequency = density[spectrumPeak] > 0 ? selected?.spectrum?.frequency_hz[spectrumPeak] ?? null : null
  const plotReady = Boolean(selected && points.length > 1)

  function selectChannel(index: number) {
    const position = ordered.findIndex((channel) => channel.channel_index === index)
    setChannelIndex(index)
    setPage(Math.floor(Math.max(0, position) / CHANNELS_PER_PAGE))
  }

  function toggleFreeze() {
    if (frozen) setSnapshot(null)
    else if (streamId) setSnapshot({ source, streamId, channels: available })
  }

  return (
    <section className="panel eeg-scope" aria-labelledby="eeg-scope-title">
      <header className="scope-heading">
        <div className="panel-heading"><h2 id="eeg-scope-title">EEG monitor</h2></div>
        <p className="scope-feed" data-receiving={receiving}><span aria-hidden="true" />{feedState}</p>
      </header>
      <div className="scope-controls">
        <div className="segmented scope-segment" role="group" aria-label="Signal view">
          <button type="button" aria-pressed={view === 'waveform'} onClick={() => setView('waveform')}>Waveform</button>
          <button type="button" aria-pressed={view === 'spectrum'} onClick={() => setView('spectrum')}>Spectrum</button>
        </div>
        <select aria-label="EEG channel" disabled={!selected} value={selected?.channel_index ?? ''} onChange={(event) => selectChannel(Number(event.target.value))}>
          {!selected && <option value="">No channels</option>}
          {ordered.map((channel) => <option key={channel.channel_index} value={channel.channel_index}>{channel.channel}</option>)}
        </select>
        <button className="scope-freeze" type="button" disabled={!hasSamples && !frozen} onClick={toggleFreeze} aria-label={frozen ? 'Resume updating the chart' : 'Freeze the chart for inspection'}>
          {frozen ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}
          {frozen ? 'Resume' : 'Freeze'}
        </button>
      </div>
      <div className="scope-plot-card">
        {plotReady && selected ? (
          <Plot key={`${selected.stream_id}:${selected.channel_index}:${view}`} channel={selected} points={points} view={view} />
        ) : (
          <div className="scope-placeholder">
            <Activity size={28} strokeWidth={1.4} aria-hidden="true" />
            <strong>{selected ? (view === 'spectrum' && selected.waveform.values.length > 1 ? 'Spectrum warming up' : 'Channel samples unavailable') : 'Waiting for EEG samples'}</strong>
            <p>{selected ? (view === 'spectrum' && selected.waveform.values.length > 1
              ? 'The spectrum appears after the monitor collects a full analysis window.'
              : `No usable samples are available for ${selected.channel} in this window.`)
              : source === 'manual' ? 'Choose Live EEG or Replay to see measured waveforms and frequencies.'
              : 'Start the EEG monitor and check that its LSL stream is available.'}</p>
          </div>
        )}
      </div>
      <dl className="scope-readouts">
        <div><dt>Channels</dt><dd>{selected ? `${ordered.length} / ${channelCount}` : '—'}</dd></div>
        <div><dt>Sample rate</dt><dd>{selected ? `${formatNumber(selected.sample_rate_hz)} Hz` : '—'}</dd></div>
        <div><dt>Spectral peak</dt><dd>{peakFrequency === null ? '—' : `${formatNumber(peakFrequency)} Hz`}</dd></div>
      </dl>
      {selected && (
        <div className="scope-channel-index">
          <div className="scope-channel-heading">
            <p title={selected.stream_name}>{frozen ? 'Frozen view' : connected ? selected.stream_name : 'Last received data'}</p>
            {totalPages > 1 && (
              <div className="scope-gallery-actions">
                {!showAll && <div className="scope-pagination" role="group" aria-label="Channel pages">
                  <button type="button" disabled={displayedPage === 0} onClick={() => setPage(displayedPage - 1)} aria-label="Previous channels"><ChevronLeft size={14} /></button>
                  <span>{displayedPage + 1} / {totalPages}</span>
                  <button type="button" disabled={displayedPage + 1 >= totalPages} onClick={() => setPage(displayedPage + 1)} aria-label="Next channels"><ChevronRight size={14} /></button>
                </div>}
                <button className="scope-gallery-toggle" type="button" aria-expanded={showAll} aria-controls={previewsId} onClick={() => setShowAll((value) => !value)}>
                  {showAll ? 'Collapse' : 'Show all'}
                </button>
              </div>
            )}
          </div>
          <div className="scope-channels" id={previewsId} aria-label="Channel previews" role="group" data-expanded={showAll}>
            {previews.map((channel) => (
              <button key={channel.channel_index} type="button" aria-pressed={selected.channel_index === channel.channel_index} onClick={() => selectChannel(channel.channel_index)} title={channel.channel}>
                <span>{channel.channel}</span><MiniTrace channel={channel} view={view} />
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
