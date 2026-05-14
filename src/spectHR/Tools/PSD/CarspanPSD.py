"""
CarspanPSD.py – CARSPAN event-series spectral analysis.

Implements the DFT of an R-peak event series (unit impulses) as described
in Chapter 3 of the CARSPAN manual (Mulder et al.) and as found in the
original CARSPAN Pascal source ``T_AnaFunctions.pas`` (function ``SOC``).

The single entry point is :func:`compute_carspan_psd`. Every CARSPAN
quirk that ``carspan_strict`` needs (Pascal-faithful taper, amplitude
2/T, skip-first-event, asymmetric DC reference grid, …) is an
*individual* parameter on this function, so users can mix and match
them. :func:`compute_carspan_psd_strict` is a thin wrapper that picks
the manual-faithful preset.

Output units: **Hz** (events²/Hz). Conversion to mMI²/Hz is done by
the caller (CardioFrequencyMetricsMixin).

References
----------
L. J. M. Mulder, "CARSPAN Manual", Ch. 3.
CARSPAN Pascal source ``T_AnaFunctions.pas`` (function ``SOC`` —
"spectrum of counts").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

import numpy as np
from scipy.signal import get_window

from spectHR.Tools.PSD._psd_utils import (
    _chi2_ci,
    _require_min_samples,
    _resolve_window,
)


# ---------------------------------------------------------------------------
# Options dataclass
# ---------------------------------------------------------------------------


# Type aliases for the two presets each Literal kwarg admits.
Taper = Literal["scipy", "carspan_index"]
DcGrid = Literal["span_matched", "carspan_strict"]


@dataclass(frozen=True)
class CarspanOptions:
    """Configuration for :func:`compute_carspan_psd`.

    The defaults correspond to the variance-corrected *configurable*
    variant. Use :func:`compute_carspan_psd_strict` (or
    :func:`carspan_strict_options`) to obtain the manual-faithful preset.
    """

    # ----- Grid & smoothing -------------------------------------------------
    freq_resolution: float = 0.01
    """Hz — spacing of the display grid produced by bin-averaging."""

    smooth_for_display: bool = True
    """Bin-average + 3-point MA when True (CARSPAN's plot convention)."""

    f_max: float = 0.5
    """Upper frequency limit of the computed spectrum, in Hz."""

    # ----- Window -----------------------------------------------------------
    window: str = "hann"
    """scipy ``get_window`` name (only consulted when ``taper == "scipy"``)."""

    taper: Taper = "scipy"
    """Window builder: ``"scipy"`` for any scipy window, ``"carspan_index"``
    for the Pascal-faithful sin²((i+1)π/(2·N_taper)) cosine bell."""

    alpha_taper: float = 0.10
    """Cosine-bell width per side, used when ``taper == "carspan_index"``."""

    # ----- Amplitude / DFT --------------------------------------------------
    amplitude_correction: bool = True
    """True → variance-correct amplitude ``2N/(T·S₂)``; False → manual's ``2/T``."""

    skip_first_event: bool = False
    """Skip the first R-peak (CARSPAN's SOC loops over IBI indices ``0..N_IBI-1``)."""

    # ----- DC removal -------------------------------------------------------
    dc_removal: bool = False
    """Subtract the DFT of a regular-grid impulse train at the mean rate."""

    dc_grid: DcGrid = "span_matched"
    """Layout of the regular-grid reference times. ``"span_matched"`` =
    linspace(t₀, t_end, N). ``"carspan_strict"`` = ``t₀ + (i+1)·ΔT`` with
    ``ΔT = T/(N-1)``, exactly as the Pascal ``SOC`` lays out ``ExpT``."""

    # ----- Plot-unit hint ---------------------------------------------------
    plot_units: str = "mMI²/Hz"
    """Display unit hint for the caller — ``"mMI²/Hz"`` or ``"ms²/Hz"``."""


_DEFAULT_CARSPAN_OPTIONS = CarspanOptions()


def carspan_strict_options(
    *,
    smooth_for_display: bool = True,
    f_max: float = 0.5,
    plot_units: str = "mMI²/Hz",
) -> CarspanOptions:
    """Return the CARSPAN-faithful bundle as a :class:`CarspanOptions`.

    All values match the reference Pascal implementation. Only the few
    knobs the manual leaves to the caller (``smooth_for_display``,
    ``f_max``, ``plot_units``) are user-controllable; everything else is
    locked.
    """
    return CarspanOptions(
        freq_resolution=0.01,
        smooth_for_display=smooth_for_display,
        f_max=f_max,
        window="hann",                # ignored under taper="carspan_index"
        taper="carspan_index",
        alpha_taper=0.10,
        amplitude_correction=False,
        skip_first_event=True,
        dc_removal=True,
        dc_grid="carspan_strict",
        plot_units=plot_units,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_carspan_psd(
    event_times_s: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    options: Optional[CarspanOptions] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """CARSPAN PSD with chi-squared CI.

    Parameters
    ----------
    event_times_s : np.ndarray
        R-peak times in seconds, monotonically increasing.
    alpha_ci : float
        CI significance level (default 0.05 → 95 % CI).
    options : CarspanOptions, optional
        Bundle of CARSPAN tuning. Defaults to ``CarspanOptions()``
        (the variance-corrected configurable variant).

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds in Hz (events²/Hz).
    """
    opts = options if options is not None else _DEFAULT_CARSPAN_OPTIONS
    freqs, power, bin_counts = _compute(event_times_s, opts)
    ci_lower, ci_upper = _chi2_ci(power, 2 * bin_counts, alpha_ci)
    return freqs, power, ci_lower, ci_upper


def compute_carspan_psd_strict(
    event_times_s: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    smooth: bool = True,
    f_max: float = 0.5,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Manual-faithful CARSPAN PSD — thin wrapper around
    :func:`compute_carspan_psd` with the CARSPAN preset.

    Reproduces the reference Pascal ``SOC`` bit-for-bit:

    * Tukey 5 % cosine bell applied by event index (the Pascal ``Taper``
      formula — sample 0 carries a small non-zero weight, unlike
      scipy's tukey).
    * Amplitude ``2/T`` with no ``N/S₂`` correction (manual Eq. 3.19).
    * Skip-first-event convention from the Pascal SOC loop.
    * Regular-grid DC removal with the asymmetric reference grid
      ``ExpTᵢ = t₀ + (i+1)·ΔT``.

    The only knobs the manual leaves user-controllable are exposed
    here: ``alpha_ci``, ``smooth``, and ``f_max``.
    """
    return compute_carspan_psd(
        event_times_s,
        alpha_ci=alpha_ci,
        options=carspan_strict_options(
            smooth_for_display=smooth,
            f_max=f_max,
        ),
    )


# ---------------------------------------------------------------------------
# Core computation
#
# ``_compute`` is the single internal entry point. It reads as a
# sequence of named steps; each step delegates to a small helper below
# so the top-level reads as plain English.
# ---------------------------------------------------------------------------


def _compute(
    event_times_s: np.ndarray,
    opts: CarspanOptions,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shared CARSPAN PSD computation driven entirely by *opts*."""
    # 1. Sanity-check the input and pull the observation span.
    N = event_times_s.size
    T = _validate_input(event_times_s, N)

    # 2. Build the native-grid frequencies (Δf = 1/T) up to ``f_max``.
    freqs, delta_f = _native_grid(T=T, f_max=opts.f_max)

    # 3. Build the per-event window weights and the amplitude pre-factor.
    w, amplitude = _make_window(
        N=N,
        T=T,
        taper=opts.taper,
        window=opts.window,
        alpha_taper=opts.alpha_taper,
        amplitude_correction=opts.amplitude_correction,
    )

    # 4. Pick the actual event times that go into the DFT.
    actual_times = _actual_times(event_times_s, skip_first=opts.skip_first_event)

    # 5. Single windowed DFT of the actual event train.
    X_real, X_imag = _dft(freqs, actual_times, w)

    # 6. Optional DC-removal post-step: subtract the DFT of a regular-grid
    #    reference impulse train at the mean rate.
    if opts.dc_removal:
        exp_times = _dc_reference_times(
            event_times_s=event_times_s,
            n_actual=actual_times.size,
            grid=opts.dc_grid,
        )
        X_real, X_imag = _remove_dc(X_real, X_imag, freqs, exp_times, w)

    # 7. |X(f)|² × amplitude → raw periodogram on the native grid.
    power = amplitude * (X_real**2 + X_imag**2)

    # 8. Optionally bin-average to the display grid and apply the 3-MA
    #    smoother that CARSPAN uses on the plotted curve.
    return _apply_display_smoothing(
        freqs=freqs,
        power=power,
        delta_f=delta_f,
        display_resolution=float(opts.freq_resolution),
        do_smooth=opts.smooth_for_display,
    )


# ---------------------------------------------------------------------------
# Step helpers — each one does exactly the step it is named after.
# ---------------------------------------------------------------------------


def _validate_input(event_times_s: np.ndarray, N: int) -> float:
    """Sanity-check the event-times array and return the observation span ``T``.

    Raises if there are fewer than 4 events or if the time span is
    zero or negative.
    """
    _require_min_samples(N, 4, "CARSPAN PSD")
    T = float(event_times_s[-1] - event_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")
    return T


def _native_grid(*, T: float, f_max: float) -> Tuple[np.ndarray, float]:
    """Build the CARSPAN native frequency grid.

    The grid runs from ``Δf = 1/T`` to ``k_max · Δf`` with
    ``k_max = floor(f_max / Δf)``. The DC bin (k = 0) is excluded —
    it carries no HRV information.
    """
    delta_f = 1.0 / T
    k_max = int(np.floor(f_max / delta_f))
    freqs = np.arange(1, k_max + 1) * delta_f
    return freqs, delta_f


def _make_window(
    *,
    N: int,
    T: float,
    taper: Taper,
    window: str,
    alpha_taper: float,
    amplitude_correction: bool,
) -> Tuple[np.ndarray, float]:
    """Build per-event window weights and the DFT amplitude pre-factor.

    Two taper presets:

    * ``"carspan_index"`` — bit-for-bit equivalent of CARSPAN's Pascal
      ``Taper`` (``T_AnaFunctions.pas:128-161``): a
      ``sin²(π·(i+1)/(2·N_taper))`` cosine bell applied by *event index*,
      with the (i+1) offset that gives the first sample a small but
      *non-zero* weight (unlike scipy's tukey, which zeros it). The
      taper acts on ``N − 1`` events because CARSPAN's ``SOC`` loops
      over IBI indices ``0..N_IBI-1``.

    * ``"scipy"`` — any ``scipy.signal.get_window`` name. ``"tukey"``
      without parameters defaults to α = 0.10 to stay close to CARSPAN.

    Amplitude:

    * ``amplitude_correction = False`` → ``2 / T`` (manual Eq. 3.19).
    * ``amplitude_correction = True``  → ``2N / (T · S₂)`` with
      ``S₂ = Σ wᵢ²``; level stays approximately consistent across
      window choices.
    """
    if taper == "carspan_index":
        n_taper_pct = max(1, int(round((alpha_taper * 50.0) * (N - 1) / 100.0)))
        w = _carspan_taper(N - 1, n_taper_pct)
    else:
        ws = _resolve_window(window)
        if isinstance(ws, str) and ws.lower() == "tukey":
            ws = ("tukey", alpha_taper)
        w = get_window(ws, N, fftbins=False).astype(np.float64)

    if amplitude_correction:
        S2 = float(np.sum(w**2))
        if S2 == 0:
            raise ValueError("Window sum-of-squares S₂ is zero — degenerate window.")
        amplitude = 2.0 * w.size / (T * S2)
    else:
        amplitude = 2.0 / T

    return w, amplitude


def _actual_times(event_times_s: np.ndarray, *, skip_first: bool) -> np.ndarray:
    """Pick the array of actual event times that goes into the DFT.

    CARSPAN's ``SOC`` (``T_AnaFunctions.pas:297-414``) loops over
    ``IBI = 0..N_IBI-1`` — i.e. R-peaks 1..N_R-1, skipping the first
    R-peak at t = 0. With ``skip_first=True`` this convention is mirrored;
    otherwise all events participate.
    """
    if skip_first:
        return event_times_s[1:].astype(np.float64)
    return event_times_s.astype(np.float64)


def _dc_reference_times(
    *,
    event_times_s: np.ndarray,
    n_actual: int,
    grid: DcGrid,
) -> np.ndarray:
    """Build the regular-grid reference times subtracted in DC removal.

    Two grid layouts:

    * ``"carspan_strict"`` — Pascal-faithful asymmetric grid.
      ``ExpTᵢ = t₀ + (i+1)·ΔT`` for ``i = 0..N_IBI-1`` with
      ``ΔT = T/(N_IBI − 1)``. The last expected time lands slightly
      past ``t_end`` by design.

    * ``"span_matched"`` — symmetric ``linspace(t₀, t_end, N)``. Easier
      to reason about and zeros the boundary phase difference at f = 0.
    """
    t0 = float(event_times_s[0])
    t_end = float(event_times_s[-1])
    if grid == "carspan_strict":
        delta_T = (
            (t_end - t0) / float(n_actual - 1) if n_actual > 1 else (t_end - t0)
        )
        return t0 + (np.arange(n_actual, dtype=np.float64) + 1) * float(delta_T)
    return np.linspace(t0, t_end, n_actual)


def _dft(
    freqs: np.ndarray, times: np.ndarray, w: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Windowed DFT of an impulse train: ``X(f) = Σ wᵢ · exp(-2πj f tᵢ)``.

    Returns the real and imaginary parts as separate arrays (slightly
    faster than complex multiplies, and clearer when ``_remove_dc``
    later subtracts a second DFT component-wise).
    """
    phase = 2.0 * np.pi * np.outer(freqs, times)
    X_real = np.dot(np.cos(phase), w)
    X_imag = np.dot(-np.sin(phase), w)
    return X_real, X_imag


def _remove_dc(
    X_real: np.ndarray,
    X_imag: np.ndarray,
    freqs: np.ndarray,
    exp_times: np.ndarray,
    w: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """CARSPAN-style DC removal: subtract the DFT of a regular-grid
    impulse train.

    Given an already-computed DFT ``X(f)`` of the actual event train,
    this computes the DFT of a perfectly periodic impulse train at the
    mean rate (using the same window ``w``) and returns
    ``X(f) − X_ref(f)`` component-wise. At ``f = 0`` both phasors equal
    ``1``, so their difference is zero — the DC component is removed
    exactly. Beyond DC, the subtraction also drains the spectral leakage
    that the mean-rate impulse train would otherwise contribute to the
    VLF / LF region.
    """
    X_ref_real, X_ref_imag = _dft(freqs, exp_times, w)
    return X_real - X_ref_real, X_imag - X_ref_imag


def _apply_display_smoothing(
    *,
    freqs: np.ndarray,
    power: np.ndarray,
    delta_f: float,
    display_resolution: float,
    do_smooth: bool,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bin-average to the display grid and run the CARSPAN 3-point MA.

    1. **Bin-averaging.** When the native grid is finer than the display
       grid (``Δf < display_resolution`` ≈ 0.99×), neighbouring native
       bins are averaged into display bins. This raises the chi-squared
       dof per bin from 2 (single DFT) to ``2 × bin_counts``.

    2. **3-point moving average.** CARSPAN manual sec. 3.2, p. 33::

           "a moving average window over three frequency points
            (0.03 Hz bandwidth) is applied before plotting the
            spectral functions"

       Plot-only smoothing; the kernel is mean-preserving, so the area
       under the curve is preserved and peaks visually drop ≈ 3× to
       match CARSPAN's display.
    """
    if do_smooth and freqs.size > 0 and delta_f < display_resolution * 0.99:
        freqs, power, bin_counts = _bin_average(freqs, power, display_resolution)
    else:
        bin_counts = np.ones(freqs.size, dtype=int)

    if do_smooth and power.size >= 3:
        kernel = np.ones(3, dtype=np.float64) / 3.0
        power = np.convolve(power, kernel, mode="same")

    return freqs, power, bin_counts


# ---------------------------------------------------------------------------
# Window-builder + bin-averager
# ---------------------------------------------------------------------------


def _carspan_taper(length: int, n_taper: int) -> np.ndarray:
    """CARSPAN-style cosine-bell taper, applied to a unit array.

    Mirrors ``T_AnaFunctions.pas:128-161`` (procedure ``Taper``). The
    (LeftSmp) offset in the cosine argument — *not* (LeftSmp − 1) —
    means sample 0 receives weight ``sin²(π / (2·N_taper))`` rather
    than 0. scipy's tukey zeros the first sample, so we cannot use it
    for bit-for-bit parity.
    """
    w = np.ones(length, dtype=np.float64)
    if length < 2 or n_taper < 1:
        return w
    n_taper = min(n_taper, length // 2)
    fac = np.pi / (2.0 * n_taper)
    for left_smp in range(1, n_taper + 1):
        right_smp = length - left_smp
        f_arg = left_smp * fac
        # Pascal: if LeftSmp <> NrOfTaperSmp then FCos := cos(FArg) else FCos := 0
        f_cos = 0.0 if left_smp == n_taper else np.cos(f_arg)
        f_mult = 1.0 - f_cos * f_cos
        w[left_smp - 1] *= f_mult
        w[right_smp] *= f_mult
    return w


def _bin_average(native_freqs, native_power, display_resolution):
    """Bin-average the native grid onto a display grid starting at 2 × resolution.

    Returns ``(display_freqs, display_power, bin_counts)``. Effective dof
    per display bin is ``2 × bin_counts`` — averaging k native bins
    raises the chi-squared dof from 2 (single DFT) to 2k.

    The first display bin is centred at 2·Δ (e.g. 0.020 Hz for
    Δ = 0.01 Hz), so native bins below 1.5·Δ (near-DC, high 1/f power)
    are excluded.
    """
    f_max = native_freqs[-1]
    first_edge = 1.5 * display_resolution
    bin_edges = np.arange(first_edge, f_max + display_resolution, display_resolution)

    out_freqs, out_power, counts = [], [], []
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (native_freqs >= lo) & (native_freqs <= hi)
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
