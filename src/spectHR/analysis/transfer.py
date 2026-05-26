# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/transfer.py
"""
Transfer function computation (Respiration → HR coupling).

Faithful Python port of the CARSPAN ``RunTransfer`` pipeline
(``T_AnaFunctions.pas`` lines 492–809, 2178–2610).

Pipeline
--------
For a single epoch the steps are:

1.  Interpolate the continuous respiration TimeSeries at R-peak times
    to obtain a beat-indexed respiration signal.
2.  Mean-subtract both the IBI and respiration signals and apply the
    CARSPAN cosine-bell taper, then weight by the local IBI duration
    (Pascal ``Amp := NData[i] * IData[i]/1000``).
3.  Compute the complex DFT for both signals at the cumulative-IBI time
    grid (the CARSPAN IBI-amplitude SOC convention, Eq. 3.21 + the
    analogous non-IBI column path).
4.  Form the auto-spectra ``(2×10⁶/T)·|DFT|²`` and complex cross-spectrum
    ``conj(DFT_in)·DFT_out·(2×10⁶/T)``; optionally apply the 3-point
    triangular frequency smoother used in the profile path
    (``T_AnaFunctions.pas:574-583``, WindowSize=3).
5.  Transfer function  ``H = Cross / Auto_in``.
6.  Modulus ``|H|``, wrapped phase ``arctan2(Im, Re)``, unwrapped phase
    (threshold π, step 2π), squared coherence ``|Cross|²/(Auto_in·Auto_out)``.
7.  Per-band summaries: power-weighted coherence, coherence-gated modulus
    and phase means (``Caluculate_WeightedCoherenceSum``,
    ``Caluculate_ModulusSum``, ``Caluculate_PhaseSum``).

Public surface
--------------
``compute_transfer(series, rsp_timeseries, *, ...) -> TransferResult``

Notes
-----
For a *single unsmoothed epoch* the squared coherence is mathematically
1 at every non-zero bin (each DFT has exactly one realization). Set
``smooth=True`` to apply the 3-point triangular smoother to the spectra
before computing coherence; this gives sub-unity coherence estimates
useful for sliding-window (profile) analyses.

References
----------
CARSPAN manual §3.3.1–3.3.3; ``T_AnaFunctions.pas`` functions
``CrossSpectrum`` (492), ``AutoSpectrum`` (416), ``Transfer`` (700),
``Modulus`` (723), ``Phase`` (744), ``UnwrapPhase`` (762),
``Coherence`` (784), ``Caluculate_WeightedCoherenceSum`` (883),
``Caluculate_PhaseSum`` (935), ``Caluculate_ModulusSum`` (963),
``RunCrossSpectrum`` (2178), ``RunPDS`` (2101), ``RunTransfer`` (2493).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from spectHR.analysis.ibi_helpers import event_times_clean
from spectHR.analysis.psd._carspan import _make_window, _native_grid


__all__ = [
    "BandTransfer",
    "TransferResult",
    "TransferProfileResult",
    "compute_transfer",
    "compute_transfer_profile",
]


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BandTransfer:
    """Band-integrated transfer statistics for one frequency band.

    Attributes
    ----------
    weighted_coherence : float
        Power-weighted mean coherence over the band:
        ``Σ(coh[k] × psd_in[k]) / Σ(psd_in[k])``.
        Faithful to ``Caluculate_WeightedCoherenceSum``
        (``T_AnaFunctions.pas:883``).
    modulus : float
        Mean modulus over the band, restricted to bins where
        ``coherence[k] ≥ min_coherence``.
        Faithful to ``Caluculate_ModulusSum``
        (``T_AnaFunctions.pas:963``).
    phase : float
        Mean **wrapped** phase (radians) over coherent bins in the band
        (CARSPAN ``Phase2`` path — ``Phase(TransList)`` without
        ``UnwrapPhase``; ``Caluculate_PhaseSum``,
        ``T_AnaFunctions.pas:935``).
    phase_unwrapped : float
        Mean **unwrapped** (within-epoch) phase (radians) over coherent
        bins in the band (CARSPAN ``Phase`` path — ``Phase(TransList)``
        mutated by ``UnwrapPhase(thresh=π, step=2π)`` before
        ``Caluculate_PhaseSum``).
    n_points : int
        Total number of frequency bins inside the band.
    n_coherent : int
        Number of bins where ``coherence ≥ min_coherence``.  When this
        is 0, ``modulus`` and ``phase`` are 0 and not meaningful.
    """

    weighted_coherence: float
    modulus: float
    phase: float
    phase_unwrapped: float
    n_points: int
    n_coherent: int


@dataclass(frozen=True)
class TransferResult:
    """Immutable container for a transfer function computation.

    Analogous to :class:`~spectHR.analysis.psd._utils.PSDResult`.

    Attributes
    ----------
    freqs : (N,) ndarray
        Frequency grid in Hz (native Δf = 1/T grid, DC excluded).
    modulus : (N,) ndarray
        ``|H(f)|`` — amplitude gain of the transfer function at each
        frequency.  Units are ``output_unit / input_unit`` (e.g. ms/V
        when HR is in ms and respiration in Volts).
    phase_wrapped : (N,) ndarray
        ``arctan2(Im H, Re H)`` in radians, range ``(−π, +π]``.
        Faithful to ``T_AnaFunctions.pas:Phase()``.
    phase_unwrapped : (N,) ndarray
        Phase unwrapped across the spectrum using CARSPAN's threshold-
        based convention (threshold = π, step = 2π).
        Faithful to ``T_AnaFunctions.pas:UnwrapPhase()``.
    coherence : (N,) ndarray
        Squared coherence ``|C(f)|²`` in ``[0, 1]``.  For a single
        un-smoothed epoch this is 1 everywhere (by construction); set
        ``smooth=True`` in :func:`compute_transfer` to obtain sub-unity
        estimates.
    freq_resolution : float
        Frequency resolution ``Δf = 1/T`` in Hz.
    method : str
        Algorithm label (``"carspan_transfer"``).
    band_results : dict[str, BandTransfer] or None
        Per-band summary statistics; ``None`` when no bands were
        requested, ``{}`` when an empty band dict was passed.
    """

    freqs: np.ndarray
    modulus: np.ndarray
    phase_wrapped: np.ndarray
    phase_unwrapped: np.ndarray
    coherence: np.ndarray
    freq_resolution: float
    method: str = "carspan_transfer"
    band_results: Optional[Dict[str, BandTransfer]] = None


@dataclass(frozen=True)
class TransferProfileResult:
    """Immutable container for a sliding-window transfer-function profile.

    Parallel to :class:`~spectHR.analysis.psd._utils.ProfileResult` but
    for transfer function quantities instead of band power.

    A profile is the time-resolved transfer statistics of a recording:
    modulus, coherence, and phase band-values recomputed inside each of a
    series of overlapping sliding windows — exactly as CARSPAN's
    ``RunTransfer`` profile branch (``T_AnaFunctions.pas:2562-2608``)
    feeds the output loop in ``T_Output.pas`` (``acCoherence``,
    ``acModulus``, ``acPhase``).

    Fields
    ------
    timestamps : (n_windows,) float array
        Window-centre times in seconds.
    band_names : list[str]
        Band names in the row order of the 2-D arrays below.
    modulus : (n_bands, n_windows) float array
        Coherence-gated mean ``|H(f)|`` per band per window.
        ``np.nan`` when a window had fewer than 4 R-peaks or no
        coherent bins (``Caluculate_ModulusSum``).
    phase : (n_bands, n_windows) float array
        Coherence-gated mean **wrapped** phase (radians) per band per
        window.  Corresponds to CARSPAN ``Phase2`` (the copy of
        ``Phase(TransList)`` that ``UnwrapPhase`` did *not* touch).
    phase_unwrapped : (n_bands, n_windows) float array
        Coherence-gated mean of the **within-window unwrapped** phase
        (radians) per band per window.  Corresponds to CARSPAN ``Phase``
        (the copy that *was* mutated by
        ``UnwrapPhase(thresh=π, step=2π)``).
    weighted_coherence : (n_bands, n_windows) float array
        Power-weighted mean coherence per band per window
        (``Caluculate_WeightedCoherenceSum``).
    n_coherent : (n_bands, n_windows) int array
        Number of frequency bins with coherence ≥ ``min_coherence``
        that contributed to the modulus / phase means in each window.
    window_s : float
        Window length in seconds.
    step_s : float
        Step between successive windows in seconds.
    method : str
        Algorithm label (``"carspan_transfer"``).
    """

    timestamps: np.ndarray
    band_names: list
    modulus: np.ndarray
    phase: np.ndarray
    phase_unwrapped: np.ndarray
    weighted_coherence: np.ndarray
    n_coherent: np.ndarray
    window_s: float
    step_s: float
    method: str = "carspan_transfer"


# ---------------------------------------------------------------------------
# Low-level signal-processing helpers
# Each one is a direct port of a single named Pascal function.
# ---------------------------------------------------------------------------


def _compute_dft(
    freqs: np.ndarray,
    times: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Complex DFT: ``X(f) = Σ wᵢ · exp(−2πj·f·tᵢ)``.

    Used instead of the split real/imag form in ``_carspan._dft`` so that
    the rest of the transfer pipeline can work with standard complex arrays.
    """
    phase = 2.0 * np.pi * np.outer(freqs, times)   # (n_freqs, n_beats)
    re = np.dot(np.cos(phase), weights)
    im = -np.dot(np.sin(phase), weights)
    return re + 1j * im


def _auto_spectrum(dft: np.ndarray, T: float) -> np.ndarray:
    """Auto-spectrum: ``(2×10⁶/T)·|DFT|²``.

    Faithful to ``T_AnaFunctions.pas:AutoSpectrum()`` (WindowSize=0)::

        Dou := 1000000 * (2 * cd_real(conj(X)·X) / T)
    """
    return (2.0e6 / T) * (dft.real ** 2 + dft.imag ** 2)


def _cross_spectrum(
    dft_in: np.ndarray,
    dft_out: np.ndarray,
    T: float,
) -> np.ndarray:
    """Complex cross-spectrum: ``conj(DFT_in)·DFT_out·(2×10⁶/T)``.

    Faithful to ``T_AnaFunctions.pas:CrossSpectrum()`` (WindowSize=0)::

        cd_conj(conCValue1, CValue1^)
        cd_mul(DCom, conCValue1, CValue2^)
        cd_DivRe(DCom, DCom, T/2000000)
    """
    return np.conj(dft_in) * dft_out * (2.0e6 / T)


def _smooth3(x: np.ndarray) -> np.ndarray:
    """3-point triangular frequency smoother (CARSPAN WindowSize=3).

    ``T_AnaFunctions.pas:CreateWindow`` builds ``[0.5, 1.0, 0.5]`` for
    WindowSize=3 (normalised sum = 2, effective weights 1/4 · 1/2 · 1/4).
    Boundary bins are padded by mirror reflection, which matches the
    Pascal head/tail initialisation in ``CrossSpectrum`` / ``AutoSpectrum``
    when WindowSize != 0::

        VCD_PElement(TMPVector, MaxPnt+index)^ := DCom;
        VCD_PElement(TMPVector, MaxPnt-index)^ := DCom;   # mirror
    """
    if x.size < 3:
        return x.copy()
    w = np.array([0.5, 1.0, 0.5])
    padded = np.pad(x, 1, mode="reflect")
    return np.convolve(padded, w, mode="valid") / w.sum()


def _smooth3_complex(x: np.ndarray) -> np.ndarray:
    """Apply :func:`_smooth3` to real and imaginary parts independently.

    Matches the Pascal ``MAW(..., Complex=True)`` path which separates
    the real and imaginary lists before smoothing and recombines them.
    """
    return _smooth3(x.real) + 1j * _smooth3(x.imag)


def _transfer_function(cross: np.ndarray, auto_in: np.ndarray) -> np.ndarray:
    """Transfer function ``H = Cross / Auto_in`` (complex ÷ real).

    Faithful to ``T_AnaFunctions.pas:Transfer()``::

        if PDou^ = 0 then H := 0+0j
        else           cd_divRe(PDCom^, CValue^, PDou^)
    """
    H = np.zeros(len(cross), dtype=complex)
    ok = auto_in != 0.0
    H[ok] = cross[ok] / auto_in[ok]
    return H


def _modulus(H: np.ndarray) -> np.ndarray:
    """``|H(f)| = sqrt(conj(H)·H)``.

    Faithful to ``T_AnaFunctions.pas:Modulus()``::

        cd_conj(con, PDCom^); cd_mul(tmp, con, PDCom^); sqrt(tmp.Re)
    """
    return np.sqrt(H.real ** 2 + H.imag ** 2)


def _phase_wrapped(H: np.ndarray) -> np.ndarray:
    """Wrapped phase ``arctan2(Im H, Re H)``.

    Faithful to ``T_AnaFunctions.pas:Phase()``::

        PDou^ := arcTan2(PDCom^.Im, PDCom^.Re)
    """
    return np.arctan2(H.imag, H.real)


def _unwrap_phase(
    phase: np.ndarray,
    thresh: float = np.pi,
    step: float = 2.0 * np.pi,
) -> np.ndarray:
    """CARSPAN-faithful phase unwrapping.

    Direct port of ``T_AnaFunctions.pas:UnwrapPhase()`` (lines 762-780).
    The comparison always uses the *raw* (un-offset) phase values; the
    offset (``ModFactor × step``) is accumulated separately::

        Next := Phase[0]
        for index := 0 to N-2:
            First := Next
            Next  := Phase[index+1]         # raw, before any offset
            Dev   := First - Next
            if   Dev >= thresh:  inc(ModFactor)
            elif Dev <= -thresh: dec(ModFactor)
            Phase[index+1] += ModFactor * step

    Parameters
    ----------
    phase : ndarray
        Wrapped phase values in radians.
    thresh : float
        Jump threshold; CARSPAN uses ``1.0 * pi``.
    step : float
        Correction step; CARSPAN uses ``2 * pi``.
    """
    if phase.size < 2:
        return phase.copy()
    out = phase.copy()
    mod_factor = 0
    prev = float(phase[0])          # raw Phase[0]
    for i in range(phase.size - 1):
        curr = float(phase[i + 1])  # raw Phase[i+1], read before modification
        dev = prev - curr
        if dev >= thresh:
            mod_factor += 1
        elif dev <= -thresh:
            mod_factor -= 1
        out[i + 1] = curr + mod_factor * step
        prev = curr                 # next comparison uses raw Phase[i+1]
    return out


def _coherence(
    cross: np.ndarray,
    auto_in: np.ndarray,
    auto_out: np.ndarray,
) -> np.ndarray:
    """Squared coherence ``|Cross|² / (Auto_in × Auto_out)``.

    Faithful to ``T_AnaFunctions.pas:Coherence()``::

        cd_conj(con, PDCom^); cd_mul(tmp, con, PDCom^)
        if (abs(PValue1^) * abs(PValue2^)) = 0 then PDou^ := 0
        else PDou^ := cd_real(tmp) / (abs(PValue1^) * abs(PValue2^))
    """
    denom = auto_in * auto_out
    coh = np.zeros(len(cross))
    ok = denom > 0.0
    cross_sq = cross.real ** 2 + cross.imag ** 2
    coh[ok] = cross_sq[ok] / denom[ok]
    return np.clip(coh, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Band-summary helpers (T_AnaFunctions.pas:883-980)
# ---------------------------------------------------------------------------


def _band_slice(
    low_hz: float,
    high_hz: float,
    freq_res: float,
    n: int,
) -> Tuple[int, int]:
    """Map band edges to 0-based array indices.

    CARSPAN index convention (``T_AnaFunctions.pas:Caluculate_ModulusSum``)::

        LowerIndex := round(LowerBand / FreqRes) - 1
        UpperIndex := round(UpperBand / FreqRes) - 1

    Uses ``int(x + 0.5)`` to match Pascal ``round()`` (rounds 0.5 up),
    not Python's banker's rounding.  Returns ``(-1, -2)`` when either
    edge is zero or the slice is empty.
    """
    if low_hz == 0.0 or high_hz == 0.0:
        return -1, -2
    lo = max(0,     int(low_hz  / freq_res + 0.5) - 1)
    hi = min(n - 1, int(high_hz / freq_res + 0.5) - 1)
    if hi < lo:
        return -1, -2
    return lo, hi


def _band_weighted_coherence(
    coh: np.ndarray,
    psd_in: np.ndarray,
    lo: int,
    hi: int,
) -> Tuple[float, int]:
    """``Σ(coh[k]·psd_in[k]) / Σ(psd_in[k])`` over ``[lo, hi]`` inclusive.

    Faithful to ``T_AnaFunctions.pas:Caluculate_WeightedCoherenceSum()``
    (lines 883-907).
    """
    if lo > hi or lo < 0:
        return 0.0, 0
    c = coh[lo : hi + 1]
    p = psd_in[lo : hi + 1]
    n_pts = len(c)
    B = float(np.sum(p))
    if B == 0.0:
        return 0.0, n_pts
    return float(np.sum(c * p) / B), n_pts


def _band_modulus_mean(
    modulus: np.ndarray,
    coh: np.ndarray,
    lo: int,
    hi: int,
    min_coh: float,
) -> Tuple[float, int]:
    """Mean modulus where ``coh >= min_coh`` over ``[lo, hi]``.

    Faithful to ``T_AnaFunctions.pas:Caluculate_ModulusSum()``
    (lines 963-980).
    """
    if lo > hi or lo < 0:
        return 0.0, 0
    sl_mod = modulus[lo : hi + 1]
    sl_coh = coh[lo : hi + 1]
    mask = sl_coh >= min_coh
    n_coh = int(np.sum(mask))
    if n_coh == 0:
        return 0.0, 0
    return float(np.mean(sl_mod[mask])), n_coh


def _band_phase_mean(
    phase: np.ndarray,
    coh: np.ndarray,
    lo: int,
    hi: int,
    min_coh: float,
) -> Tuple[float, int]:
    """Mean phase where ``coh >= min_coh`` over ``[lo, hi]``.

    Faithful to ``T_AnaFunctions.pas:Caluculate_PhaseSum()``
    (lines 935-959).
    """
    if lo > hi or lo < 0:
        return 0.0, 0
    sl_phase = phase[lo : hi + 1]
    sl_coh = coh[lo : hi + 1]
    mask = sl_coh >= min_coh
    n_coh = int(np.sum(mask))
    if n_coh == 0:
        return 0.0, 0
    return float(np.mean(sl_phase[mask])), n_coh


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_transfer(
    series,
    rsp_timeseries,
    *,
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
    min_coherence: float = 0.5,
    smooth: bool = False,
    f_max: float = 0.5,
    taper: str = "carspan_index",
    alpha_taper: float = 0.10,
) -> TransferResult:
    """Compute the Respiration->HR transfer function using the CARSPAN pipeline.

    Faithful port of ``T_AnaFunctions.pas:RunDFT`` + ``RunPDS`` +
    ``RunCrossSpectrum`` + ``RunTransfer`` for a single epoch.

    Parameters
    ----------
    series : CardioSeriesLike
        Heart-rate series exposing ``.times``, ``.ibi``, ``.labels``.
        Artefact-labelled beats are excluded via
        :func:`~spectHR.analysis.ibi_helpers.event_times_clean`.
    rsp_timeseries : TimeSeries
        Continuous respiration recording with ``.times`` (seconds) and
        ``.values`` (arbitrary units, e.g. Volts).  Linearly interpolated
        at R-peak times.  The time range should cover the cardiac epoch.
    bands : dict {name: (low_hz, high_hz)}, optional
        Frequency bands for which band-summary statistics are computed.
        Standard CARSPAN bands::

            {"VLF": (0.01, 0.04), "LF": (0.04, 0.15), "HF": (0.15, 0.40)}

    min_coherence : float
        Minimum squared coherence for a bin to contribute to the band
        modulus/phase means (CARSPAN ``MinCoh``, default 0.5).
    smooth : bool
        Apply 3-point triangular smoother to auto- and cross-spectra
        *before* computing transfer / coherence.  Use ``True`` for
        sliding-window (profile) analysis; leave ``False`` (default) for
        single-epoch spectral analysis.
    f_max : float
        Upper frequency limit of the native grid (default 0.5 Hz).
    taper : {"carspan_index", "scipy"}
        Window applied to the signal before the DFT.
        ``"carspan_index"`` matches the Pascal ``Taper`` function
        (5 % cosine bell by event index).
    alpha_taper : float
        Cosine-bell half-width per side (default 0.10 -> 5 % each side,
        matching the CARSPAN ``TaperPercent := 5`` default).

    Returns
    -------
    TransferResult
        Contains ``freqs``, ``modulus``, ``phase_wrapped``,
        ``phase_unwrapped``, ``coherence``, ``freq_resolution``,
        ``method="carspan_transfer"``, and optionally ``band_results``.

    Raises
    ------
    ValueError
        If fewer than 4 clean R-peaks are available, the recording is too
        short for the requested ``f_max``, or the frequency grid is empty.
    """
    # ------------------------------------------------------------------ #
    # 1. Extract clean R-peak times                                        #
    # ------------------------------------------------------------------ #
    rp_times = event_times_clean(series)
    if rp_times.size < 4:
        raise ValueError(
            f"Need at least 4 clean R-peaks for a transfer function, "
            f"got {rp_times.size}."
        )

    ibi_s = np.diff(rp_times)          # (N-1,) IBI durations in seconds
    ibi_ms = ibi_s * 1000.0
    n = ibi_s.size
    T = float(rp_times[-1] - rp_times[0])

    # ------------------------------------------------------------------ #
    # 2. Respiration sampled at R-peak times 1..N-1                       #
    # Aligned with the IBI DFT grid (cumulative times end at R-peaks 1-N-1)
    # ------------------------------------------------------------------ #
    rsp_vals = np.interp(
        rp_times[1:],
        rsp_timeseries.times,
        rsp_timeseries.values,
    )

    # ------------------------------------------------------------------ #
    # 3. Mean-subtract both signals (Pascal: NData := DataIn - Mean)      #
    # ------------------------------------------------------------------ #
    nd_ibi = ibi_ms  - float(np.mean(ibi_ms))
    nd_rsp = rsp_vals - float(np.mean(rsp_vals))

    # ------------------------------------------------------------------ #
    # 4. Taper and IBI-amplitude weights                                  #
    # Pascal: Amp := NData[i] * IData[i]/1000  (IData in ms -> /1000 = s) #
    # ------------------------------------------------------------------ #
    w, _ = _make_window(
        n_signal=n,
        T=T,
        taper=taper,
        window="hann",
        alpha_taper=alpha_taper,
        amplitude_correction=False,
    )
    amp_ibi = nd_ibi * w * ibi_s    # (ms x s) -- HR output amplitude
    amp_rsp = nd_rsp * w * ibi_s    # (resp_unit x s) -- Resp input amplitude

    # Cumulative IBI times -- the DFT evaluation grid
    # (Pascal: T accumulates IData from 0 inside SOC main loop)
    cum_times = np.cumsum(ibi_s)    # (N-1,) seconds from first beat

    # ------------------------------------------------------------------ #
    # 5. Native frequency grid (Df = 1/T, DC excluded)                   #
    # ------------------------------------------------------------------ #
    freqs, delta_f = _native_grid(T=T, f_max=f_max)
    if freqs.size == 0:
        raise ValueError(
            f"Frequency grid is empty (T={T:.1f}s, f_max={f_max}Hz). "
            "Recording is too short or f_max too low."
        )

    # ------------------------------------------------------------------ #
    # 6. Complex DFTs for both channels                                   #
    # ------------------------------------------------------------------ #
    dft_rsp = _compute_dft(freqs, cum_times, amp_rsp)  # respiration (input)
    dft_ibi = _compute_dft(freqs, cum_times, amp_ibi)  # HR / IBI (output)

    # ------------------------------------------------------------------ #
    # 7. Auto- and cross-spectra                                          #
    # Pascal: RunPDS (WindowSize=0 spectra / 3 profiles)                  #
    #         RunCrossSpectrum (same WindowSize)                           #
    # ------------------------------------------------------------------ #
    auto_rsp = _auto_spectrum(dft_rsp, T)
    auto_ibi = _auto_spectrum(dft_ibi, T)
    cross    = _cross_spectrum(dft_rsp, dft_ibi, T)

    if smooth:
        # Profile path: apply 3-point triangular smoother to spectra.
        # In Pascal this is AutoSpectrum(..., WindowSize=3) and
        # CrossSpectrum(..., WindowSize=3).
        auto_rsp = _smooth3(auto_rsp)
        auto_ibi = _smooth3(auto_ibi)
        cross    = _smooth3_complex(cross)

    # ------------------------------------------------------------------ #
    # 8. Transfer function, modulus, phase, coherence                     #
    # Pascal: RunTransfer                                                  #
    # ------------------------------------------------------------------ #
    H           = _transfer_function(cross, auto_rsp)
    mod         = _modulus(H)
    phase_w     = _phase_wrapped(H)
    phase_u     = _unwrap_phase(phase_w, thresh=np.pi, step=2.0 * np.pi)
    coh         = _coherence(cross, auto_rsp, auto_ibi)

    # ------------------------------------------------------------------ #
    # 9. Per-band summaries                                               #
    # ------------------------------------------------------------------ #
    band_out: Dict[str, BandTransfer] = {}
    if bands:
        n_freqs = freqs.size
        for name, (low_hz, high_hz) in bands.items():
            lo, hi = _band_slice(low_hz, high_hz, delta_f, n_freqs)
            wt_coh, n_pts  = _band_weighted_coherence(coh, auto_rsp, lo, hi)
            bmod,   n_coh  = _band_modulus_mean(mod,     coh, lo, hi, min_coherence)
            # CARSPAN Phase2 path: Caluculate_PhaseSum on wrapped phase
            bphs,   _      = _band_phase_mean(phase_w,   coh, lo, hi, min_coherence)
            # CARSPAN Phase  path: Caluculate_PhaseSum on unwrapped phase
            bphs_u, _      = _band_phase_mean(phase_u,   coh, lo, hi, min_coherence)
            band_out[name] = BandTransfer(
                weighted_coherence=wt_coh,
                modulus=bmod,
                phase=bphs,
                phase_unwrapped=bphs_u,
                n_points=n_pts,
                n_coherent=n_coh,
            )

    return TransferResult(
        freqs=freqs,
        modulus=mod,
        phase_wrapped=phase_w,
        phase_unwrapped=phase_u,
        coherence=coh,
        freq_resolution=delta_f,
        method="carspan_transfer",
        band_results=band_out if bands else None,
    )


def compute_transfer_profile(
    series,
    rsp_timeseries,
    *,
    bands: Dict[str, Tuple[float, float]],
    window_s: float,
    step_s: float,
    min_coherence: float = 0.5,
    f_max: float = 0.5,
    taper: str = "carspan_index",
    alpha_taper: float = 0.10,
) -> "TransferProfileResult":
    """Sliding-window band-transfer profile (CARSPAN ``RunTransfer`` profile path).

    Equivalent to calling :func:`compute_transfer` with ``smooth=True``
    (CARSPAN ``AutoSpectrum`` / ``CrossSpectrum`` ``WindowSize=3``) inside
    each window, then collecting the :class:`BandTransfer` summaries into
    ``(n_bands, n_windows)`` arrays -- exactly as
    ``T_AnaFunctions.pas:RunTransfer`` (profile branch, lines 2562-2608)
    feeds the band-summary loop in ``T_Output.pas``.

    The 3-point triangular smoother (``WindowSize=3``) applied by
    ``smooth=True`` is what makes the per-window coherence estimates
    fall below 1, matching CARSPAN's profile computation.

    Parameters
    ----------
    series : CardioSeriesLike
        Heart-rate series exposing ``.times``, ``.ibi``, ``.labels``,
        ``.view(t_start, t_end)``.
    rsp_timeseries : TimeSeries
        Continuous respiration recording (``.times``, ``.values``).
        Passed unchanged to :func:`compute_transfer`; interpolated at
        R-peak times inside each window.
    bands : dict {name: (low_hz, high_hz)}
        Frequency bands for which band-summary profiles are built.
        Must not be empty.
    window_s : float
        Window length in seconds.  Equivalent to the CARSPAN analysis
        epoch length used inside the profile computation.
    step_s : float
        Step between successive windows in seconds.  Must be strictly
        less than ``window_s`` (overlapping windows required).
    min_coherence : float
        Minimum squared coherence for a bin to contribute to band
        modulus / phase means (CARSPAN ``FMinCoh``, default 0.5).
    f_max : float
        Upper frequency limit in Hz (default 0.5).
    taper : {"carspan_index", "scipy"}
        DFT window type.  ``"carspan_index"`` reproduces the Pascal
        ``Taper`` (5 % cosine bell by event index).
    alpha_taper : float
        Cosine-bell half-width per side (default 0.10).

    Returns
    -------
    TransferProfileResult
        ``timestamps`` (window centres), ``band_names``, and
        ``(n_bands, n_windows)`` arrays for ``modulus``, ``phase``,
        ``phase_unwrapped``, ``weighted_coherence``, ``n_coherent``.
        Array cells are ``np.nan`` / 0 for windows with fewer than 4
        clean R-peaks or where the transfer computation raised an error.

    Raises
    ------
    ValueError
        If ``bands`` is empty, ``step_s >= window_s``, or the recording
        is shorter than one window.
    """
    if not bands:
        raise ValueError("bands must not be empty for a transfer profile.")
    if window_s <= 0 or step_s <= 0:
        raise ValueError("window_s and step_s must both be > 0.")
    if step_s >= window_s:
        raise ValueError(
            f"step_s ({step_s!r}s) must be strictly smaller than "
            f"window_s ({window_s!r}s) so windows overlap."
        )
    if series.times.size < 2:
        raise ValueError("Need at least 2 R-peaks for a transfer profile.")

    t0       = float(series.times[0])
    t_end    = float(series.times[-1])
    duration = t_end - t0

    if duration < window_s:
        raise ValueError(
            f"Recording too short ({duration:.1f} s) for "
            f"window_s={window_s} s."
        )

    band_names = list(bands.keys())
    n_bands    = len(band_names)
    n_windows  = int((duration - window_s) / step_s) + 1

    timestamps = np.empty(n_windows, dtype=np.float64)
    mod_grid   = np.full((n_bands, n_windows), np.nan)
    phw_grid   = np.full((n_bands, n_windows), np.nan)
    phu_grid   = np.full((n_bands, n_windows), np.nan)
    coh_grid   = np.full((n_bands, n_windows), np.nan)
    ncoh_grid  = np.zeros((n_bands, n_windows), dtype=int)

    for i in range(n_windows):
        win_start      = t0 + i * step_s
        win_end        = win_start + window_s
        timestamps[i]  = win_start + window_s / 2.0

        win_view = series.view(win_start, win_end)
        if win_view.times.size < 4:
            continue

        try:
            result = compute_transfer(
                win_view,
                rsp_timeseries,
                bands=bands,
                min_coherence=min_coherence,
                smooth=True,        # CARSPAN profile path: WindowSize=3
                f_max=f_max,
                taper=taper,
                alpha_taper=alpha_taper,
            )
        except Exception:
            continue

        if not result.band_results:
            continue

        for b, name in enumerate(band_names):
            bt = result.band_results.get(name)
            if bt is None:
                continue
            mod_grid[b, i]   = bt.modulus
            phw_grid[b, i]   = bt.phase
            phu_grid[b, i]   = bt.phase_unwrapped
            coh_grid[b, i]   = bt.weighted_coherence
            ncoh_grid[b, i]  = bt.n_coherent

    return TransferProfileResult(
        timestamps=timestamps,
        band_names=band_names,
        modulus=mod_grid,
        phase=phw_grid,
        phase_unwrapped=phu_grid,
        weighted_coherence=coh_grid,
        n_coherent=ncoh_grid,
        window_s=float(window_s),
        step_s=float(step_s),
        method="carspan_transfer",
    )
