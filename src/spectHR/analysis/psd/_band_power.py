# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/psd/_band_power.py
"""Band-power integration (CARSPAN manual Eq. 3.28)."""

from __future__ import annotations

import numpy as np

__all__ = ["band_power_rectangular"]


def band_power_rectangular(
    freqs: np.ndarray,
    power: np.ndarray,
    f_low: float,
    f_high: float,
) -> float:
    """Rectangular-rule band power integration (CARSPAN Eq. 3.28).

    ``B = Σ S_xx(fₖ) · Δfₖ`` for ``f_low ≤ fₖ ≤ f_high``, both endpoints
    inclusive. Per-bin Δfₖ is the centred neighbour spacing so the
    integration adapts to both uniform (Welch, Lomb-Scargle) and the
    Resample-binned CARSPAN display grid.

    Returns 0 if no bin falls inside the band.
    """
    mask = (freqs >= f_low) & (freqs <= f_high)
    band_freqs = freqs[mask]
    band_power = power[mask]

    if band_freqs.size == 0:
        return 0.0

    if band_freqs.size == 1:
        if freqs.size > 1:
            delta_f = float(freqs[1] - freqs[0])
        else:
            delta_f = float(band_freqs[0])
        return float(band_power[0] * delta_f)

    spacings = np.diff(band_freqs)
    delta_f_per_bin = np.empty_like(band_freqs)
    delta_f_per_bin[0] = spacings[0]
    delta_f_per_bin[-1] = spacings[-1]
    delta_f_per_bin[1:-1] = (spacings[:-1] + spacings[1:]) / 2.0

    return float(np.sum(band_power * delta_f_per_bin))
