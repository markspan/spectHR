"""
CarspanPSD.py – CARSPAN event-series spectral analysis.

Implements the DFT of an R-peak event series (unit impulses) as described
in Chapter 3 of the CARSPAN manual (Mulder et al.).

    X(fₖ) = Σᵢ wᵢ · exp(−2π j fₖ tᵢ)
    S_xx(fₖ) = (2 / T) |X(fₖ)|²         (strict, Eq. 3.19)
    S_xx(fₖ) = (2 N / (T · S₂)) |X(fₖ)|²  (configurable, with N/S₂ correction)

Native grid Δf = 1/T, optionally bin-averaged onto a 0.01 Hz display grid.
Output units: **Hz** (events²/Hz).  Conversion to mMI²/Hz is done by the
caller (CardioFrequencyMetricsMixin).

References
----------
L. J. M. Mulder, "CARSPAN Manual", Ch. 3.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from scipy.signal import get_window

from spectHR.Tools.PSD._psd_utils import (
    _chi2_ci,
    _require_min_samples,
    _resolve_window,
    update_params,
)


CARSPAN_PARAMS = {
    "freq_resolution": 0.01,      # Hz — display grid spacing
    "window": "hann",             # Default window for configurable mode
    "smooth_for_display": True,   # Bin-average to the display grid
    "plot_units": "mMI²/Hz",      # "mMI²/Hz" or "ms²/Hz" (IBI signal)
}


def load_carspan_params(config: dict) -> None:
    """Update module-level CARSPAN_PARAMS from a workspace config dict."""
    update_params(CARSPAN_PARAMS, config)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_carspan_psd(
    event_times_s: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    f_max: float = 0.5,
    window: Optional[str] = None,
    smooth: Optional[bool] = None,
    display_resolution: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Configurable CARSPAN PSD with chi-squared CI.

    The window is applied by **event index** (scipy-style) and the power
    is N/S₂-corrected.  Any scipy-compatible window name is accepted
    (including the "X% cosine bell" convention).

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds in Hz (events²/Hz).
    """
    window_spec = _resolve_window(
        window if window is not None else CARSPAN_PARAMS["window"]
    )
    freqs, power, bin_counts = _compute(
        event_times_s,
        f_max=f_max,
        smooth=smooth,
        display_resolution=display_resolution,
        strict=False,
        window_spec=window_spec,
    )
    ci_lower, ci_upper = _chi2_ci(power, 2 * bin_counts, alpha_ci)
    return freqs, power, ci_lower, ci_upper


def compute_carspan_psd_strict(
    event_times_s: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    f_max: float = 0.5,
    alpha_taper: float = 0.10,
    smooth: Optional[bool] = None,
    display_resolution: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Strict (manual-faithful) CARSPAN PSD with chi-squared CI.

    The Tukey window (α=0.10 → 5 % cosine bell per side) is applied by
    **time position**, and no N/S₂ correction is used — faithful to the
    CARSPAN manual Eq. 3.19.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds in Hz (events²/Hz).
    """
    freqs, power, bin_counts = _compute(
        event_times_s,
        f_max=f_max,
        smooth=smooth,
        display_resolution=display_resolution,
        strict=True,
        alpha_taper=alpha_taper,
    )
    ci_lower, ci_upper = _chi2_ci(power, 2 * bin_counts, alpha_ci)
    return freqs, power, ci_lower, ci_upper


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _compute(
    event_times_s,
    *,
    f_max,
    smooth,
    display_resolution,
    strict,
    window_spec=None,
    alpha_taper=0.10,
):
    """Shared strict/configurable CARSPAN PSD computation."""
    smooth = smooth if smooth is not None else CARSPAN_PARAMS["smooth_for_display"]
    display_resolution = float(
        display_resolution
        if display_resolution is not None
        else CARSPAN_PARAMS["freq_resolution"]
    )

    N = event_times_s.size
    _require_min_samples(N, 4, "CARSPAN PSD")

    T = float(event_times_s[-1] - event_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")

    delta_f = 1.0 / T
    k_max = int(np.floor(f_max / delta_f))
    freqs = np.arange(1, k_max + 1) * delta_f

    if strict:
        w = _tukey_by_time_fraction(event_times_s, alpha=alpha_taper)
        amplitude = 2.0 / T
    else:
        ws = window_spec
        if isinstance(ws, str) and ws.lower() == "tukey":
            ws = ("tukey", 0.10)
        w = get_window(ws, N, fftbins=False).astype(np.float64)
        S2 = float(np.sum(w ** 2))
        if S2 == 0:
            raise ValueError("Window sum-of-squares S₂ is zero — degenerate window.")
        amplitude = 2.0 * N / (T * S2)

    # X(f) = Σ wᵢ exp(-2πj f tᵢ), split into real/imag to avoid complex arrays.
    phase = 2.0 * np.pi * np.outer(freqs, event_times_s)
    X_real = np.dot(np.cos(phase), w)
    X_imag = np.dot(-np.sin(phase), w)
    power = amplitude * (X_real ** 2 + X_imag ** 2)

    if smooth and freqs.size > 0 and delta_f < display_resolution * 0.99:
        freqs, power, bin_counts = _bin_average(freqs, power, display_resolution)
    else:
        bin_counts = np.ones(freqs.size, dtype=int)

    # CARSPAN manual (sec. 3.2, p. 33): "a moving average window over three
    # frequency points (0.03 Hz bandwidth) is applied before plotting the
    # spectral functions". This is plot-only smoothing — band-power
    # integration on the spectHR side uses this same array, so the area is
    # preserved (3-point MA preserves total sum modulo small boundary
    # effects), and peaks visually drop ≈3× to match CARSPAN's display.
    if smooth and power.size >= 3:
        kernel = np.ones(3, dtype=np.float64) / 3.0
        power = np.convolve(power, kernel, mode="same")

    return freqs, power, bin_counts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tukey_by_time_fraction(event_times_s, alpha=0.10):
    """
    Tukey window evaluated at each event's fractional position in [t₀, t_end].

    Unlike scipy's index-based tukey, this taper acts on clock time — the
    weight depends on *where* each event falls within the observation
    interval, matching the CARSPAN manual's specification of a "5 % cosine
    bell" applied to the signal timeline.
    """
    N = event_times_s.size
    if N < 2:
        return np.ones(N, dtype=np.float64)

    t0, t_end = float(event_times_s[0]), float(event_times_s[-1])
    T = t_end - t0
    if T <= 0:
        return np.ones(N, dtype=np.float64)

    frac = (event_times_s - t0) / T
    w = np.ones(N, dtype=np.float64)

    left = frac < alpha / 2
    w[left] = 0.5 * (1.0 - np.cos(2.0 * np.pi * frac[left] / alpha))

    right = frac > (1.0 - alpha / 2)
    w[right] = 0.5 * (1.0 - np.cos(2.0 * np.pi * (1.0 - frac[right]) / alpha))

    return w


def _bin_average(native_freqs, native_power, display_resolution):
    """
    Bin-average the native grid onto a display grid starting at 2 × resolution.

    Returns (display_freqs, display_power, bin_counts).  Effective dof per
    display bin is ``2 × bin_counts`` — averaging k native bins raises the
    chi-squared dof from 2 (single DFT) to 2k.

    The first display bin is centred at 2·Δ (e.g. 0.020 Hz for Δ=0.01 Hz),
    so native bins below 1.5·Δ (near-DC, high 1/f power) are excluded.
    """
    f_max = native_freqs[-1]
    first_edge = 1.5 * display_resolution
    bin_edges = np.arange(first_edge, f_max + display_resolution, display_resolution)

    out_freqs, out_power, counts = [], [], []
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (native_freqs >= lo) & (native_freqs < hi)
        count = int(np.sum(mask))
        if count > 0:
            # Round to the resolution multiple to avoid float accumulation from arange.
            center = round((lo + hi) / 2.0 / display_resolution) * display_resolution
            out_freqs.append(center)
            out_power.append(float(np.mean(native_power[mask])))
            counts.append(count)

    return (
        np.array(out_freqs),
        np.array(out_power),
        np.array(counts, dtype=int),
    )


