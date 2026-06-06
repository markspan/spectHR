# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/respiration_metrics.py
"""
Respiration-context HRV metrics.

HF-HRV amplitude depends not only on vagal tone but also on the rate and
depth of breathing (Grossman & Taylor, 2007): the same vagal drive
produces a smaller HF peak when breathing is fast or shallow, and a
breathing frequency that drifts *out of* the HF band (0.15-0.40 Hz, i.e.
9-24 breaths/min) breaks the assumption that HF power indexes respiratory
sinus arrhythmia at all.

spectHR therefore surfaces, per epoch, the two quantities a researcher
needs to judge whether an HF change is vagal or merely a breathing
artefact:

``resp_rate``
    Mean breathing frequency in Hz.
``hf_resp_in_band``
    1.0 when the mean breathing frequency falls inside the configured HF
    band, 0.0 when it falls outside (a flag that the HF estimate may be
    contaminated), ``NaN`` when it cannot be determined.

The actual statistical *correction* of HF for respiration (regressing HF
on rate/depth across epochs or subjects) is deliberately left to the
analyst's statistics package (R / JASP) rather than baked into the tool —
these two columns are the inputs that make that correction possible.

Reference
---------
Grossman, P., & Taylor, E. W. (2007). Toward understanding respiratory
sinus arrhythmia: relations to cardiac vagal tone, evolution and
biobehavioral functions. *Biological Psychology*, 74(2), 263-285.
"""
from __future__ import annotations

from spectHR.analysis.registry import epoch_metric
from spectHR.Tools.RespirationSegmentation import mean_breath_frequency_hz


__all__ = ["resp_rate", "hf_resp_in_band"]


def _mean_breath_hz(ctx):
    """Mean breathing frequency (Hz) for the epoch, or None."""
    phases = getattr(ctx, "rsp_phases", None)
    if phases is None or len(phases) < 2:
        return None
    try:
        return mean_breath_frequency_hz(phases)
    except Exception:
        return None


@epoch_metric
def resp_rate(ctx) -> float:
    """Mean breathing frequency in Hz (blank when no respiration channel)."""
    f = _mean_breath_hz(ctx)
    return float(f) if f is not None else float("nan")


@epoch_metric
def hf_resp_in_band(ctx) -> float:
    """1.0 if mean breathing frequency lies inside the HF band, else 0.0 (Grossman & Taylor 2007)."""
    f = _mean_breath_hz(ctx)
    if f is None:
        return float("nan")
    method = getattr(ctx, "psd_method", None)
    bands = getattr(method, "bands", None) if method is not None else None
    if not bands or "HF" not in bands:
        return float("nan")
    hf = bands["HF"]
    return 1.0 if (hf.low <= f <= hf.high) else 0.0
