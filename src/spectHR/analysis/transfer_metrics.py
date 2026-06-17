# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/transfer_metrics.py
"""
Per-epoch transfer-function band metrics.

Registers one ``@epoch_metric_group``, ``transfer_band_metrics``, that
emits three columns per configured frequency band:

``{band}_tf_modulus``
    Coherence-gated mean ``|H(f)|`` over the band.  Units are ms/mmHg for
    BP inputs, dimensionless for respiration.

``{band}_tf_coherence``
    Power-weighted mean squared coherence over the band
    (``Σ coh[k]·PSD_in[k] / Σ PSD_in[k]``).

``{band}_tf_phase_w``
    Coherence-gated mean **wrapped** phase (radians) over the band.

All three are ``NaN`` when the transfer function cannot be computed
(missing input channel, fewer than 4 clean R-peaks, no coherent bins).

``FullRange`` is excluded from the band loop because a coherence-gated
average over the entire 0.02–0.50 Hz range is not clinically meaningful.

References
----------
CARSPAN manual §3.1.5 (baroreflex sensitivity, weighted coherence);
``T_AnaFunctions.pas`` ``Caluculate_WeightedCoherenceSum`` (883),
``Caluculate_ModulusSum`` (963), ``Caluculate_PhaseSum`` (935).
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.epoch_context import EpochContext
from spectHR.analysis.registry import epoch_metric_group

# Suffix → tooltip text for dynamically-named transfer-function columns.
# Results widget uses these to annotate column headers whose names cannot be
# known at import time (they include the configured band name).
TRANSFER_COLUMN_TOOLTIPS: dict[str, str] = {
    "_tf_modulus": (
        "Transfer function modulus |H(f)| averaged over this band, gated to "
        "bins where squared coherence ≥ threshold. "
        "Units: ms/mmHg (BP input) or dimensionless (respiration input). "
        "Reflects the gain of the input→IBI transfer, baroreflex sensitivity "
        "when the input is blood pressure."
    ),
    "_tf_coherence": (
        "Power-weighted mean squared coherence over this band "
        "(Σ coh[k]·PSD_in[k] / Σ PSD_in[k]). "
        "Ranges 0–1; values below the threshold (~0.5) indicate a weak or "
        "non-linear coupling, treat the modulus and phase with caution."
    ),
    "_tf_phase_w": (
        "Mean wrapped phase ∠H(f) in radians over the coherent bins in this "
        "band. Positive values indicate IBI lags the input; negative values "
        "indicate IBI leads. Reported as the coherence-weighted circular mean."
    ),
}


@epoch_metric_group
def transfer_band_metrics(ctx: EpochContext) -> dict[str, float]:
    """Per-band transfer-function scalars (modulus, coherence, phase).

    Emits ``{band}_tf_modulus``, ``{band}_tf_coherence``, and
    ``{band}_tf_phase_w`` for every configured frequency band (excluding
    FullRange).  Returns an empty dict when the transfer result is
    unavailable.

    Transfer function: H(f) = CrossSpectrum(input, IBI) / AutoSpectrum(input).
    Note: this is an open-loop estimate of the closed-loop BP–HR system.
    """
    tf = getattr(ctx, "transfer_result", None)
    if tf is None:
        return {}
    band_results = getattr(tf, "band_results", None) or {}
    out: dict[str, float] = {}
    for band_name, bt in band_results.items():
        if band_name == "FullRange":
            continue
        prefix = f"{band_name.lower()}_tf"
        out[f"{prefix}_modulus"]   = float(bt.modulus)   if bt.n_coherent > 0 else np.nan
        out[f"{prefix}_coherence"] = float(bt.weighted_coherence)
        out[f"{prefix}_phase_w"]   = float(bt.phase)     if bt.n_coherent > 0 else np.nan
    return out
