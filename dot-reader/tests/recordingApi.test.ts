import { describe, it, expect } from "bun:test";
import {
  DecoderError,
  MAX_UPLOAD_BYTES,
  effectiveModel,
  groupFiles,
  isFolderPlaceholder,
  parseDecodeResult,
  parseScore,
  parseTrace,
  unwrapEnvelope,
} from "../src/lib/recordingApi";

const file = (name: string, size = 10) => new File([new Uint8Array(size)], name);

/** File whose reported size is large without allocating it. */
const bigFile = (name: string, size: number) => {
  const f = file(name);
  Object.defineProperty(f, "size", { value: size });
  return f;
};

const validResult = {
  file: "session.cnt",
  duration_s: 60,
  sfreq: 500,
  n_channels: 24,
  channels_used: ["T7", "T8"],
  bad_channels: [],
  model: "clench",
  text: "How are you?",
  raw_text: "HPW ARE YOU",
  corrected_text: "HOW ARE YOU",
  morse: ".... --- .-- / .- .-. . / -.-- --- ..-",
  sentence_types: ["question"],
  corrections: [{ from: "HPW", to: "HOW", cost: 1 }],
  letters: [{ code: "....", char: "H", status: "ok", t_start: 1, t_end: 2 }],
  elements: [{ t_on: 1, t_off: 1.3, symbol: ".", boundary: "start" }],
  artifacts: [{ t_on: 5, t_off: 5.2, kind: "blink", channel: null, action: "removed" }],
  trace: { t: [0, 1, 2], activation: [0, 1, 0], lo: 0.4, hi: 0.6 },
  quality: { separability: 0.85, n_key_downs: 12, n_artifacts: 1, artifact_aware: true, warnings: [] },
  timing: { unit_s: 0.3, dash_threshold_s: 0.6, letter_gap_s: 0.6, word_gap_s: 1.5 },
  score: null,
};

describe("groupFiles", () => {
  it("bundles a .cnt with its .evt and .seg sidecars into one upload", () => {
    const { groups, errors } = groupFiles([file("s1.cnt"), file("s1.evt"), file("S1.seg")]);
    expect(errors).toEqual([]);
    expect(groups).toHaveLength(1);
    expect(groups[0].files.map((f) => f.name)).toEqual(["s1.cnt", "s1.evt", "S1.seg"]);
  });

  it("makes one group per recording", () => {
    const { groups } = groupFiles([file("a.edf"), file("b.npz"), file("c.cnt")]);
    expect(groups.map((g) => g.stem)).toEqual(["a", "b", "c"]);
  });

  it("rejects unsupported extensions with a friendly error", () => {
    const { groups, errors } = groupFiles([file("notes.pdf")]);
    expect(groups).toEqual([]);
    expect(errors[0]).toContain("unsupported file type");
  });

  it("flags orphan sidecars dropped without their .cnt", () => {
    const { groups, errors } = groupFiles([file("s1.evt"), file("s1.seg")]);
    expect(groups).toEqual([]);
    expect(errors[0]).toContain("matching .cnt");
  });

  it("refuses uploads over the size limit", () => {
    const { groups, errors } = groupFiles([bigFile("huge.cnt", MAX_UPLOAD_BYTES + 1)]);
    expect(groups).toEqual([]);
    expect(errors[0]).toContain("500 MB");
  });
});

describe("session notes", () => {
  const f = (name: string, size = 10) => new File(["x".repeat(size)], name);
  it("travel with the recording of the same name", () => {
    const { groups, errors } = groupFiles([f("s.cnt"), f("s.evt"), f("s.seg"), f("s.txt")]);
    expect(errors).toEqual([]);
    expect(groups[0].files.map((x) => x.name)).toEqual(["s.cnt", "s.evt", "s.seg", "s.txt"]);
  });
  it("can go with any recording type", () => {
    expect(groupFiles([f("a.npz"), f("a.txt")]).groups[0].files).toHaveLength(2);
  });
  it("are flagged when dropped without their recording", () => {
    expect(groupFiles([f("lonely.txt")]).errors[0]).toContain("session notes");
  });
  it("are parsed as a list and default to empty", () => {
    expect(parseDecodeResult({ ...validResult, session_notes: ["Hi", 3, "There"] }).session_notes).toEqual(["Hi", "There"]);
    expect(parseDecodeResult(validResult).session_notes).toEqual([]);
  });
});

describe("parseDecodeResult", () => {
  it("reads the reliable flag and defaults it to true for older servers", () => {
    expect(parseDecodeResult({ ...validResult, reliable: false, text: "" }).reliable).toBe(false);
    expect(parseDecodeResult(validResult).reliable).toBe(true);
  });

  it("accepts a complete result", () => {
    const r = parseDecodeResult(validResult);
    expect(r.text).toBe("How are you?");
    expect(r.artifacts[0].kind).toBe("blink");
    expect(r.sentence_types).toEqual(["question"]);
  });

  it("drops malformed list items instead of failing", () => {
    const r = parseDecodeResult({
      ...validResult,
      letters: [validResult.letters[0], { code: 3 }],
      elements: [{ symbol: "x" }],
      artifacts: [{ kind: "sneeze", action: "removed", t_on: 0, t_off: 1 }],
    });
    expect(r.letters).toHaveLength(1);
    expect(r.elements).toEqual([]);
    expect(r.artifacts).toEqual([]);
  });

  it("trims mismatched trace arrays to the same length", () => {
    const r = parseDecodeResult({ ...validResult, trace: { t: [0, 1, 2], activation: [1], lo: 0, hi: 1 } });
    expect(r.trace.t).toHaveLength(1);
  });

  it("throws a DecoderError when the final text is missing", () => {
    expect(() => parseDecodeResult({ ...validResult, text: undefined })).toThrow(DecoderError);
  });

  it("throws when quality is missing", () => {
    expect(() => parseDecodeResult({ ...validResult, quality: undefined })).toThrow(DecoderError);
  });
});

describe("unwrapEnvelope", () => {
  it("returns data on success", () => {
    expect(unwrapEnvelope({ success: true, data: 1, error: null }, 200)).toBe(1);
  });

  it("surfaces the server error message", () => {
    expect(() => unwrapEnvelope({ success: false, data: null, error: "bad file" }, 400)).toThrow("bad file");
  });

  it("handles non-JSON replies", () => {
    expect(() => unwrapEnvelope(null, 502)).toThrow("HTTP 502");
  });
});

describe("review fixes", () => {
  it("keeps t/activation paired when one side has a bad sample", () => {
    const trace = parseTrace({ t: [0, 1, 2, 3], activation: [5, null, 7, Number.NaN], lo: 1, hi: 2 });
    expect(trace.t).toEqual([0, 2]);
    expect(trace.activation).toEqual([5, 7]);
  });

  it("returns null thresholds when the server omits them", () => {
    const trace = parseTrace({ t: [0, 1], activation: [1, 2] });
    expect(trace.lo).toBeNull();
    expect(trace.hi).toBeNull();
  });

  it("treats a malformed optional score as absent", () => {
    expect(parseScore({ expected: "HI", cer: "bad" })).toBeNull();
    expect(parseScore({ cer: 0.1 })).toBeNull();
    expect(parseScore({ expected: "HI", cer: 0, exact: true })).toEqual({ expected: "HI", cer: 0, exact: true });
  });

  it("rejects dropped folders instead of uploading empty files", () => {
    const folder = new File([], "session_data.csv", { type: "" });
    expect(isFolderPlaceholder(folder)).toBe(true);
    const { groups, errors } = groupFiles([folder]);
    expect(groups).toHaveLength(0);
    expect(errors[0]).toContain("folders are not supported");
  });

  it("explains same-name recordings clearly", () => {
    const { groups, errors } = groupFiles([file("s1.cnt"), file("s1.edf")]);
    expect(groups).toHaveLength(1);
    expect(errors[0]).toContain("s1.cnt has the same name");
  });

  it("falls back to the server's first model when the chosen one is missing", () => {
    expect(effectiveModel("clench", ["clench", "blink"])).toBe("clench");
    expect(effectiveModel("clench", ["clench_v2", "blink"])).toBe("clench_v2");
    expect(effectiveModel("clench", [])).toBe("clench");
  });
});
