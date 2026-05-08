"""
CarspanPSD.py – CARSPAN event-series spectral analysis.

Implements the DFT of an R-peak event series (unit impulses) as described
in Chapter 3 of the CARSPAN manual (Mulder et al.) and as found in the
original CARSPAN Pascal source ``T_AnaFunctions.pas`` (function ``SOC``).

Two variants are exposed:

* **strict** — manual-faithful Eq. 3.19 with two CARSPAN-specific quirks
  that the original Pascal applies but the formula in the manual does
  not state explicitly:

    1. **Regular-grid DC removal.** The DFT is taken not of the bare
       event train but of the *difference* between the actual event
       train and a perfectly periodic event train at the mean rate.
       At each event index ``i`` CARSPAN subtracts a phasor at
       ``ExpTᵢ = (i+1)·ΔT`` (with ``ΔT`` the mean IBI) from the phasor
       at the actual event time ``Tᵢ``::

           X(fₖ) = Σᵢ wᵢ · [exp(-2πj fₖ Tᵢ) - exp(-2πj fₖ ExpTᵢ)]

       At ``f = 0`` both phasors are ``1`` so their difference is zero,
       i.e. the DC component is removed exactly. This is also what
       drains the spurious low-frequency leakage that an un-detrended
       impulse train would show in the VLF/LF region.

    2. **Index-based tapering.** The Tukey 5 % cosine taper is applied
       per event index (``Taper(NData, TaperPercent)`` in the Pascal),
       not by clock fraction. For approximately periodic rhythms the
       two are nearly identical, but for irregular rhythms the
       index-based form is what the reference implementation uses.

       Amplitude factor: ``2/T`` with no ``N/S₂`` correction.

* **configurable** — variance-corrected variant intended for general
  use. Any scipy window name is accepted, the amplitude carries the
  standard ``2N/(T·S₂)`` correction so the level is approximately
  window-invariant. Regular-grid DC removal is **opt-in** via the
  workspace key ``FrequencyAnalysis.carspan.dc_removal`` (default
  False to preserve historical behaviour); when enabled, configurable
  mode uses the same DC-removal subtraction as strict mode.

Native grid Δf = 1/T, optionally bin-averaged onto a 0.01 Hz display grid.
Output units: **Hz** (events²/Hz). Conversion to mMI²/Hz is done by the
caller (CardioFrequencyMetricsMixin).

References
----------
L. J. M. Mulder, "CARSPAN Manual", Ch. 3.
CARSPAN Pascal source ``T_AnaFunctions.pas`` (function ``SOC``).
"""

from __future__ import annotations

import math
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
    "freq_resolution": 0.01,  # Hz — display grid spacing
    "window": "hann",  # Default window for configurable mode
    "smooth_for_display": True,  # Bin-average to the display grid
    "plot_units": "mMI²/Hz",  # "mMI²/Hz" or "ms²/Hz" (IBI signal)
    "dc_removal": False,# (Strict mode always applies DC removal regardless of this flag.)
    # "Match Edges" — when True, band-power integration rounds the
    # band edges (low / high) to the nearest multiple of
    # ``freq_resolution`` before masking, reproducing CARSPAN's
    # ``GetMinBandFreq`` / ``GetMaxBandFreq`` behaviour. Off by default
    # so user-chosen edges are honoured at full float precision.
    "match_edges": False,
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
    dc_removal: Optional[bool] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Configurable CARSPAN PSD with chi-squared CI.

    The window is applied by **event index** (scipy-style) and the power
    is N/S₂-corrected.  Any scipy-compatible window name is accepted
    (including the "X% cosine bell" convention).

    Parameters
    ----------
    dc_removal : bool, optional
        If True, subtract the DFT of a regular-grid impulse train at the
        mean rate before squaring — same DC / mean-rate leakage removal
        the strict mode performs unconditionally. If None (default), the
        flag is read from ``CARSPAN_PARAMS["dc_removal"]`` (workspace
        ``FrequencyAnalysis.carspan.dc_removal``), which itself defaults
        to False to preserve historical behaviour.

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
        dc_removal=dc_removal,
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

    Reproduces the reference CARSPAN Pascal implementation (function
    ``SOC`` in ``T_AnaFunctions.pas``):

    * Tukey window (α=0.10 → 5 % cosine bell per side) applied by
      **event index**, matching the Pascal ``Taper(NData, TaperPercent)``
      call which operates on the impulse-array index, not on clock time.
    * Amplitude ``2/T`` with no ``N/S₂`` correction — manual Eq. 3.19.
    * **Regular-grid DC removal**: at each event index the phasor of the
      actual time is subtracted by the phasor of the corresponding
      regular-grid time (``ExpTᵢ = (i+1)·ΔT``). This kills the DC
      component exactly and removes the low-frequency leakage that the
      mean-rate impulse train would otherwise contribute. CARSPAN does
      this implicitly via the ``A - AIBI`` subtraction in the inner
      loop of ``SOC``.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds (both inclusive) in Hz (events²/Hz).
    """
    freqs, power, bin_counts = _compute(
        event_times_s,
        f_max=f_max,
        smooth=True,
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
    dc_removal=None,
):
    """Shared strict/configurable CARSPAN PSD computation."""
    smooth = smooth if smooth is not None else CARSPAN_PARAMS["smooth_for_display"]
    display_resolution = float(
        display_resolution
        if display_resolution is not None
        else CARSPAN_PARAMS["freq_resolution"]
    )
    # DC removal is unconditional in strict mode (it's part of what makes
    # strict "manual-faithful"). In configurable mode the flag is opt-in
    # via CARSPAN_PARAMS, set from the workspace.
    if strict:
        use_dc_removal = True
    elif dc_removal is None:
        use_dc_removal = bool(CARSPAN_PARAMS.get("dc_removal", False))
    else:
        use_dc_removal = bool(dc_removal)

    N = event_times_s.size
    _require_min_samples(N, 4, "CARSPAN PSD")

    T = float(event_times_s[-1] - event_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")

    delta_f = 1.0 / T
    k_max = int(np.floor(f_max / delta_f))
    freqs = np.arange(1, k_max + 1) * delta_f

    if strict:
        # CARSPAN's Pascal Taper (T_AnaFunctions.pas:128-161) walks the
        # first / last N_taper samples and applies sin²(π·(i+1)/(2·N_taper))
        # by event index — note the (i+1) offset, which means sample 0
        # gets a small but *non-zero* weight, unlike scipy's tukey which
        # zeros it out.  We therefore build the window ourselves to match
        # CARSPAN bit-for-bit.  The loop runs over N_used = N_R−1 events
        # (CARSPAN sums IBIs, indexed by IBI = 0..N_IBI−1; see SOC line 364).
        #
        # ``alpha_taper = 0.10`` corresponds to ``TaperPercent = 5`` per
        # side in the Pascal source (RunDFT line 1952).
        n_taper_pct = max(1, int(round((alpha_taper * 50.0) * (N - 1) / 100.0)))
        w = _carspan_taper(N - 1, n_taper_pct)
        amplitude = 2.0 / T
    else:
        ws = window_spec
        if isinstance(ws, str) and ws.lower() == "tukey":
            ws = ("tukey", 0.10)
        w = get_window(ws, N, fftbins=False).astype(np.float64)
        S2 = float(np.sum(w**2))
        if S2 == 0:
            raise ValueError("Window sum-of-squares S₂ is zero — degenerate window.")
        amplitude = 2.0 * N / (T * S2)

    # ----- DFT of the (possibly mean-detrended) impulse train -----------
    #
    # CARSPAN's SOC (T_AnaFunctions.pas:297-414) loops over IBI = 0..N_IBI-1
    # — i.e. it sums over R-peaks 1..N_R-1 (skipping the first R-peak at
    # t=0) using the cumulative IBI sum as the actual time.  In strict
    # mode we follow that convention exactly so the Tᵢ array CARSPAN
    # plugs into the DFT and the one we plug in are identical.  The
    # configurable variant keeps the older "all events" behaviour for
    # backward compatibility — flip the flag below if you want
    # configurable mode to align too.
    if strict:
        actual_times = event_times_s[1:].astype(np.float64)
    else:
        actual_times = event_times_s.astype(np.float64)
    phase_actual = 2.0 * np.pi * np.outer(freqs, actual_times)

    if use_dc_removal:
        # CARSPAN-style regular-grid DC removal.
        #
        # The reference Pascal (T_AnaFunctions.pas, function SOC,
        # lines 297-414) maintains *two* phasor accumulators per event:
        #
        #   A    — phasor at the actual event time      Tᵢ = Σₖ≤ᵢ IBIₖ
        #   AIBI — phasor at the regular-grid time      ExpTᵢ = (i+1)·ΔT
        #
        # and accumulates ``Amp · (A - AIBI)``. ``ExpT`` advances by the
        # mean IBI at every step, so AIBI is the DFT of a perfectly
        # periodic impulse train at the mean rate. Subtracting it from A
        # removes the DC and mean-rate leakage that an un-detrended
        # impulse train would carry — at f = 0 both phasors equal 1, so
        # their difference is exactly zero.
        #
        # Strict mode uses this unconditionally (it's part of what makes
        # the variant manual-faithful). Configurable mode opts in via
        # ``CARSPAN_PARAMS["dc_removal"]`` (workspace key
        # ``FrequencyAnalysis.carspan.dc_removal``).
        #
        # CARSPAN's expected-time grid is offset from t₀ by ΔT and runs
        # for N_IBI = N_R − 1 points: ExpTᵢ = (i+1)·ΔT (relative to t₀)
        # for i = 0..N_IBI−1, with ΔT = T/(N_IBI−1) = T/(N_R−2).  The last
        # expected time is therefore (N_R−1)/(N_R−2)·T — slightly *past*
        # the actual end time, by design (Pascal SOC line 317-369).  We
        # mirror that exactly when ``strict`` so the DC-removal cancels
        # the same way it does in the reference implementation.
        if strict:
            n_used = N - 1
            delta_T = T / float(n_used - 1) if n_used > 1 else T
            exp_times = (
                float(event_times_s[0])
                + (np.arange(n_used, dtype=np.float64) + 1) * delta_T
            )
        else:
            # Configurable mode keeps the historical span-matched grid;
            # ``np.linspace`` zeros the first/last events but is slightly
            # easier to reason about for users who want a plain DFT.
            exp_times = np.linspace(
                float(event_times_s[0]),
                float(event_times_s[-1]),
                N,
            )
        phase_expected = 2.0 * np.pi * np.outer(freqs, exp_times)

        # X(f) = Σ wᵢ · [exp(-2πj f Tᵢ) - exp(-2πj f ExpTᵢ)]
        # Note the sign on the imaginary part: -sin(actual) - (-sin(exp))
        #                                    = -sin(actual) + sin(exp).
        X_real = np.dot(np.cos(phase_actual) - np.cos(phase_expected), w)
        X_imag = np.dot(-np.sin(phase_actual) + np.sin(phase_expected), w)
    else:
        # Plain DFT — no DC removal. Used by the configurable variant
        # when ``dc_removal`` is False (the historical default). The
        # N/S₂ amplitude correction handles energy bookkeeping; users
        # can detrend upstream if they need it.
        X_real = np.dot(np.cos(phase_actual), w)
        X_imag = np.dot(-np.sin(phase_actual), w)

    power = amplitude * (X_real**2 + X_imag**2)

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


def _carspan_taper(length: int, n_taper: int) -> np.ndarray:
    """
    CARSPAN-style cosine-bell taper, applied to a unit array.

    Mirrors ``T_AnaFunctions.pas:128-161`` (procedure ``Taper``):

        Fac := pi / (2 * NrOfTaperSmp);
        for LeftSmp := 1 to NrOfTaperSmp do begin
            FArg := LeftSmp * Fac;
            if LeftSmp <> NrOfTaperSmp then FCos := cos(FArg)
            else                            FCos := 0;     # forced 1 at the inner edge
            FMult := 1 - sqr(FCos);                        # = sin^2(FArg)
            Data[LeftSmp - 1] *= FMult;
            Data[length - LeftSmp] *= FMult;
        end;

    Note the (LeftSmp) — *not* (LeftSmp − 1) — index in the cosine
    argument: sample 0 receives weight ``sin^2(pi / (2 * N_taper))``
    rather than 0.  scipy.signal.get_window(("tukey", ...)) zeros the
    first sample, so we cannot use it for bit-for-bit parity.
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
        w[right_smp]    *= f_mult
    return w


def _bin_average(native_freqs, native_power, display_resolution):
    """
    Bin-average the native grid onto a display grid starting at 2 × resolution.

    Returns ``(display_freqs, display_power, bin_counts)``.  Effective dof
    per display bin is ``2 × bin_counts`` --- averaging k native bins
    raises the chi-squared dof from 2 (single DFT) to 2k.

    The first display bin is centred at 2·Δ (e.g. 0.020 Hz for
    Δ = 0.01 Hz), so native bins below 1.5·Δ (near-DC, high
    1/f power) are excluded.
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
