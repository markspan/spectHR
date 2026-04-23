"""
CarspanPSD.py – CARSPAN event-series spectral analysis.

Implements the Direct Fourier Transform (DFT) of an R-peak event series
as described in Chapter 3 of the CARSPAN manual (Version 3.6, Mulder et al.).

The key idea: treat R-peaks as unit impulses x(t) = Σ δ(t − tᵢ), compute
the Fourier coefficients at frequencies fₖ = k / T via:

    X(fₖ) = Σᵢ exp(−2π j fₖ tᵢ)          (Eq. 3.17)

and derive the one-sided power spectral density:

    S_xx(fₖ) = (2 / T) |X(fₖ)|²           (Eq. 3.19)

The spectrum has units **Hz** (events²/Hz, since the "signal" is a rate).

Two modes are provided
----------------------
1. **Strict mode** (``compute_carspan_psd_strict``):
   Faithful to the CARSPAN manual — uses a 5 % cosine bell (Tukey α = 0.10)
   applied by *time position* (not event index), formula ``(2/T)|X_w|²``
   with no N/S₂ correction.

2. **Configurable mode** (``compute_carspan_psd``):
   Applies the window by *event index* (like scipy), includes the N/S₂
   correction to compensate for the window's power loss, and accepts any
   scipy-compatible window name.  Formula: ``(2N / (T · S₂)) |X_w|²``.

Output units
------------
**Hz** (events²/Hz).  Conversion to mMI²/Hz is done by the caller.

References
----------
L. J. M. Mulder, "CARSPAN Manual", Chapter 3 — Signal processing
algorithms, Equations 3.12, 3.17–3.20, 3.28.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Module-level default parameters (overridden by workspace config)
# ---------------------------------------------------------------------------

CARSPAN_PARAMS = {
    "freq_resolution": 0.01,  # Hz  (native grid spacing Δf = 1/T)
    "window": "hann",  # Default window for *configurable* mode
    "smooth_for_display": True,  # Bin-average to 0.01 Hz display grid
}


def load_carspan_params(config: dict) -> None:
    """
    Update module-level CARSPAN_PARAMS from a workspace configuration dict.

    Parameters
    ----------
    config : dict
        Keys matching CARSPAN_PARAMS will be updated; unknown keys are
        ignored.
    """
    for key in CARSPAN_PARAMS:
        if key in config:
            CARSPAN_PARAMS[key] = config[key]


# ===================================================================
#  Internal helpers
# ===================================================================


def _tukey_by_time_fraction(
    event_times_s: np.ndarray,
    alpha: float = 0.10,
) -> np.ndarray:
    """
    Evaluate a Tukey (cosine-taper) window at arbitrary *time positions*.

    The CARSPAN manual prescribes a "5 % cosine bell", meaning 5 % of the
    segment duration is tapered at each end.  That corresponds to a Tukey
    window with α = 0.10 (10 % total taper, split equally between both
    sides).

    Unlike ``scipy.signal.windows.tukey``, which evaluates the window at
    equally-spaced *sample indices*, this function maps each event's
    timestamp to its fractional position within the observation interval
    [t₀, t_end] and evaluates the Tukey formula there.

    Parameters
    ----------
    event_times_s : np.ndarray, shape (N,)
        R-peak timestamps in seconds.
    alpha : float
        Tukey parameter (fraction of the total duration that is tapered).
        Default 0.10 (= 5 % per side).

    Returns
    -------
    w : np.ndarray, shape (N,)
        Window weight for each event, in [0, 1].
    """
    N = event_times_s.size
    if N < 2:
        return np.ones(N, dtype=np.float64)

    t0 = float(event_times_s[0])
    t_end = float(event_times_s[-1])
    T = t_end - t0

    if T <= 0:
        return np.ones(N, dtype=np.float64)

    # Fractional position of each event in [0, 1]
    frac = (event_times_s - t0) / T

    w = np.ones(N, dtype=np.float64)

    # Left taper: frac in [0, α/2]
    left_mask = frac < alpha / 2
    w[left_mask] = 0.5 * (1.0 - np.cos(2.0 * np.pi * frac[left_mask] / alpha))

    # Right taper: frac in [1 − α/2, 1]
    right_mask = frac > (1.0 - alpha / 2)
    w[right_mask] = 0.5 * (1.0 - np.cos(2.0 * np.pi * (1.0 - frac[right_mask]) / alpha))

    return w


def _index_window(N: int, window_name: str) -> np.ndarray:
    """
    Return a window of length *N* evaluated at integer indices (scipy style).

    Parameters
    ----------
    N : int
        Number of events (window length).
    window_name : str
        Any window name accepted by ``scipy.signal.get_window`` (e.g.
        ``"hann"``, ``("tukey", 0.1)``, ``"boxcar"``).

    Returns
    -------
    w : np.ndarray, shape (N,)
    """
    from scipy.signal import get_window

    if N < 1:
        return np.array([], dtype=np.float64)

    return get_window(window_name, N, fftbins=False).astype(np.float64)


def _dft_event_series(
    event_times_s: np.ndarray,
    weights: np.ndarray,
    freqs_hz: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Direct Fourier Transform of a windowed event series.

    Computes:

        X(f) = Σᵢ wᵢ · exp(−2π j f tᵢ)

    separated into real and imaginary parts (avoids complex-number overhead
    and is more readable).

    Parameters
    ----------
    event_times_s : np.ndarray, shape (N,)
        R-peak timestamps in seconds.
    weights : np.ndarray, shape (N,)
        Per-event window weights.
    freqs_hz : np.ndarray, shape (K,)
        Frequencies at which to evaluate the DFT.

    Returns
    -------
    X_real : np.ndarray, shape (K,)
    X_imag : np.ndarray, shape (K,)
    """
    # Phase matrix: shape (K, N)
    # phase[k, i] = 2π · f_k · t_i
    phase = 2.0 * np.pi * np.outer(freqs_hz, event_times_s)

    # Windowed cosine and sine sums
    X_real = np.dot(np.cos(phase), weights)  # shape (K,)
    X_imag = np.dot(-np.sin(phase), weights)  # shape (K,)  (note minus sign)

    return X_real, X_imag


def _native_frequency_grid(T: float, f_max: float) -> np.ndarray:
    """
    Build the native CARSPAN frequency grid: fₖ = k / T, for k = 1, 2, …

    The grid starts at f₁ = 1/T (excluding DC) and extends up to f_max.

    Parameters
    ----------
    T : float
        Total observation duration in seconds.
    f_max : float
        Upper frequency limit in Hz.

    Returns
    -------
    freqs : np.ndarray, shape (K,)
        Frequencies in Hz on the native grid.
    """
    if T <= 0:
        raise ValueError("Observation duration T must be > 0.")

    delta_f = 1.0 / T
    k_max = int(np.floor(f_max / delta_f))
    k_values = np.arange(1, k_max + 1)  # k = 1 … k_max (no DC)

    return k_values * delta_f


def _bin_average_to_display_grid(
    native_freqs: np.ndarray,
    native_power: np.ndarray,
    display_resolution: float = 0.01,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Bin-average a native-grid PSD onto a coarser display grid.

    CARSPAN displays spectra at 0.01 Hz resolution.  When T > 100 s the
    native grid (Δf = 1/T < 0.01 Hz) is finer, so we average adjacent
    bins into 0.01 Hz-wide slots.

    Parameters
    ----------
    native_freqs : np.ndarray, shape (K,)
    native_power : np.ndarray, shape (K,)
    display_resolution : float
        Target bin width in Hz (default 0.01).

    Returns
    -------
    display_freqs : np.ndarray
        Centre frequencies of display bins.
    display_power : np.ndarray
        Bin-averaged power values.
    """
    f_min = native_freqs[0]
    f_max = native_freqs[-1]

    # Build display bin edges
    bin_start = np.floor(f_min / display_resolution) * display_resolution
    bin_edges = np.arange(bin_start, f_max + display_resolution, display_resolution)

    display_freqs_list = []
    display_power_list = []

    for i in range(len(bin_edges) - 1):
        lo = bin_edges[i]
        hi = bin_edges[i + 1]
        mask = (native_freqs >= lo) & (native_freqs < hi)

        if np.any(mask):
            display_freqs_list.append((lo + hi) / 2.0)
            display_power_list.append(np.mean(native_power[mask]))

    return np.array(display_freqs_list), np.array(display_power_list)


# ===================================================================
#  Band-power integration (Eq. 3.28)
# ===================================================================


def band_power_rectangular(
    freqs: np.ndarray,
    power: np.ndarray,
    f_low: float,
    f_high: float,
) -> float:
    """
    Rectangular-rule band power integration (CARSPAN Eq. 3.28).

        B = Σ S_xx(fₖ) · Δf     for f_low ≤ fₖ < f_high

    Uses the *native* frequency grid spacing; each bin contributes its
    power times the spacing between consecutive grid points.

    Parameters
    ----------
    freqs : np.ndarray, shape (K,)
        Frequency axis (Hz), assumed sorted and > 0.
    power : np.ndarray, shape (K,)
        PSD values at those frequencies.
    f_low, f_high : float
        Band boundaries in Hz (inclusive lower, exclusive upper).

    Returns
    -------
    float
        Integrated band power.  Units match ``power`` × Hz.
    """
    mask = (freqs >= f_low) & (freqs < f_high)
    band_freqs = freqs[mask]
    band_power = power[mask]

    if band_freqs.size == 0:
        return 0.0

    # Use actual spacings between consecutive grid points
    if band_freqs.size == 1:
        # Single bin: assume uniform spacing from the full grid
        if freqs.size > 1:
            delta_f = float(freqs[1] - freqs[0])
        else:
            delta_f = float(band_freqs[0])  # fallback: f₁ = 1/T = Δf
        return float(band_power[0] * delta_f)

    # For multiple bins: use midpoint rule (spacing between consecutive)
    spacings = np.diff(band_freqs)
    # First bin uses spacing to the next; last bin uses spacing from previous
    delta_f_per_bin = np.empty_like(band_freqs)
    delta_f_per_bin[0] = spacings[0]
    delta_f_per_bin[-1] = spacings[-1]
    delta_f_per_bin[1:-1] = (spacings[:-1] + spacings[1:]) / 2.0

    return float(np.sum(band_power * delta_f_per_bin))


# ===================================================================
#  STRICT MODE  (manual-faithful)
# ===================================================================


def compute_carspan_psd_strict(
    event_times_s: np.ndarray,
    f_max: float = 0.5,
    alpha: float = 0.10,
    smooth: Optional[bool] = None,
    display_resolution: float = 0.01,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    CARSPAN PSD — strict (manual-faithful) mode.

    Implements the CARSPAN spectral algorithm exactly as described in the
    manual:

    1. Window: 5 % cosine bell (Tukey α = 0.10) applied by **time
       position** — each event is weighted according to where it falls in
       [t₀, t_end], not by its ordinal index.
    2. DFT: X(fₖ) = Σᵢ wᵢ exp(−2πj fₖ tᵢ)  on the native grid
       fₖ = k/T.
    3. PSD: S_xx(fₖ) = (2 / T) |X_w(fₖ)|²   (Eq. 3.19).
       **No** N/S₂ correction is applied — the manual does not prescribe it.

    Parameters
    ----------
    event_times_s : np.ndarray, shape (N,)
        R-peak timestamps in seconds.
    f_max : float
        Upper frequency limit in Hz (default 0.5).
    alpha : float
        Tukey parameter (default 0.10 = 5 % taper per side).
    smooth : bool, optional
        If True, bin-average to a 0.01 Hz display grid.  Defaults to
        ``CARSPAN_PARAMS["smooth_for_display"]``.
    display_resolution : float
        Display grid spacing when smoothing (default 0.01 Hz).

    Returns
    -------
    freqs : np.ndarray, shape (K,)
        Frequency axis in Hz.
    power : np.ndarray, shape (K,)
        Power spectral density in **Hz** (events²/Hz).
    """
    smooth = smooth if smooth is not None else CARSPAN_PARAMS["smooth_for_display"]

    # --- Input validation --------------------------------------------------
    N = event_times_s.size
    if N < 4:
        raise ValueError(f"Need at least 4 R-peak events for CARSPAN PSD, got {N}.")

    T = float(event_times_s[-1] - event_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")

    # --- Frequency grid (native: fₖ = k/T) --------------------------------
    freqs = _native_frequency_grid(T, f_max)

    # --- Time-based Tukey window -------------------------------------------
    w = _tukey_by_time_fraction(event_times_s, alpha=alpha)

    # --- Direct Fourier Transform ------------------------------------------
    X_real, X_imag = _dft_event_series(event_times_s, w, freqs)

    # --- PSD: S_xx = (2/T) |X_w|²  (Eq. 3.19) ----------------------------
    power = (2.0 / T) * (X_real**2 + X_imag**2)

    # --- Optional bin-averaging for display --------------------------------
    if smooth and freqs.size > 0:
        native_delta_f = 1.0 / T
        if native_delta_f < display_resolution * 0.99:
            freqs, power = _bin_average_to_display_grid(
                freqs, power, display_resolution
            )

    return freqs, power


# ===================================================================
#  CONFIGURABLE MODE
# ===================================================================


def compute_carspan_psd(
    event_times_s: np.ndarray,
    f_max: float = 0.5,
    window: Optional[str] = None,
    smooth: Optional[bool] = None,
    display_resolution: float = 0.01,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    CARSPAN PSD — configurable mode.

    Same DFT-of-events approach, but:

    - The window is applied by **event index** (like scipy), not by time
      position.
    - An N/S₂ correction compensates for the window's power loss:

          S_xx(fₖ) = (2N / (T · S₂)) |X_w(fₖ)|²

      where S₂ = Σ wᵢ² is the window's sum-of-squares.
    - Any scipy-compatible window name can be used.

    Parameters
    ----------
    event_times_s : np.ndarray, shape (N,)
        R-peak timestamps in seconds.
    f_max : float
        Upper frequency limit in Hz (default 0.5).
    window : str, optional
        Window name.  Defaults to ``CARSPAN_PARAMS["window"]``.
    smooth : bool, optional
        If True, bin-average to a 0.01 Hz display grid.  Defaults to
        ``CARSPAN_PARAMS["smooth_for_display"]``.
    display_resolution : float
        Display grid spacing when smoothing (default 0.01 Hz).

    Returns
    -------
    freqs : np.ndarray, shape (K,)
        Frequency axis in Hz.
    power : np.ndarray, shape (K,)
        Power spectral density in **Hz** (events²/Hz).
    """
    window = window if window is not None else CARSPAN_PARAMS["window"]
    smooth = smooth if smooth is not None else CARSPAN_PARAMS["smooth_for_display"]

    # --- Input validation --------------------------------------------------
    N = event_times_s.size
    if N < 4:
        raise ValueError(f"Need at least 4 R-peak events for CARSPAN PSD, got {N}.")

    T = float(event_times_s[-1] - event_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")

    # --- Frequency grid (native: fₖ = k/T) --------------------------------
    freqs = _native_frequency_grid(T, f_max)

    # --- Index-based window ------------------------------------------------
    # Handle special case: "tukey" shorthand → Tukey with α = 0.10
    if isinstance(window, str) and window.lower() == "tukey":
        window_spec = ("tukey", 0.10)
    else:
        window_spec = window

    w = _index_window(N, window_spec)

    # S₂ = sum of squared weights (window energy)
    S2 = float(np.sum(w**2))
    if S2 == 0:
        raise ValueError("Window sum-of-squares S₂ is zero — degenerate window.")

    # --- Direct Fourier Transform ------------------------------------------
    X_real, X_imag = _dft_event_series(event_times_s, w, freqs)

    # --- PSD with N/S₂ correction ------------------------------------------
    # S_xx = (2N / (T · S₂)) |X_w|²
    power = (2.0 * N / (T * S2)) * (X_real**2 + X_imag**2)

    # --- Optional bin-averaging for display --------------------------------
    if smooth and freqs.size > 0:
        native_delta_f = 1.0 / T
        if native_delta_f < display_resolution * 0.99:
            freqs, power = _bin_average_to_display_grid(
                freqs, power, display_resolution
            )

    return freqs, power


# ===================================================================
#  Confidence intervals
# ===================================================================


def compute_carspan_psd_strict_with_ci(
    event_times_s: np.ndarray,
    alpha_ci: float = 0.05,
    **kwargs,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Strict CARSPAN PSD with chi-squared confidence intervals.

    A single-segment DFT has ~2 degrees of freedom per frequency bin.

    Parameters
    ----------
    event_times_s : np.ndarray
        R-peak timestamps.
    alpha_ci : float
        Significance level for CI (default 0.05 → 95 % CI).
    **kwargs
        Forwarded to :func:`compute_carspan_psd_strict`.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
    """
    from scipy.stats import chi2

    freqs, power = compute_carspan_psd_strict(event_times_s, **kwargs)

    dof = 2  # Single-segment DFT
    chi2_lo = chi2.ppf(alpha_ci / 2, dof)
    chi2_hi = chi2.ppf(1 - alpha_ci / 2, dof)

    ci_lower = dof * power / chi2_hi
    ci_upper = dof * power / chi2_lo

    return freqs, power, ci_lower, ci_upper


def compute_carspan_psd_with_ci(
    event_times_s: np.ndarray,
    alpha_ci: float = 0.05,
    **kwargs,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Configurable CARSPAN PSD with chi-squared confidence intervals.

    Parameters
    ----------
    event_times_s : np.ndarray
        R-peak timestamps.
    alpha_ci : float
        Significance level for CI (default 0.05 → 95 % CI).
    **kwargs
        Forwarded to :func:`compute_carspan_psd`.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
    """
    from scipy.stats import chi2

    freqs, power = compute_carspan_psd(event_times_s, **kwargs)

    dof = 2
    chi2_lo = chi2.ppf(alpha_ci / 2, dof)
    chi2_hi = chi2.ppf(1 - alpha_ci / 2, dof)

    ci_lower = dof * power / chi2_hi
    ci_upper = dof * power / chi2_lo

    return freqs, power, ci_lower, ci_upper
