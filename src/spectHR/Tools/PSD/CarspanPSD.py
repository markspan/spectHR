"""
CarspanPSD.py – CARSPAN spectral analysis for HRV.

The module exposes a single :func:`compute_carspan_psd` function whose
behaviour is fully driven by :class:`CarspanOptions`. The ``signal``
field of that dataclass picks between the two algorithm variants from
Mulder's "CARSPAN Manual" (Ch. 3) / the Pascal source
``T_AnaFunctions.pas`` (``SOC``):

* ``signal="events"`` (default) — **unit-impulse SOC**, manual Eq. 3.19,
  Pascal ``IsRPDataCol=True``. Treats the R-peak series as a train of
  unit impulses ``Σ δ(t − tᵢ)`` and computes
  ``(2/T)·|Σ wᵢ exp(−i 2π f tᵢ)|²``. Window, amplitude correction,
  reference-grid DC removal, skip-first-event are all individually
  configurable. Returns ``events²/Hz``; the mixin layer multiplies by
  ``mean_ms²`` to reach mMI²/Hz.

* ``signal="ibi_amplitude"`` — **manual-faithful IBI-amplitude DFT**,
  manual Eq. 3.21, Pascal ``IsRPDataCol=False``. Computes
  ``(2/T)·|Σ tᵢ · xᵢ · exp(−i 2π f Tᵢ)|²`` where ``xᵢ`` is the
  arithmetic-mean-subtracted IBI in ms and ``tᵢ`` the local IBI
  duration in seconds. DC removal is done at the signal level by the
  mean subtraction — there is no reference-grid subtraction. Returns
  ``ms²/Hz``; the mixin layer multiplies by ``10⁶ / mean_ms²`` to
  reach mMI²/Hz (Eq. 3.20 + milli²). Reproduces the CARSPAN manual to
  within ~2 % on every band (epoch #2 of ``example1.EVT``,
  manual p. 121).

The convenience helper :func:`carspan_strict_options` builds the
:class:`CarspanOptions` bundle for the manual-faithful preset
(``signal="ibi_amplitude"`` + Pascal 5 % index taper +
``smooth_for_display=True``), and the thin wrapper
:func:`compute_carspan_psd_strict` is the same as
``compute_carspan_psd(options=carspan_strict_options(...))`` plus a
rename of the ``method`` field on the returned :class:`PSDResult` to
``"carspan_strict"`` so downstream code can tell the two apart.

The display-grid resample :func:`_bin_average` is a faithful port of
Pascal's ``Resample_R`` (fractional-coverage weighted mean with
exclusive upper boundary) and is shared by both signal variants.
It runs unconditionally inside :func:`_compute` whenever the native
grid is finer than ``freq_resolution`` (mirroring Pascal's ``Resample``
before ``Calculate_Power``); the ``smooth_for_display`` flag controls
only the additional 3-point MA used for plotting.

References
----------
L. J. M. Mulder, "CARSPAN Manual", Ch. 3, Eq. 3.19, 3.20, 3.21.
CARSPAN Pascal source ``T_AnaFunctions.pas`` — function ``SOC``
(both branches), ``Taper``, ``AutoSpectrum``, ``Resample_R``,
``Calculate_Power``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

import numpy as np
from scipy.signal import get_window

from spectHR.Tools.PSD._psd_utils import (
    PSDResult,
    _chi2_ci,
    _require_min_samples,
    _resolve_window,
)


# ---------------------------------------------------------------------------
# Options dataclass
# ---------------------------------------------------------------------------


# Type aliases for the Literal kwargs.
Signal = Literal["events", "ibi_amplitude"]
Taper = Literal["scipy", "carspan_index"]
DcGrid = Literal["span_matched", "carspan_strict"]


@dataclass(frozen=True)
class CarspanOptions:
    """Configuration for :func:`compute_carspan_psd`.

    The same :class:`CarspanOptions` drives both CARSPAN variants — the
    ``signal`` field picks between them:

    * ``signal="events"`` (default) — manual Eq. 3.19, Pascal
      ``IsRPDataCol=True``. The DFT runs on a windowed unit-impulse
      train. The remaining knobs (``window``, ``taper``, ``alpha_taper``,
      ``amplitude_correction``, ``skip_first_event``, ``dc_removal``,
      ``dc_grid``) all apply.
    * ``signal="ibi_amplitude"`` — manual Eq. 3.21, Pascal
      ``IsRPDataCol=False``. The DFT runs on mean-subtracted IBI
      amplitudes weighted by their local interval (Pascal's
      ``Amp := NData[i] * IData[i]/1000``). DC is removed by the mean
      subtraction; the ``dc_removal``, ``dc_grid``,
      ``amplitude_correction``, and ``skip_first_event`` knobs are
      **ignored** in this branch (the manual specifies fixed choices
      for them). The window/taper choice still applies.

    :func:`carspan_strict_options` is the convenience preset that picks
    ``signal="ibi_amplitude"`` with Pascal's 5 % index taper —
    reproducing the CARSPAN manual to within ~2 % on every band.
    """

    # ----- Algorithm variant ------------------------------------------------
    signal: Signal = "events"
    """Which signal goes into the DFT — see class docstring."""

    # ----- Grid & smoothing -------------------------------------------------
    freq_resolution: float = 0.01
    """Hz — spacing of the display grid produced by bin-averaging."""

    smooth_for_display: bool = True
    """Apply the CARSPAN 3-point MA on the display grid when True.
    Bin-averaging to the display grid is always on (mirrors Pascal's
    ``Resample`` always running before ``Calculate_Power``)."""

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

    # ----- Amplitude / DFT (events branch only) -----------------------------
    amplitude_correction: bool = True
    """True → variance-correct amplitude ``2N/(T·S₂)``; False → manual's
    ``2/T``. Ignored when ``signal == "ibi_amplitude"``."""

    skip_first_event: bool = False
    """Skip the first R-peak (CARSPAN's SOC loops over IBI indices
    ``0..N_IBI-1``). Ignored when ``signal == "ibi_amplitude"``."""

    # ----- DC removal (events branch only) ----------------------------------
    dc_removal: bool = False
    """Subtract the DFT of a regular-grid impulse train at the mean rate.
    Ignored when ``signal == "ibi_amplitude"`` (mean subtraction does
    the DC removal at the signal level there)."""

    dc_grid: DcGrid = "span_matched"
    """Layout of the regular-grid reference times. ``"span_matched"`` =
    linspace(t₀, t_end, N). ``"carspan_strict"`` = ``t₀ + (i+1)·ΔT`` with
    ``ΔT = T/(N-1)``, exactly as the Pascal ``SOC`` lays out ``ExpT``.
    Ignored when ``signal == "ibi_amplitude"``."""

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
    """Manual-faithful CARSPAN preset — a :class:`CarspanOptions` bundle
    that drives :func:`compute_carspan_psd` along the IBI-amplitude DFT
    path (manual Eq. 3.21, Pascal ``SOC`` branch ``IsRPDataCol=False``).

    Passing this bundle to :func:`compute_carspan_psd` reproduces the
    CARSPAN manual's reference values (epoch #2 of ``example1.EVT``
    matches the manual to within ~2 % on every band). The thin
    convenience wrapper :func:`compute_carspan_psd_strict` just calls
    ``compute_carspan_psd(options=carspan_strict_options(...))``.

    The bundle locks every choice the manual leaves implicit. Only the
    knobs the manual exposes are kept user-controllable:

    * ``smooth_for_display`` — 3-point MA on the display grid (plot only).
    * ``f_max`` — upper frequency limit of the native grid.
    * ``plot_units`` — display unit hint passed downstream.
    """
    return CarspanOptions(
        signal="ibi_amplitude",
        freq_resolution=0.01,
        smooth_for_display=smooth_for_display,
        f_max=f_max,
        window="hann",                # ignored under taper="carspan_index"
        taper="carspan_index",
        alpha_taper=0.10,
        # The fields below are ignored by the ibi_amplitude branch but
        # kept consistent with the Pascal IsRPDataCol=True bundle in
        # case a caller flips signal back to "events" for comparison.
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
) -> PSDResult:
    """Configurable CARSPAN PSD (unit-impulse SOC, manual Eq. 3.19).

    Models the R-peak sequence as a unit-impulse train and computes
    ``(2/T)·|Σ wᵢ exp(−i 2π f tᵢ)|²``, optionally with a reference-grid
    DC subtraction (CARSPAN's spectral-leakage cleanup at low f).
    All algorithmic knobs are exposed on :class:`CarspanOptions`.

    For the IBI-amplitude DFT (manual Eq. 3.21) that reproduces the
    CARSPAN manual's reference numbers, see
    :func:`compute_carspan_psd_strict`.

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
    PSDResult
        ``power`` in raw events²/Hz (``unit="Hz"``). The mixin layer
        applies the mMI² (or ms²) conversion via ``_carspan_display``.
    """
    opts = options if options is not None else _DEFAULT_CARSPAN_OPTIONS
    freqs, power, bin_counts = _compute(event_times_s, opts)
    ci_lower, ci_upper = _chi2_ci(power, 2 * bin_counts, alpha_ci)
    # Unit follows the algorithm variant: the unit-impulse SOC is
    # natively in events²/Hz, the IBI-amplitude DFT in ms²/Hz.
    raw_unit = "ms²/Hz" if opts.signal == "ibi_amplitude" else "Hz"
    return PSDResult(
        freqs=freqs,
        power=power,
        unit=raw_unit,
        method="carspan",
        ci_lower=ci_lower,
        ci_upper=ci_upper,
    )


def compute_carspan_psd_strict(
    event_times_s: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    smooth: bool = True,
    f_max: float = 0.5,
) -> PSDResult:
    """Manual-faithful CARSPAN PSD — thin wrapper around
    :func:`compute_carspan_psd` with the :func:`carspan_strict_options`
    preset.

    This is equivalent to::

        compute_carspan_psd(
            event_times_s,
            alpha_ci=alpha_ci,
            options=carspan_strict_options(
                smooth_for_display=smooth, f_max=f_max,
            ),
        )

    plus a rename of the ``method`` field on the returned :class:`PSDResult`
    from ``"carspan"`` to ``"carspan_strict"`` so downstream code can tell
    the two apart. The actual algorithm — IBI-amplitude DFT (manual
    Eq. 3.21, Pascal ``SOC`` branch ``IsRPDataCol=False``) — runs inside
    :func:`compute_carspan_psd` via the ``signal="ibi_amplitude"`` field
    of :class:`CarspanOptions`. See :func:`carspan_strict_options` for
    the full preset.

    Parameters
    ----------
    event_times_s : np.ndarray
        R-peak times in seconds, monotonically increasing.
    alpha_ci : float
        Confidence-interval significance level (default 0.05 → 95 % CI).
    smooth : bool
        If True, apply the CARSPAN 3-point MA smoother to the resampled
        display grid (plot-only; integration runs on the unsmoothed
        spectrum independently).
    f_max : float
        Upper frequency limit of the native grid (default 0.5 Hz).

    Returns
    -------
    PSDResult
        ``power`` in raw ms²/Hz on the resampled display grid. The
        mixin's ``_carspan_display`` applies the mMI²/Hz conversion.
    """
    from dataclasses import replace as _replace
    raw = compute_carspan_psd(
        event_times_s,
        alpha_ci=alpha_ci,
        options=carspan_strict_options(
            smooth_for_display=smooth, f_max=f_max,
        ),
    )
    return _replace(raw, method="carspan_strict")


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
    """Shared CARSPAN PSD computation driven entirely by *opts*.

    Dispatches on ``opts.signal``:

    * ``"events"`` — unit-impulse SOC (Eq. 3.19).
    * ``"ibi_amplitude"`` — IBI-amplitude DFT (Eq. 3.21).

    Both branches return ``(freqs, power, bin_counts)`` after the
    Pascal-faithful Resample to the display grid and the optional
    3-point MA. Bin-averaging always runs when the native grid is
    finer than ``freq_resolution``; the ``smooth_for_display`` flag
    controls only the 3-MA.
    """
    # 1. Sanity-check the input and pull the observation span.
    T = _validate_input(event_times_s, event_times_s.size)

    # 2. Build the native-grid frequencies (Δf = 1/T) up to ``f_max``.
    freqs, delta_f = _native_grid(T=T, f_max=opts.f_max)

    # 3. Dispatch on the signal variant.
    if opts.signal == "ibi_amplitude":
        power = _ibi_amplitude_periodogram(event_times_s, freqs, T, opts)
    else:
        power = _events_periodogram(event_times_s, freqs, T, opts)

    # 4. Bin-average to the display grid (always) and optionally apply
    #    the 3-MA. Pascal applies ``Resample`` before ``Calculate_Power``
    #    unconditionally; the plot-only smoothing is opt-in.
    return _apply_display_smoothing(
        freqs=freqs,
        power=power,
        delta_f=delta_f,
        display_resolution=float(opts.freq_resolution),
        do_smooth=opts.smooth_for_display,
    )


def _events_periodogram(
    event_times_s: np.ndarray,
    freqs: np.ndarray,
    T: float,
    opts: CarspanOptions,
) -> np.ndarray:
    """Unit-impulse SOC periodogram (manual Eq. 3.19, Pascal
    ``IsRPDataCol=True``).

    ``X(f) = Σ wᵢ · exp(−i 2π f tᵢ)``, optionally minus the DFT of a
    regular-grid reference train at the mean rate. Returns
    ``amplitude · |X|²`` on the native grid.
    """
    actual_times = _actual_times(event_times_s, skip_first=opts.skip_first_event)
    n_signal = actual_times.size

    w, amplitude = _make_window(
        n_signal=n_signal,
        T=T,
        taper=opts.taper,
        window=opts.window,
        alpha_taper=opts.alpha_taper,
        amplitude_correction=opts.amplitude_correction,
    )

    X_real, X_imag = _dft(freqs, actual_times, w)

    if opts.dc_removal:
        exp_times = _dc_reference_times(
            event_times_s=event_times_s,
            n_actual=actual_times.size,
            grid=opts.dc_grid,
        )
        X_real, X_imag = _remove_dc(X_real, X_imag, freqs, exp_times, w)

    return amplitude * (X_real ** 2 + X_imag ** 2)


def _ibi_amplitude_periodogram(
    event_times_s: np.ndarray,
    freqs: np.ndarray,
    T: float,
    opts: CarspanOptions,
) -> np.ndarray:
    """IBI-amplitude periodogram (manual Eq. 3.21, Pascal
    ``IsRPDataCol=False``).

    Reproduces the Pascal ``SOC`` branch for IBI input bit-for-bit:

    * ``NData[i] = IBIᵢ_ms`` (mean-subtracted with arithmetic mean).
    * Tapered with the chosen window (``opts.taper``, ``opts.window``,
      ``opts.alpha_taper``). The Pascal default ``TaperPercent := 5``
      corresponds to ``taper="carspan_index"`` + ``alpha_taper=0.10``.
    * ``Amp[i] = NData_tapered[i] · IBIᵢ_s`` (Pascal's
      ``Amp := NData[i] * IData[i]/1000``).
    * DFT at ``Tᵢ = Σⱼ≤ᵢ IBIⱼ`` (Pascal's ``T`` accumulates ``IData``
      from 0).
    * Spectrum = ``(2/T) · |X|²`` — native ms²/Hz.

    The ``amplitude_correction``, ``skip_first_event``, ``dc_removal``,
    and ``dc_grid`` options are ignored on this branch (the manual
    specifies fixed choices; the mean subtraction does the DC removal
    at the signal level).
    """
    ibi_s = np.diff(event_times_s)
    ibi_ms = ibi_s * 1000.0
    n_signal = ibi_ms.size
    if n_signal < 4:
        raise ValueError("CARSPAN ibi_amplitude PSD needs ≥4 IBIs.")

    mean_ms = float(np.mean(ibi_ms))
    nd = ibi_ms - mean_ms     # arithmetic mean-subtraction → DC removed

    w, _ = _make_window(
        n_signal=n_signal,
        T=T,
        taper=opts.taper,
        window=opts.window,
        alpha_taper=opts.alpha_taper,
        amplitude_correction=False,    # not applicable; manual Eq. 3.21 uses 2/T flat
    )
    nd_tapered = nd * w

    # Pascal: Amp := NData[i] * IData[i]/1000 → (ms · ms/1000) = (ms · s).
    amp = nd_tapered * ibi_s
    # Pascal: T accumulates IData from 0 inside SOC's main loop.
    event_times_relative = np.cumsum(ibi_s)

    X_real, X_imag = _dft(freqs, event_times_relative, amp)

    # Eq. 3.21: (2/T) · |X|². Native ms²/Hz.
    return 2.0 * (X_real ** 2 + X_imag ** 2) / T


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
    n_signal: int,
    T: float,
    taper: Taper,
    window: str,
    alpha_taper: float,
    amplitude_correction: bool,
) -> Tuple[np.ndarray, float]:
    """Build per-event window weights and the DFT amplitude pre-factor.

    ``n_signal`` is the **length of the impulse train going into the
    DFT** — that is, ``actual_times.size`` from :func:`_actual_times`.
    It may be ``N`` (full event count) or ``N − 1`` (skip-first
    convention). Sizing the window to ``n_signal`` keeps the
    ``np.dot`` in :func:`_dft` shape-correct regardless of which
    skip-first / taper combination the user picks.

    Two taper presets:

    * ``"carspan_index"`` — bit-for-bit equivalent of CARSPAN's Pascal
      ``Taper`` (``T_AnaFunctions.pas:128-161``): a
      ``sin²(π·(i+1)/(2·N_taper))`` cosine bell applied by *event index*,
      with the (i+1) offset that gives the first sample a small but
      *non-zero* weight (unlike scipy's tukey, which zeros it). The
      Pascal source pairs this with ``skip_first=True`` so the window
      acts on the ``N − 1`` IBI-indexed events.

    * ``"scipy"`` — any ``scipy.signal.get_window`` name. ``"tukey"``
      without parameters defaults to α = 0.10 to stay close to CARSPAN.

    Amplitude:

    * ``amplitude_correction = False`` → ``2 / T`` (manual Eq. 3.19).
    * ``amplitude_correction = True``  → ``2 · n_signal / (T · S₂)``
      with ``S₂ = Σ wᵢ²``; level stays approximately consistent across
      window choices.
    """
    if taper == "carspan_index":
        n_taper_pct = max(1, int(round((alpha_taper * 50.0) * n_signal / 100.0)))
        w = _carspan_taper(n_signal, n_taper_pct)
    else:
        ws = _resolve_window(window)
        if isinstance(ws, str) and ws.lower() == "tukey":
            ws = ("tukey", alpha_taper)
        w = get_window(ws, n_signal, fftbins=False).astype(np.float64)

    if amplitude_correction:
        S2 = float(np.sum(w**2))
        if S2 == 0:
            raise ValueError("Window sum-of-squares S₂ is zero — degenerate window.")
        amplitude = 2.0 * n_signal / (T * S2)
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
    """Bin-average to the display grid and optionally run the 3-point MA.

    1. **Bin-averaging — always on.** When the native grid is finer than
       the display grid (``Δf < display_resolution`` × 0.99), neighbouring
       native bins are averaged into display bins by Pascal's
       fractional-coverage rule (see :func:`_bin_average`). This
       reproduces Pascal's ``Resample`` step, which runs
       unconditionally before ``Calculate_Power`` reads ``PDSin_BCK``.
       The chi-squared dof per display bin scales as ``2 × bin_counts``.

    2. **3-point moving average — opt-in via ``do_smooth``.** From the
       CARSPAN manual (§3.2, p. 33):

           "a moving average window over three frequency points
            (0.03 Hz bandwidth) is applied before plotting the
            spectral functions"

       Plot-only smoothing; the kernel is mean-preserving, so the area
       under the curve is preserved and peaks visually drop ≈ 3× to
       match CARSPAN's display.
    """
    if freqs.size > 0 and delta_f < display_resolution * 0.99:
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
    """Resample a native-grid spectrum onto the CARSPAN display grid.

    Faithful port of Pascal's ``Resample_R`` (``T_AnaFunctions.pas:171-239``).
    Each display bin is the fractional-coverage-weighted average of the
    native bins that intersect its frequency window ``[FRQCEN − Δ/2,
    FRQCEN + Δ/2)``:

    * The native bin just below the lower edge contributes weight
      ``(freq_next − FRQLOW) / native_df`` (otherwise 1).
    * Interior native bins contribute weight 1 each.
    * The native bin straddling the upper edge contributes weight
      ``(FRQHIG − freq_prev) / native_df`` (otherwise 1).
    * The native bin AT the upper edge (``FRQARR[ILAST]``) is **never**
      summed — only ``FRQARR[ILAST-1]`` is, with weight FFACH. This is
      what makes the algorithm energy-preserving across adjacent display
      bins.

    The display grid is ``IFRQ · Δ`` for ``IFRQ = 1..MAXPNT`` with
    ``MAXPNT = floor(N_native · native_df / Δ)``, exactly as Pascal lays
    it out — so the first display bin is centred at ``Δ`` (e.g. 0.01 Hz
    for Δ = 0.01 Hz).

    Returns ``(display_freqs, display_power, bin_counts)``. ``bin_counts``
    is an effective count for chi-squared dof scaling (interior + 1 for
    each non-zero fractional edge).
    """
    native_freqs = np.asarray(native_freqs, dtype=np.float64)
    native_power = np.asarray(native_power, dtype=np.float64)

    if native_freqs.size == 0:
        return (np.array([]), np.array([]), np.array([], dtype=int))

    # The native grid is freq[k] = (k+1)·native_df. Recover native_df
    # from the first sample (Pascal builds an explicit FRQARR list; we
    # don't need to).
    native_df = float(native_freqs[0])
    n_native = native_freqs.size

    max_pnt = int(np.floor(n_native * native_df / display_resolution))
    if max_pnt < 1:
        return (np.array([]), np.array([]), np.array([], dtype=int))

    isave = 0
    out_freqs: list[float] = []
    out_power: list[float] = []
    counts: list[int] = []

    first_freq = float(native_freqs[0])

    for ifrq in range(1, max_pnt + 1):
        frq_cen = ifrq * display_resolution
        frq_low = frq_cen - display_resolution / 2.0
        frq_high = frq_cen + display_resolution / 2.0
        if frq_cen < first_freq:
            continue

        # Advance ISAVE to the first native bin whose freq >= FRQLOW.
        while isave < n_native and native_freqs[isave] < frq_low:
            isave += 1
        i_first = max(1, isave - 1)
        # Advance ISAVE to the first native bin whose freq >= FRQHIG
        # (and stay within the valid-index range).
        while (
            isave < n_native - 1
            and native_freqs[isave] < frq_high
        ):
            isave += 1
        i_last = min(isave, n_native - 1)

        if native_freqs[i_first] < frq_low:
            ffac_l = (native_freqs[i_first + 1] - frq_low) / native_df
        else:
            ffac_l = 1.0

        if native_freqs[i_last] > frq_high:
            ffac_h = (frq_high - native_freqs[i_last - 1]) / native_df
        else:
            ffac_h = 1.0

        sumy = ffac_l * native_power[i_first]
        sumx = ffac_l

        # Pascal: for index := IFIRST+1 to ILAST-2 do (inclusive both ends).
        for idx in range(i_first + 1, i_last - 1):
            sumy += native_power[idx]
            sumx += 1.0

        sumy += ffac_h * native_power[i_last - 1]
        sumx += ffac_h

        # Effective bin count: interior count + 1 for each non-zero
        # fractional edge. Used as a chi-squared dof scale by the CI
        # path; the actual statistical weight is the FFACL / FFACH
        # fraction, but counting the edge bins as "one each" is a
        # conservative-but-defensible approximation.
        interior = max(0, (i_last - 1) - (i_first + 1) + 1)
        eff_count = interior + int(ffac_l > 0) + int(ffac_h > 0)
        eff_count = max(1, eff_count)

        # Round to the resolution multiple to avoid float accumulation.
        center = round(frq_cen / display_resolution) * display_resolution
        out_freqs.append(center)
        out_power.append(sumy / sumx if sumx != 0 else 0.0)
        counts.append(int(eff_count))

    return (
        np.array(out_freqs, dtype=np.float64),
        np.array(out_power, dtype=np.float64),
        np.array(counts, dtype=int),
    )
