"""Diagnostic figure: raw band signal -> activation + thresholds -> dots/dashes -> letters.

This is the "show your work" view for a demo: every decoded letter can be
traced back to the key-down intervals and the EEG trace that produced it.
"""
from __future__ import annotations

import numpy as np

from .pipeline import Result


def plot_result(res: Result, path: str, truth=None, start: float | None = None,
                stop: float | None = None, title: str | None = None, labels=None) -> str:
    """labels: Annotations (e.g. from eego) drawn as coloured bars under the trace."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    act, th, tr = res.activation, res.thresholds, res.transcript
    t0 = act.t[0] if start is None else start
    t1 = act.t[-1] if stop is None else stop
    span = max(t1 - t0, 1.0)
    width = float(np.clip(span / 4.0, 10, 40))
    fig, axes = plt.subplots(3, 1, figsize=(width, 7.5), sharex=True,
                             gridspec_kw=dict(height_ratios=[1.1, 1.6, 0.8]))
    ink, muted, accent, warn = "#1f2328", "#8c959f", "#0969da", "#cf222e"

    # 1. band-passed EEG on the first used channel
    ax = axes[0]
    step = max(1, int(act.sfreq // 250))
    ts = np.arange(act.filtered.shape[1])[::step] / act.sfreq
    sel = (ts >= t0) & (ts <= t1)
    ax.plot(ts[sel], act.filtered[0, ::step][sel], lw=0.5, color=ink)
    f = res.config.feature
    ax.set_ylabel(f"{act.channels[0]}\n{f.band[0]:g}-{f.band[1]:g} Hz", fontsize=9)
    ax.set_title(title or f"Decoded: {tr.text or '(nothing)'}", loc="left", fontsize=13,
                 color=ink, fontweight="bold")

    # 2. activation, thresholds, detected key-downs (and ground truth if simulated)
    ax = axes[1]
    sel = (act.t >= t0) & (act.t <= t1)
    ax.plot(act.t[sel], act.values[sel], lw=1.0, color=accent, label="activation")
    ax.axhline(th.hi, color=warn, lw=0.8, ls="--", label="on threshold")
    ax.axhline(th.lo, color=muted, lw=0.8, ls="--", label="off threshold")
    ymin, ymax = np.percentile(act.values[sel], [0.5, 99.5])
    pad = 0.15 * (ymax - ymin + 1e-12)
    ax.set_ylim(ymin - pad, ymax + 2.2 * pad)
    for e in tr.elements:
        ax.axvspan(e.t_on, e.t_off, color=accent, alpha=0.12, lw=0)
        ax.text((e.t_on + e.t_off) / 2, ymax + 0.9 * pad, "•" if e.symbol == "." else "—",
                ha="center", va="center", fontsize=12, color=ink)
    if labels:
        palette = ["#1a7f37", "#8250df", "#bf8700", "#cf222e", "#0550ae"]
        kinds = sorted({l.label for l in labels})
        for l in labels:
            col = palette[kinds.index(l.label) % len(palette)]
            ax.plot([l.onset, l.onset + max(l.duration, 0.15)], [ymin - 0.6 * pad] * 2,
                    color=col, lw=4, solid_capstyle="butt")
        for k in kinds:
            ax.plot([], [], color=palette[kinds.index(k) % len(palette)], lw=4, label=f"label: {k}")
    if truth is not None:
        for a, b in zip(truth.t_on, truth.t_off):
            ax.plot([a, b], [ymin - 0.6 * pad] * 2, color="#1a7f37", lw=3, solid_capstyle="butt")
        ax.plot([], [], color="#1a7f37", lw=3, label="true key-down (simulated)")
    label = "-log band power (ERD)" if f.direction == "decrease" else (
        "log band power" if f.measure == "power" else "amplitude")
    ax.set_ylabel(f"activation\n{label}", fontsize=9)
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.995, 0.995), ncol=4,
               fontsize=8, frameon=False)

    # 3. letters
    ax = axes[2]
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    for l in tr.letters:
        mid = (l.t_start + l.t_end) / 2
        color = ink if l.status == "ok" else warn
        ax.text(mid, 0.62, l.char, ha="center", va="center", fontsize=15,
                fontweight="bold", color=color)
        ax.text(mid, 0.25, l.code, ha="center", va="center", fontsize=9,
                color=muted, family="monospace")
        ax.plot([l.t_start, l.t_end], [0.08, 0.08], color=muted, lw=1)
    ax.set_xlabel("time in recording (s)" if len(res.recording.segments) > 1 else "time (s)")
    ax.set_xlim(t0, t1)
    for a, _ in res.recording.segments[1:]:
        for axx in axes:
            axx.axvline(a / res.recording.sfreq, color=muted, lw=0.8, ls=":")
    if len(res.recording.segments) > 1:
        axes[0].text(1.0, 1.02, "dotted lines = recording paused/resumed", transform=axes[0].transAxes,
                     ha="right", va="bottom", fontsize=7, color=muted)
    for a in axes:
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        a.tick_params(labelsize=8, colors=ink)
    fig.text(0.995, 0.005,
             f"unit {tr.unit_s:.2f}s ({tr.unit_source.split(' ')[0]})  ·  separability "
             f"{th.separability:.2f}  ·  channels {', '.join(act.channels)}  ·  {res.recording.source}",
             ha="right", va="bottom", fontsize=7, color=muted)
    fig.tight_layout(rect=(0, 0.02, 1, 0.965))
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
