/**
 * Client for the eeg_morse recording decoder (`uv run eeg-morse serve`).
 *
 * Everything that comes back from the server is validated here before the UI
 * sees it, so a malformed or partial response becomes an error message instead
 * of a crash.
 */

const LOCAL_DECODER_URL = 'http://127.0.0.1:8770';
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

const isLocalPage = () => typeof window === 'undefined' || LOCAL_HOSTS.has(window.location.hostname);

/**
 * Where the decoder API lives: NEXT_PUBLIC_DECODER_URL if set (empty = same origin),
 * else `eeg-morse serve` on this laptop when the page is local, else the page's own
 * domain (a hosted deployment routes /api/* to the decoder).
 */
export function decoderBase(): string {
  const configured = process.env.NEXT_PUBLIC_DECODER_URL;
  if (configured !== undefined) return configured;
  return isLocalPage() ? LOCAL_DECODER_URL : '';
}

export const ACCEPTED_EXTENSIONS = [
  '.cnt', '.evt', '.seg', '.edf', '.bdf', '.fif', '.xdf', '.npz', '.csv', '.txt',
] as const;
/** Files that only make sense next to a .cnt with the same name. */
export const SIDECAR_EXTENSIONS = ['.evt', '.seg'] as const;
/** Session notes (what was said during the recording), written by the team. Never decoded. */
export const NOTES_EXTENSION = '.txt';
export const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;
/** Hosted decoders (Vercel) accept at most ~4.5 MB per request. */
export const HOSTED_MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

export function maxUploadBytes(): number {
  const configured = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB);
  if (configured > 0) return configured * 1024 * 1024;
  return decoderBase() === LOCAL_DECODER_URL ? MAX_UPLOAD_BYTES : HOSTED_MAX_UPLOAD_BYTES;
}
const HEALTH_TIMEOUT_MS = 4000;
const DECODE_TIMEOUT_MS = 10 * 60 * 1000;

export type SentenceType = 'question' | 'statement' | 'exclamation';
export type LetterStatus = 'ok' | 'split' | 'nearest' | 'unknown';
export type ArtifactKind = 'blink' | 'eye_movement' | 'electrode_pop';

export interface Correction { from: string; to: string; cost: number }
export interface DecodedLetter { code: string; char: string; status: LetterStatus; t_start: number; t_end: number }
export interface MorseElement { t_on: number; t_off: number; symbol: '.' | '-'; boundary: 'start' | 'intra' | 'letter' | 'word' }
/** Artifacts are removed from the signal before detection (eye EMG regressed out, pops patched). */
export interface Artifact { t_on: number; t_off: number; kind: ArtifactKind; channel: string | null; action: 'removed' }

export interface DecodeResult {
  file: string;
  duration_s: number;
  sfreq: number;
  n_channels: number;
  channels_used: string[];
  bad_channels: string[];
  model: string;
  /** False when the signal is too weak to trust: no sentence, no word correction. */
  reliable: boolean;
  /** What the team noted was said during the recording (from a .txt next to it). Not decoded. */
  session_notes: string[];
  text: string;
  raw_text: string;
  corrected_text: string;
  morse: string;
  sentence_types: SentenceType[];
  corrections: Correction[];
  letters: DecodedLetter[];
  elements: MorseElement[];
  artifacts: Artifact[];
  /** lo/hi are null when the server omitted them (no threshold lines are drawn). */
  trace: { t: number[]; activation: number[]; lo: number | null; hi: number | null };
  quality: { separability: number; n_key_downs: number; n_artifacts: number; artifact_aware: boolean; warnings: string[] };
  timing: { unit_s: number; dash_threshold_s: number; letter_gap_s: number; word_gap_s: number };
  score: { expected: string; cer: number; exact: boolean } | null;
}

export interface Health { status: string; models: string[] }

export class DecoderError extends Error {}
/** Thrown when the caller aborted the request (e.g. the view unmounted). */
export class DecodeAbortedError extends DecoderError {}

// ---------- validation helpers ----------

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

function str(o: Obj, key: string, fallback?: string): string {
  const v = o[key];
  if (typeof v === 'string') return v;
  if (fallback !== undefined && (v === undefined || v === null)) return fallback;
  throw new DecoderError(`Decoder response is missing text field "${key}".`);
}

function num(o: Obj, key: string, fallback?: number): number {
  const v = o[key];
  if (isNum(v)) return v;
  if (fallback !== undefined && (v === undefined || v === null)) return fallback;
  throw new DecoderError(`Decoder response is missing number field "${key}".`);
}

function obj(o: Obj, key: string): Obj {
  const v = o[key];
  if (isObj(v)) return v;
  throw new DecoderError(`Decoder response is missing section "${key}".`);
}

/** Array of items; malformed items are dropped rather than failing the whole result. */
function list<T>(v: unknown, parse: (item: unknown) => T | null): T[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((item) => {
    try {
      const parsed = parse(item);
      return parsed === null ? [] : [parsed];
    } catch {
      return [];
    }
  });
}

const strings = (v: unknown): string[] => list(v, (s) => (typeof s === 'string' ? s : null));

function oneOf<T extends string>(v: unknown, allowed: readonly T[]): T | null {
  return typeof v === 'string' && (allowed as readonly string[]).includes(v) ? (v as T) : null;
}

const SENTENCE_TYPES = ['question', 'statement', 'exclamation'] as const;
const LETTER_STATUSES = ['ok', 'split', 'nearest', 'unknown'] as const;
const ARTIFACT_KINDS = ['blink', 'eye_movement', 'electrode_pop'] as const;
const BOUNDARIES = ['start', 'intra', 'letter', 'word'] as const;

function parseLetter(v: unknown): DecodedLetter | null {
  if (!isObj(v)) return null;
  const status = oneOf(v.status, LETTER_STATUSES) ?? 'unknown';
  return { code: str(v, 'code'), char: str(v, 'char'), status, t_start: num(v, 't_start'), t_end: num(v, 't_end') };
}

function parseElement(v: unknown): MorseElement | null {
  if (!isObj(v)) return null;
  const symbol = v.symbol === '.' || v.symbol === '-' ? v.symbol : null;
  const boundary = oneOf(v.boundary, BOUNDARIES);
  if (!symbol || !boundary) return null;
  return { t_on: num(v, 't_on'), t_off: num(v, 't_off'), symbol, boundary };
}

function parseArtifact(v: unknown): Artifact | null {
  if (!isObj(v)) return null;
  const kind = oneOf(v.kind, ARTIFACT_KINDS);
  const action = oneOf(v.action, ['removed'] as const);
  if (!kind || !action) return null;
  const channel = typeof v.channel === 'string' ? v.channel : null;
  return { t_on: num(v, 't_on'), t_off: num(v, 't_off'), kind, channel, action };
}

function parseCorrection(v: unknown): Correction | null {
  if (!isObj(v)) return null;
  return { from: str(v, 'from'), to: str(v, 'to'), cost: num(v, 'cost', 0) };
}

const EMPTY_TRACE: DecodeResult['trace'] = { t: [], activation: [], lo: null, hi: null };

/** Pair t[i] with activation[i] and drop pairs where either is non-finite, so samples never shift. */
export function parseTrace(o: Obj): DecodeResult['trace'] {
  const ts = Array.isArray(o.t) ? o.t : [];
  const vs = Array.isArray(o.activation) ? o.activation : [];
  const t: number[] = [];
  const activation: number[] = [];
  for (let i = 0; i < Math.min(ts.length, vs.length); i += 1) {
    const ti: unknown = ts[i];
    const vi: unknown = vs[i];
    if (isNum(ti) && isNum(vi)) {
      t.push(ti);
      activation.push(vi);
    }
  }
  return { t, activation, lo: isNum(o.lo) ? o.lo : null, hi: isNum(o.hi) ? o.hi : null };
}

/** Optional section: anything malformed becomes null instead of failing the whole result. */
export function parseScore(v: unknown): DecodeResult['score'] {
  if (!isObj(v) || typeof v.expected !== 'string' || !isNum(v.cer)) return null;
  return { expected: v.expected, cer: v.cer, exact: v.exact === true };
}

/** Validate an untrusted decode payload. Throws DecoderError on missing essentials. */
export function parseDecodeResult(data: unknown): DecodeResult {
  if (!isObj(data)) throw new DecoderError('Decoder returned no result.');
  const quality = obj(data, 'quality');
  const timing = obj(data, 'timing');
  return {
    file: str(data, 'file', 'recording'),
    duration_s: num(data, 'duration_s', 0),
    sfreq: num(data, 'sfreq', 0),
    n_channels: num(data, 'n_channels', 0),
    channels_used: strings(data.channels_used),
    bad_channels: strings(data.bad_channels),
    model: str(data, 'model', 'unknown'),
    reliable: data.reliable !== false,
    session_notes: strings(data.session_notes),
    text: str(data, 'text'),
    raw_text: str(data, 'raw_text', ''),
    corrected_text: str(data, 'corrected_text', ''),
    morse: str(data, 'morse', ''),
    sentence_types: list(data.sentence_types, (s) => oneOf(s, SENTENCE_TYPES)),
    corrections: list(data.corrections, parseCorrection),
    letters: list(data.letters, parseLetter),
    elements: list(data.elements, parseElement),
    artifacts: list(data.artifacts, parseArtifact),
    trace: isObj(data.trace) ? parseTrace(data.trace) : EMPTY_TRACE,
    quality: {
      separability: num(quality, 'separability', 0),
      n_key_downs: num(quality, 'n_key_downs', 0),
      n_artifacts: num(quality, 'n_artifacts', 0),
      artifact_aware: quality.artifact_aware === true,
      warnings: strings(quality.warnings),
    },
    timing: {
      unit_s: num(timing, 'unit_s', 0),
      dash_threshold_s: num(timing, 'dash_threshold_s', 0),
      letter_gap_s: num(timing, 'letter_gap_s', 0),
      word_gap_s: num(timing, 'word_gap_s', 0),
    },
    score: parseScore(data.score),
  };
}

/** Unwrap the {success, data, error} envelope. */
export function unwrapEnvelope(body: unknown, httpStatus: number): unknown {
  if (!isObj(body)) throw new DecoderError(`Decoder sent an unreadable reply (HTTP ${httpStatus}).`);
  if (body.success !== true) {
    const msg = typeof body.error === 'string' && body.error ? body.error : `Decoding failed (HTTP ${httpStatus}).`;
    throw new DecoderError(msg);
  }
  return body.data;
}

// ---------- file grouping ----------

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot <= 0 ? '' : name.slice(dot).toLowerCase();
}

export function stemOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot <= 0 ? name : name.slice(0, dot);
}

export interface FileGroup { stem: string; main: File; files: File[]; totalBytes: number }
export interface GroupingResult { groups: FileGroup[]; errors: string[] }

const isSidecar = (ext: string) => (SIDECAR_EXTENSIONS as readonly string[]).includes(ext);

/** Browsers hand a dropped folder over as an empty File with no MIME type. */
export function isFolderPlaceholder(file: Pick<File, 'size' | 'type'>): boolean {
  return file.size === 0 && file.type === '';
}

/** The model to show and send: the chosen one if the server offers it, else the server's first. */
export function effectiveModel(chosen: string, options: readonly string[]): string {
  return options.includes(chosen) ? chosen : (options[0] ?? chosen);
}

/**
 * Group dropped files into one upload per recording: each recording file plus any
 * .evt/.seg sidecar with the same stem. Returns friendly errors for the rest.
 */
export function groupFiles(files: readonly File[]): GroupingResult {
  const errors: string[] = [];
  const mains = new Map<string, File>();
  const sidecars = new Map<string, File[]>();
  const notes = new Map<string, File>();

  for (const file of files) {
    if (isFolderPlaceholder(file)) {
      errors.push(`${file.name}: folders are not supported — drop the files inside.`);
      continue;
    }
    const ext = extensionOf(file.name);
    if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) {
      errors.push(`${file.name}: unsupported file type. Use ${ACCEPTED_EXTENSIONS.join(' ')}.`);
      continue;
    }
    const key = stemOf(file.name).toLowerCase();
    if (ext === NOTES_EXTENSION) {
      notes.set(key, file);
    } else if (isSidecar(ext)) {
      sidecars.set(key, [...(sidecars.get(key) ?? []), file]);
    } else if (mains.has(key)) {
      errors.push(
        `${file.name}: skipped — ${mains.get(key)?.name} has the same name. Upload one recording per name at a time.`,
      );
    } else {
      mains.set(key, file);
    }
  }

  const groups: FileGroup[] = [];
  for (const [key, main] of mains) {
    const extras = sidecars.get(key) ?? [];
    if (extras.length && extensionOf(main.name) !== '.cnt') {
      errors.push(`${extras.map((f) => f.name).join(', ')}: .evt/.seg files belong to an eego .cnt, not ${main.name}.`);
    }
    const note = notes.get(key);
    const groupFiles = [
      ...(extensionOf(main.name) === '.cnt' ? [main, ...extras] : [main]),
      ...(note ? [note] : []),
    ];
    const totalBytes = groupFiles.reduce((sum, f) => sum + f.size, 0);
    const limit = maxUploadBytes();
    if (totalBytes > limit) {
      errors.push(
        `${main.name}: ${(totalBytes / 1024 ** 2).toFixed(1)} MB is over the ${limit / 1024 ** 2} MB upload limit.`,
      );
      continue;
    }
    groups.push({ stem: stemOf(main.name), main, files: groupFiles, totalBytes });
  }
  for (const [key, note] of notes) {
    if (!mains.has(key)) {
      errors.push(`${note.name}: session notes go with the recording of the same name — drop them together.`);
    }
  }
  for (const [key, extras] of sidecars) {
    if (!mains.has(key)) {
      errors.push(`${extras.map((f) => f.name).join(', ')}: drop these together with the matching .cnt file.`);
    }
  }
  return { groups, errors };
}

// ---------- network ----------

async function fetchJson(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<{ body: unknown; status: number }> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener('abort', onAbort);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    const body: unknown = await res.json().catch(() => null);
    return { body, status: res.status };
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      if (timedOut) throw new DecoderError('The decoder took too long to answer.');
      throw new DecodeAbortedError('Request cancelled.');
    }
    throw new DecoderError(
      'Could not send the request: the decoder is not reachable, or a dropped file could not be read.',
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

export async function fetchHealth(base: string = decoderBase(), signal?: AbortSignal): Promise<Health> {
  const { body, status } = await fetchJson(`${base}/api/health`, { cache: 'no-store' }, HEALTH_TIMEOUT_MS, signal);
  const data = unwrapEnvelope(body, status);
  if (!isObj(data) || data.status !== 'ok') throw new DecoderError('Decoder is not ready.');
  return { status: 'ok', models: strings(data.models) };
}

export async function decodeRecording(
  group: FileGroup,
  options: { expected?: string; model?: string; signal?: AbortSignal } = {},
  base: string = decoderBase(),
): Promise<DecodeResult> {
  const form = new FormData();
  for (const f of group.files) form.append('files', f, f.name);
  const expected = options.expected?.trim();
  if (expected) form.append('expected', expected);
  form.append('model', options.model || 'clench');
  const { body, status } = await fetchJson(
    `${base}/api/recordings/decode`,
    { method: 'POST', body: form },
    DECODE_TIMEOUT_MS,
    options.signal,
  );
  return parseDecodeResult(unwrapEnvelope(body, status));
}
