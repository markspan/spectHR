"""Band-power integration (CARSPAN manual Eq. 3.28).

Rectangular-rule integration of a PSD over a frequency band, with
per-bin Δf computed from centred neighbour spacing so the same helper
adapts to both uniform grids (Welch, Lomb-Scargle) and the
Resample-binned CARSPAN display grid.

Lives in :mod:`spectHR.Tools.PSD` rather than alongside the mixin
because it has no series dependency — it just takes two arrays and two
floats. Imported by :class:`CardioMetricsMixin` for its ``band_power``
and ``band_powers`` methods.
"""

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
    inclusive. Per-bin Δfₖ is the centred neighbour spacing, so the
    integration adapts to both uniform (Welch, L-S) and the
    Resample-binned CARSPAN display grid.

    Returns 0 if no bin falls inside the band (e.g. a band that lies
    entirely below the lowest frequency of the spectrum, or above the
    highest). For a single in-band bin, ``Δf`` falls back to the
    spectrum's first-bin spacing.
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
