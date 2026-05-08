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
    "dc_removal": False, # Let op! Strict mode always applies DC removal regardless of this flag.
    # Upper frequency limit of the computed spectrum. Driven by the
    # configured frequency-band table — ``load_frequency_bands`` in
    # ``CardioFrequencyMetricsMixin`` updates this to the highest
    # ``high`` across all bands (typically ``FullRange.high = 0.5 Hz``)
    # whenever the workspace bands change, so CARSPAN's grid always
    # extends just far enough to integrate every band the user has
    # configured. Override directly only if you have a reason to.
    "f_max": 0.5,
}


def load_carspan_params(config: dict) -> None:
    """Update module-level CARSPAN_PARAMS from a workspace config dict."""
    update_params(CARSPAN_PARAMS, config)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# CARSPAN manual + Pascal source pin the strict-mode taper width at
# α = 0.10 (5 % cosine bell per side, ``TaperPercent = 5`` in
# ``RunDFT`` line 1952). Exposing this as a kwarg would only invite
# users to drift away from "manual-faithful", so it lives here as a
# private constant.
_STRICT_ALPHA_TAPER: float = 0.10


def compute_carspan_psd(
    event_times_s: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    window: Optional[str] = None,
    smooth: Optional[bool] = None,
    display_resolution: Optional[float] = None,
    dc_removal: Optional[bool] = None,
    strict: bool = False,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    CARSPAN PSD with chi-squared CI.

    By default this is the **configurable** variant: an arbitrary scipy
    window applied by event index and an ``N/S₂`` amplitude correction
    that makes the level approximately window-invariant. DC removal is
    opt-in via ``dc_removal`` or ``CARSPAN_PARAMS["dc_removal"]``.

    Pass ``strict=True`` for the **manual-faithful** preset that
    reproduces the reference CARSPAN Pascal implementation (function
    ``SOC, spectrum of counts!`` in ``T_AnaFunctions.pas``) bit-for-bit. The strict bundle
    locks in:

    * Tukey 5 % cosine bell taper (α = 0.10) applied by **event index**,
      matching the Pascal ``Taper`` procedure exactly. The user-supplied
      ``window`` kwarg is therefore ignored in strict mode.
    * Amplitude ``2/T`` with no ``N/S₂`` correction (manual Eq. 3.19).
    * Regular-grid DC removal: each event's phasor at its actual time
      is subtracted by the phasor at its regular-grid expected time
      ``ExpTᵢ = (i+1)·ΔT``. At ``f = 0`` both phasors are 1 so DC is
      removed exactly; the subtraction also cancels the spectral
      leakage that a mean-rate impulse train would otherwise contribute
      to VLF / LF. ``dc_removal`` is forced on in this mode.
    * The "skip first event" convention from Pascal ``SOC`` (sums over
      IBI indices ``0..N_IBI-1`` rather than over all R-peaks).

    ``smooth`` defaults to True in strict mode (CARSPAN's plot
    convention), but an explicit ``smooth=False`` still wins — the
    band-power integration path needs the unsmoothed grid.

    Parameters
    ----------
    dc_removal : bool, optional
        Configurable mode only: if True, apply the same DC / mean-rate
        leakage removal the strict mode performs unconditionally. If
        ``None`` (default), the flag is read from
        ``CARSPAN_PARAMS["dc_removal"]`` (workspace
        ``FrequencyAnalysis.carspan.dc_removal``).
    strict : bool, default False
        Lock in the CARSPAN-faithful preset. See above.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds in Hz (events²/Hz).
    """
    if strict:
        # Strict mode: lock the bundle the manual + Pascal specify.
        # ``window`` is ignored (strict path builds its own taper).
        # ``dc_removal`` is forced on. ``smooth`` defaults to True but
        # explicit overrides still win so the band-power integration
        # path can request an unsmoothed grid via ``smooth=False``.
        window_spec = None
        dc_removal_effective: Optional[bool] = True
        smooth_effective = True if smooth is None else smooth
    else:
        window_spec = _resolve_window(
            window if window is not None else CARSPAN_PARAMS["window"]
        )
        dc_removal_effective = dc_removal
        smooth_effective = smooth

    freqs, power, bin_counts = _compute(
        event_times_s,
        smooth=smooth_effective,
        display_resolution=display_resolution,
        strict=strict,
        window_spec=window_spec,
        dc_removal=dc_removal_effective,
        alpha_taper=_STRICT_ALPHA_TAPER,
    )
    ci_lower, ci_upper = _chi2_ci(power, 2 * bin_counts, alpha_ci)
    return freqs, power, ci_lower, ci_upper


def compute_carspan_psd_strict(
    event_times_s: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    smooth: Optional[bool] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Manual-faithful CARSPAN PSD with chi-squared CI.

    Thin wrapper for ``compute_carspan_psd(..., strict=True)`` — see
    that function for the full description of which knobs the strict
    bundle locks. The wrapper exposes only the parameters the manual
    leaves to the caller (``alpha_ci``) plus ``smooth`` so the
    band-power integration path can request the unsmoothed grid.
    Display resolution, taper width, window choice, DC-removal flag
    and the upper frequency cap are *not* exposed here — they all
    fall back to ``CARSPAN_PARAMS`` via ``compute_carspan_psd``.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds (both inclusive) in Hz (events²/Hz).
    """
    return compute_carspan_psd(
        event_times_s,
        alpha_ci=alpha_ci,
        smooth=smooth,
        strict=True,
    )


# ---------------------------------------------------------------------------
# Core computation
#
# ``_compute`` is the single entry point shared by both public functions
# (``compute_carspan_psd`` and ``compute_carspan_psd_strict``). It is kept
# deliberately short — each conceptual step is delegated to a small named
# helper below so the top-level reads as plain English. The helpers know
# nothing about each other; they just transform their inputs.
# ---------------------------------------------------------------------------


def _compute(
    event_times_s: np.ndarray,
    *,
    smooth: Optional[bool],
    display_resolution: Optional[float],
    strict: bool,
    window_spec=None,
    alpha_taper: float = 0.10,
    dc_removal: Optional[bool] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Shared strict/configurable CARSPAN PSD computation.

    Reads as a sequence of named steps; each step lives in its own
    helper function below the public API and can be read in isolation.
    """
    # 1. Resolve any ``None`` arguments against CARSPAN_PARAMS / strict rules.
    smooth_active, df_display, use_dc_removal, f_max = _resolve_options(
        strict=strict,
        smooth=smooth,
        display_resolution=display_resolution,
        dc_removal=dc_removal,
    )

    # 2. Sanity-check the input and pull the observation span.
    N = event_times_s.size
    T = _validate_input(event_times_s, N)

    # 3. Build the native-grid frequencies (Δf = 1/T) up to ``f_max``.
    freqs, delta_f = _native_grid(T=T, f_max=f_max)

    # 4. Pick the per-event window weights and the amplitude pre-factor.
    w, amplitude = _make_window(
        N=N,
        T=T,
        strict=strict,
        window_spec=window_spec,
        alpha_taper=alpha_taper,
    )

    # 5. Pick the actual event times that go into the DFT.
    actual_times = _actual_times(event_times_s=event_times_s, strict=strict)

    # 6. Single windowed DFT of the actual event train.
    X_real, X_imag = _dft(freqs, actual_times, w)

    # 7. Optional DC-removal post-step: subtract the DFT of a regular-grid
    #    reference impulse train at the mean rate. CARSPAN's trick that
    #    kills DC and drains mean-rate leakage; see ``_remove_dc``.
    if use_dc_removal:
        exp_times = _dc_reference_times(
            event_times_s=event_times_s,
            n_actual=actual_times.size,
            strict=strict,
        )
        X_real, X_imag = _remove_dc(X_real, X_imag, freqs, exp_times, w)

    # 8. |X(f)|² × amplitude → raw periodogram on the native grid.
    power = amplitude * (X_real**2 + X_imag**2)

    # 9. Optionally bin-average to the display grid and apply the 3-MA
    #    smoother that CARSPAN uses on the plotted curve.
    return _apply_display_smoothing(
        freqs=freqs,
        power=power,
        delta_f=delta_f,
        display_resolution=df_display,
        do_smooth=smooth_active,
    )


# ---------------------------------------------------------------------------
# Step helpers — each one does exactly the step it is named after.
# ---------------------------------------------------------------------------


def _resolve_options(
    *,
    strict: bool,
    smooth: Optional[bool],
    display_resolution: Optional[float],
    dc_removal: Optional[bool],
) -> Tuple[bool, float, bool, float]:
    """
    Fold ``None`` arguments into concrete values.

    Returns ``(smooth_active, display_resolution, use_dc_removal, f_max)``:

    * ``smooth_active`` — bool, falls back to ``smooth_for_display`` workspace key.
    * ``display_resolution`` — float in Hz, falls back to ``freq_resolution``.
    * ``use_dc_removal`` — bool. Strict mode is *always* DC-removed (this
      is part of what makes strict "manual-faithful"). Configurable mode
      reads ``dc_removal`` from the explicit kwarg first, then from
      ``CARSPAN_PARAMS["dc_removal"]``.
    * ``f_max`` — float in Hz, the upper limit of the computed spectrum.
      Always read from ``CARSPAN_PARAMS["f_max"]`` (kept in sync with
      the configured frequency-band table by ``load_frequency_bands``).
    """
    smooth_active = (
        smooth if smooth is not None else CARSPAN_PARAMS["smooth_for_display"]
    )
    display_resolution = float(
        display_resolution
        if display_resolution is not None
        else CARSPAN_PARAMS["freq_resolution"]
    )
    if strict:
        use_dc_removal = True
    elif dc_removal is None:
        use_dc_removal = bool(CARSPAN_PARAMS.get("dc_removal", False))
    else:
        use_dc_removal = bool(dc_removal)
    f_max = float(CARSPAN_PARAMS.get("f_max", 0.5))
    return bool(smooth_active), display_resolution, use_dc_removal, f_max


def _validate_input(event_times_s: np.ndarray, N: int) -> float:
    """
    Sanity-check the event-times array and return the observation span ``T``.

    Raises if there are fewer than 4 events or if the time span is zero
    or negative — both conditions would make the rest of the pipeline
    meaningless.
    """
    _require_min_samples(N, 4, "CARSPAN PSD")
    T = float(event_times_s[-1] - event_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")
    return T


def _native_grid(*, T: float, f_max: float) -> Tuple[np.ndarray, float]:
    """
    Build the CARSPAN native frequency grid.

    The grid runs from ``Δf = 1/T`` to ``k_max · Δf`` with
    ``k_max = floor(f_max / Δf)``. The DC bin (k=0) is excluded — it
    carries no HRV information and would dominate the y-axis if kept.
    """
    delta_f = 1.0 / T
    k_max = int(np.floor(f_max / delta_f))
    freqs = np.arange(1, k_max + 1) * delta_f
    return freqs, delta_f


def _make_window(
    *,
    N: int,
    T: float,
    strict: bool,
    window_spec=None,
    alpha_taper: float = 0.10,
) -> Tuple[np.ndarray, float]:
    """
    Build per-event window weights and the DFT amplitude pre-factor.

    Two presets, picked by ``strict``:

    * **strict (CARSPAN-faithful)** — ``window_spec`` is ignored and the
      window is the bit-for-bit equivalent of CARSPAN's Pascal ``Taper``
      (``T_AnaFunctions.pas:128-161``): a ``sin²(π·(i+1)/(2·N_taper))``
      cosine bell applied by *event index*, with the (i+1) offset that
      gives the first sample a small but *non-zero* weight (unlike
      scipy's tukey, which zeros it). The taper acts on ``N − 1`` events
      because CARSPAN's ``SOC`` loops over IBI indices ``0..N_IBI-1``.
      ``alpha_taper = 0.10`` corresponds to ``TaperPercent = 5`` per
      side (``RunDFT`` line 1952). Amplitude is the manual's ``2/T``
      with no ``N/S₂`` correction (Eq. 3.19).

    * **configurable** — any ``scipy.signal.get_window`` name or
      ``(name, params)`` tuple. ``"tukey"`` without parameters defaults
      to α = 0.10 to stay close to CARSPAN. The amplitude carries the
      standard ``2N / (T·S₂)`` correction (``S₂ = Σ wᵢ²``), making the
      level approximately window-invariant so users can swap windows
      without rescaling the spectrum.

    Returns ``(w, amplitude)`` ready for the DFT step.
    """
    if strict:
        n_taper_pct = max(1, int(round((alpha_taper * 50.0) * (N - 1) / 100.0)))
        w = _carspan_taper(N - 1, n_taper_pct)
        amplitude = 2.0 / T
        return w, amplitude

    ws = window_spec
    if isinstance(ws, str) and ws.lower() == "tukey":
        ws = ("tukey", 0.10)
    w = get_window(ws, N, fftbins=False).astype(np.float64)
    S2 = float(np.sum(w**2))
    if S2 == 0:
        raise ValueError("Window sum-of-squares S₂ is zero — degenerate window.")
    amplitude = 2.0 * N / (T * S2)
    return w, amplitude


def _actual_times(*, event_times_s: np.ndarray, strict: bool) -> np.ndarray:
    """
    Pick the array of actual event times that goes into the DFT.

    CARSPAN's ``SOC`` (``T_AnaFunctions.pas:297-414``) loops over
    ``IBI = 0..N_IBI-1`` — i.e. R-peaks 1..N_R-1, skipping the first
    R-peak at t = 0 — using the cumulative IBI sum as the actual time.
    Strict mode mirrors that exactly so the ``Tᵢ`` array CARSPAN plugs
    into the DFT and the one spectHR plugs in are identical. The
    configurable variant uses *all* events for backward compatibility.
    """
    if strict:
        return event_times_s[1:].astype(np.float64)
    return event_times_s.astype(np.float64)


def _dc_reference_times(
    *, event_times_s: np.ndarray, n_actual: int, strict: bool
) -> np.ndarray:
    """
    Build the regular-grid reference times subtracted in DC removal.

    CARSPAN-style DC removal subtracts the DFT of a perfectly periodic
    impulse train at the mean rate from the DFT of the actual event
    train. The reference grid spacing depends on which mode we're in:

    * **Strict** (``T_AnaFunctions.pas`` SOC line 317-369): the
      expected-time grid is offset from ``t₀`` by ``ΔT`` and has
      ``N_IBI = N_R − 1`` points::

            ExpTᵢ = t₀ + (i + 1) · ΔT,  i = 0..N_IBI-1
            ΔT    = T / (N_IBI − 1)    = T / (N_R − 2)

      The last expected time therefore lands slightly past ``t_end``
      by design — that's how the Pascal cancels the DC.
    * **Configurable**: a span-matched ``linspace`` from ``t₀`` to
      ``t_end`` with ``N`` points. Easier to reason about and zeros
      the boundary phase difference at f = 0; we keep it as the
      configurable-mode default for users who don't need bit-for-bit
      Pascal parity.
    """
    t0 = float(event_times_s[0])
    if strict:
        delta_T = (
            (event_times_s[-1] - event_times_s[0]) / float(n_actual - 1)
            if n_actual > 1
            else (event_times_s[-1] - event_times_s[0])
        )
        return t0 + (np.arange(n_actual, dtype=np.float64) + 1) * float(delta_T)
    return np.linspace(t0, float(event_times_s[-1]), n_actual)


def _dft(
    freqs: np.ndarray, times: np.ndarray, w: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Windowed DFT of an impulse train — ``X(f) = Σ wᵢ · exp(-2πj f tᵢ)``.

    Returns the real and imaginary parts as separate arrays rather than
    a single complex array — slightly faster (no complex multiplies)
    and clearer when ``_remove_dc`` later subtracts a second DFT
    component-wise.
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
    """
    CARSPAN-style DC removal: subtract the DFT of a regular-grid impulse train.

    Given an already-computed DFT ``X(f)`` of the actual event train,
    this function computes the DFT of a perfectly periodic impulse
    train at the mean rate (using the same window ``w``) and returns
    ``X(f) − X_ref(f)`` component-wise:

        X'(f) = Σ wᵢ · [exp(-2πj f Tᵢ) − exp(-2πj f ExpTᵢ)]

    Mirrors the ``A − AIBI`` accumulator subtraction in CARSPAN's
    Pascal ``SOC``. At ``f = 0`` both phasors equal ``1``, so their
    difference is zero — the DC component is removed exactly. Beyond
    DC, subtracting the regular-grid DFT also drains the spectral
    leakage that the mean-rate impulse train would otherwise contribute
    to the VLF / LF region.

    Splitting the operation into a separate ``_dft`` plus this
    component-wise subtraction is mathematically identical to doing
    everything in one combined kernel, but it factors the two ideas
    cleanly and lets ``_dft`` stay simple.
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
    """
    Bin-average to the display grid and run the CARSPAN 3-point MA.

    Two things happen, both gated by ``do_smooth``:

    1. **Bin-averaging.** When the native grid is finer than the
       display grid (``Δf < display_resolution`` ≈ 0.99×), neighbouring
       native bins are averaged into display bins. This raises the
       chi-squared dof per bin from 2 (single DFT) to ``2 × bin_counts``,
       which the caller uses to compute confidence intervals. Without
       smoothing every bin still has dof = 2.

    2. **3-point moving average.** CARSPAN manual sec. 3.2, p. 33::

           "a moving average window over three frequency points
            (0.03 Hz bandwidth) is applied before plotting the
            spectral functions"

       This is plot-only smoothing. Band-power integration runs on the
       same array, but the kernel is mean-preserving (modulo small
       boundary effects), so the area under the curve is preserved
       and peaks visually drop ≈ 3× to match CARSPAN's display.
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
