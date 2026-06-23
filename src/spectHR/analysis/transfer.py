# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/transfer.py
"""
Transfer function computation (input -> HR coupling).

Faithful Python port of the CARSPAN ``RunTransfer`` pipeline
(``T_AnaFunctions.pas`` lines 492-809, 2178-2610).

The input channel is selectable (``input_signal``): the classic respiration
-> HR transfer, or a blood-pressure -> HR transfer (spectral baroreflex
sensitivity) driven by per-beat systolic or diastolic pressure.  The output
channel is always the IBI (HR) series.

Pipeline
--------
For a single epoch the steps are:

1.  Sample the chosen input onto the IBI beat grid: interpolate the
    continuous respiration TimeSeries at R-peak times, or extract per-beat
    systolic / diastolic blood-pressure values.
2.  Mean-subtract both the IBI and respiration signals and apply the
    CARSPAN cosine-bell taper, then weight by the local IBI duration
    (Pascal ``Amp := NData[i] * IData[i]/1000``).
3.  Compute the complex DFT for both signals at the cumulative-IBI time
    grid (the CARSPAN IBI-amplitude SOC convention, Eq. 3.21 + the
    analogous non-IBI column path).
4.  Form the auto-spectra ``(2x10^6/T) . |DFT|^2`` and complex
    cross-spectrum ``conj(DFT_in).DFT_out.(2x10^6/T)``; optionally
    apply the 3-point triangular frequency smoother used in the
    profile path (``T_AnaFunctions.pas:574-583``, WindowSize=3) with
    Pascal's exact edge policy (left mirror, right replicate-centre).
5.  Transfer function  ``H = Cross / Auto_in``.
6.  Modulus ``|H|``, wrapped phase ``arctan2(Im, Re)``, unwrapped phase
    (threshold pi, step 2pi), squared coherence ``|Cross|^2/(Auto_in.Auto_out)``.
7.  Per-band summaries: power-weighted coherence, coherence-gated modulus
    and phase means (``Caluculate_WeightedCoherenceSum``,
    ``Caluculate_ModulusSum``, ``Caluculate_PhaseSum``).

Public surface
--------------
``compute_transfer(series, input_timeseries, *, input_signal="rsp", ...) -> TransferResult``

Notes
-----
For a *single unsmoothed epoch* the squared coherence is mathematically
1 at every non-zero bin (each DFT has exactly one realization). Set
``smooth=True`` to apply the 3-point triangular smoother to the spectra
before computing coherence; this gives sub-unity coherence estimates
useful for sliding-window (profile) analyses.

References
----------
CARSPAN manual 3.3.1-3.3.3; ``T_AnaFunctions.pas`` functions
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

# Pascal Cross/AutoSpectrum WindowSize=3 (T_AnaFunctions.pas:443-487)
from spectHR.analysis._smoothing import smooth3_triangular as _smooth3
from spectHR.analysis.bp_metrics import bp_beat_parameters
from spectHR.analysis.ibi_helpers import event_times_clean
from spectHR.analysis.profile import _setup_profile_grid
from spectHR.analysis.psd._carspan import _dft, _make_window, _native_grid

__all__ = [
    "BandTransfer",
    "TransferResult",
    "TransferProfileResult",
    "INPUT_SIGNALS",
    "INPUT_SIGNAL_LABELS",
    "input_signal_label",
    "compute_transfer",
    "compute_transfer_profile",
    "transfer_summary_scalars",
]


# ---------------------------------------------------------------------------
# Selectable transfer-function input signal
# ---------------------------------------------------------------------------
#
# The transfer function H = Cross / Auto_in measures coupling from an *input*
# signal to the IBI (HR) output.  Historically the input was hard-wired to
# respiration (respiration -> HR).  ``input_signal`` now lets the caller pick
# what drives the input channel:
#
#   "rsp"    - continuous respiration waveform, interpolated at R-peak times.
#              The classic respiratory-sinus-arrhythmia transfer.
#   "bp_sys" - per-beat systolic blood pressure (from the BP waveform).
#   "bp_dia" - per-beat diastolic blood pressure (from the BP waveform).
#              BP -> IBI transfer is the spectral baroreflex-sensitivity path.
#
# For "rsp" the second positional argument is the respiration TimeSeries; for
# the "bp_*" kinds it is the continuous blood-pressure TimeSeries.
INPUT_SIGNAL_RSP = "rsp"
INPUT_SIGNAL_BP_SYS = "bp_sys"
INPUT_SIGNAL_BP_DIA = "bp_dia"
INPUT_SIGNALS = (INPUT_SIGNAL_RSP, INPUT_SIGNAL_BP_SYS, INPUT_SIGNAL_BP_DIA)

# Human-readable names for the transfer input signal, used in plot
# legends / titles so the user can tell at a glance which datatype drove
# the transfer (respiration -> HR vs baroreflex BP -> HR).
INPUT_SIGNAL_LABELS = {
    INPUT_SIGNAL_RSP: "Respiration",
    INPUT_SIGNAL_BP_SYS: "BP systolic",
    INPUT_SIGNAL_BP_DIA: "BP diastolic",
}

# Physical unit of the transfer-function modulus for each input signal.
# The output is always the IBI series (in ms). For BP inputs the
# engineering unit of the input is mmHg, giving ms/mmHg for the modulus.
# Respiration has no standard engineering unit (it comes from an
# accelerometer or thermistor whose raw values are dimensionless / V),
# so we leave it blank and let the axis label read just "|H(f)|".
MODULUS_UNITS = {
    INPUT_SIGNAL_RSP:    "",
    INPUT_SIGNAL_BP_SYS: "ms/mmHg",
    INPUT_SIGNAL_BP_DIA: "ms/mmHg",
}


def input_signal_label(input_signal: str) -> str:
    """Return a human-readable name for *input_signal* (falls back to itself)."""
    return INPUT_SIGNAL_LABELS.get(input_signal, str(input_signal))


def modulus_unit(input_signal: str) -> str:
    """Return the physical unit of |H(f)| for *input_signal*.

    ``"ms/mmHg"`` for blood-pressure inputs (IBI in ms, BP in mmHg).
    Empty string for respiration (no standardised engineering unit).
    """
    return MODULUS_UNITS.get(input_signal, "")


def _fill_nans(values: np.ndarray) -> np.ndarray:
    """Bridge NaNs so the input signal is DFT-safe.

    Internal NaNs are linearly interpolated over the beat index; leading /
    trailing NaNs are extended with the nearest finite value (``np.interp``
    edge behaviour).  The CARSPAN cross-spectral DFT cannot accept NaN, and
    the beat-by-beat BP parameters carry NaN at flat-line / artefact beats, so
    bridging keeps the transfer estimate defined across the whole window.

    An all-NaN array is returned unchanged; callers detect and reject it.
    """
    v = np.asarray(values, dtype=float).copy()
    finite = np.isfinite(v)
    if not np.any(finite) or np.all(finite):
        return v
    idx = np.arange(v.size)
    v[~finite] = np.interp(idx[~finite], idx[finite], v[finite])
    return v


def _input_beat_signal(
    input_timeseries,
    rp_times: np.ndarray,
    input_signal: str,
) -> np.ndarray:
    """Sample the chosen input signal onto the IBI beat grid.

    Returns an ``(N-1,)`` array (``N = rp_times.size``) aligned with the
    cumulative-IBI DFT grid used for the output (IBI) channel: element ``i``
    corresponds to the cardiac interval ``[R_i, R_{i+1}]`` and is placed at the
    grid time of ``R_{i+1}`` - the same convention the respiration path has
    always used (interpolation at ``rp_times[1:]``).

    Parameters
    ----------
    input_timeseries : TimeSeries-like
        ``.times`` / ``.values`` for either the respiration waveform
        (``input_signal="rsp"``) or the blood-pressure waveform
        (``input_signal="bp_sys"`` / ``"bp_dia"``).
    rp_times : np.ndarray
        Clean R-peak times (seconds).
    input_signal : str
        One of :data:`INPUT_SIGNALS`.

    Raises
    ------
    ValueError
        For an unknown ``input_signal`` or when a BP input yields no valid
        beats at all (every beat flat-line / artefact).
    """
    if input_signal == INPUT_SIGNAL_RSP:
        return np.interp(
            rp_times[1:],
            input_timeseries.times,
            input_timeseries.values,
        )

    if input_signal in (INPUT_SIGNAL_BP_SYS, INPUT_SIGNAL_BP_DIA):
        beats = bp_beat_parameters(
            np.asarray(input_timeseries.times, dtype=float),
            np.asarray(input_timeseries.values, dtype=float),
            rp_times,
        )
        key = "sbp" if input_signal == INPUT_SIGNAL_BP_SYS else "dbp"
        vals = beats[key]          # (N-1,) - one value per cardiac interval
        if not np.any(np.isfinite(vals)):
            raise ValueError(
                f"No valid {key.upper()} beats for the transfer input "
                "(every beat is flat-line / artefact)."
            )
        return _fill_nans(vals)

    raise ValueError(
        f"Unknown input_signal {input_signal!r}; "
        f"expected one of {INPUT_SIGNALS}."
    )


def _precompute_full_beat_input(
    input_timeseries,
    full_rp_times: np.ndarray,
    input_signal: str,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Extract the raw per-beat BP input once over the whole recording.

    Returns ``(full_rp_times, raw_beat_values)`` for the blood-pressure
    inputs, or ``None`` for ``"rsp"`` (whose per-window interpolation is
    already cheap, so there is nothing to amortise).

    ``raw_beat_values`` keeps the NaNs that :func:`bp_beat_parameters`
    places on flat-line / artefact beats - they are bridged *per window*
    by :func:`_resolve_input_beats` so the interpolation stays local to
    the window, exactly as the un-cached path does.  The point of this
    helper is to call the expensive :func:`bp_beat_parameters` (whose
    flat-line test scans the high-rate BP waveform) **once** instead of
    once per sliding window in :func:`compute_transfer_profile`.
    """
    if input_signal not in (INPUT_SIGNAL_BP_SYS, INPUT_SIGNAL_BP_DIA):
        return None
    beats = bp_beat_parameters(
        np.asarray(input_timeseries.times, dtype=float),
        np.asarray(input_timeseries.values, dtype=float),
        np.asarray(full_rp_times, dtype=float),
    )
    key = "sbp" if input_signal == INPUT_SIGNAL_BP_SYS else "dbp"
    return np.asarray(full_rp_times, dtype=float), beats[key]


def _resolve_input_beats(
    input_timeseries,
    rp_times: np.ndarray,
    input_signal: str,
    full_beat_input: Optional[Tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    """Window input-beat values, reusing a full-recording BP precompute.

    When *full_beat_input* is supplied (a ``(full_rp_times, raw_vals)``
    pair from :func:`_precompute_full_beat_input`) and the input is a BP
    signal, the window's per-beat values are a contiguous slice of the
    precomputed array: the clean R-peaks of a time-window are exactly a
    slice of the recording's clean R-peaks, and each beat value depends
    only on the BP waveform between two R-peaks, never on the window.
    The slice is verified against *rp_times*; any mismatch falls back to
    the direct per-window extraction so correctness never depends on the
    fast path.
    """
    if (
        full_beat_input is not None
        and input_signal in (INPUT_SIGNAL_BP_SYS, INPUT_SIGNAL_BP_DIA)
    ):
        full_rp, full_raw = full_beat_input
        n = rp_times.size - 1
        a = int(np.searchsorted(full_rp, rp_times[0]))
        if (
            n >= 1
            and a + rp_times.size <= full_rp.size
            and np.allclose(full_rp[a : a + rp_times.size], rp_times)
        ):
            seg = full_raw[a : a + n]
            if not np.any(np.isfinite(seg)):
                raise ValueError(
                    "No valid BP beats for the transfer input in this window "
                    "(every beat is flat-line / artefact)."
                )
            return _fill_nans(seg)
    return _input_beat_signal(input_timeseries, rp_times, input_signal)


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
        ``Sum(coh[k] x psd_in[k]) / Sum(psd_in[k])``.
        Faithful to ``Caluculate_WeightedCoherenceSum``
        (``T_AnaFunctions.pas:883``).
    modulus : float
        Mean modulus over the band, restricted to bins where
        ``coherence[k] >= min_coherence``.
        Faithful to ``Caluculate_ModulusSum``
        (``T_AnaFunctions.pas:963``).
    phase : float
        Mean **wrapped** phase (radians) over coherent bins in the band
        (CARSPAN ``Phase2`` path - ``Phase(TransList)`` without
        ``UnwrapPhase``; ``Caluculate_PhaseSum``,
        ``T_AnaFunctions.pas:935``).
    phase_unwrapped : float
        Mean **unwrapped** (within-epoch) phase (radians) over coherent
        bins in the band (CARSPAN ``Phase`` path - ``Phase(TransList)``
        mutated by ``UnwrapPhase(thresh=pi, step=2pi)`` before
        ``Caluculate_PhaseSum``).
    n_points : int
        Total number of frequency bins inside the band.
    n_coherent : int
        Number of bins where ``coherence >= min_coherence``.  When this
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
        Frequency grid in Hz (native df = 1/T grid, DC excluded).
    modulus : (N,) ndarray
        ``|H(f)|`` - amplitude gain of the transfer function at each
        frequency.  Units are ``output_unit / input_unit``: e.g. ms/V for
        respiration->HR (HR in ms, respiration in Volts), or ms/mmHg for
        BP->HR (the baroreflex-sensitivity gain).
    phase_wrapped : (N,) ndarray
        ``arctan2(Im H, Re H)`` in radians, range ``(-pi, +pi]``.
        Faithful to ``T_AnaFunctions.pas:Phase()``.
    phase_unwrapped : (N,) ndarray
        Phase unwrapped across the spectrum using CARSPAN's threshold-
        based convention (threshold = pi, step = 2pi).
        Faithful to ``T_AnaFunctions.pas:UnwrapPhase()``.
    coherence : (N,) ndarray
        Squared coherence ``|C(f)|^2`` in ``[0, 1]``.  For a single
        un-smoothed epoch this is 1 everywhere (by construction); set
        ``smooth=True`` in :func:`compute_transfer` to obtain sub-unity
        estimates.
    freq_resolution : float
        Frequency resolution ``df = 1/T`` in Hz.
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
    series of overlapping sliding windows - exactly as CARSPAN's
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
        ``UnwrapPhase(thresh=pi, step=2pi)``).
    weighted_coherence : (n_bands, n_windows) float array
        Power-weighted mean coherence per band per window
        (``Caluculate_WeightedCoherenceSum``).
    n_coherent : (n_bands, n_windows) int array
        Number of frequency bins with coherence >= ``min_coherence``
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
# Low-level signal-processing helpers.
# Each one is a direct port of a single named Pascal function.
# ---------------------------------------------------------------------------


def _compute_dft(
    freqs: np.ndarray,
    times: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """Complex DFT: ``X(f) = Sum w_i . exp(-2*pi*j . f . t_i)``.

    Thin wrapper around :func:`spectHR.analysis.psd._carspan._dft`, which
    returns the real and imaginary parts as separate arrays for use
    inside the PSD pipeline (component-wise subtraction is cheaper than
    complex multiplies). The transfer pipeline needs the result as a
    standard complex array for the conjugate-multiplies in
    :func:`_cross_spectrum`, :func:`_coherence`, etc., so we combine the
    two halves here.
    """
    re, im = _dft(freqs, times, weights)
    return re + 1j * im


def _auto_spectrum(dft: np.ndarray, T: float) -> np.ndarray:
    """Auto-spectrum: ``(2x10^6/T) . |DFT|^2``.

    Faithful to ``T_AnaFunctions.pas:AutoSpectrum()`` (WindowSize=0)::

        Dou := 1000000 * (2 * cd_real(conj(X).X) / T)
    """
    return (2.0e6 / T) * (dft.real ** 2 + dft.imag ** 2)


def _cross_spectrum(
    dft_in: np.ndarray,
    dft_out: np.ndarray,
    T: float,
) -> np.ndarray:
    """Complex cross-spectrum: ``conj(DFT_in) . DFT_out . (2x10^6/T)``.

    Faithful to ``T_AnaFunctions.pas:CrossSpectrum()`` (WindowSize=0)::

        cd_conj(conCValue1, CValue1^)
        cd_mul(DCom, conCValue1, CValue2^)
        cd_DivRe(DCom, DCom, T/2000000)
    """
    return np.conj(dft_in) * dft_out * (2.0e6 / T)



def _transfer_function(cross: np.ndarray, auto_in: np.ndarray) -> np.ndarray:
    """Transfer function ``H = Cross / Auto_in`` (complex / real).

    Faithful to ``T_AnaFunctions.pas:Transfer()``::

        if PDou^ = 0 then H := 0+0j
        else           cd_divRe(PDCom^, CValue^, PDou^)
    """
    H = np.zeros(len(cross), dtype=complex)
    ok = auto_in != 0.0
    H[ok] = cross[ok] / auto_in[ok]
    return H


def _modulus(H: np.ndarray) -> np.ndarray:
    """``|H(f)| = sqrt(conj(H).H)``.

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
    offset (``ModFactor x step``) is accumulated separately::

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
    """Squared coherence ``|Cross|^2 / (Auto_in x Auto_out)``.

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
    """``Sum(coh[k].psd_in[k]) / Sum(psd_in[k])`` over ``[lo, hi]`` inclusive.

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
    input_timeseries,
    *,
    input_signal: str = INPUT_SIGNAL_RSP,
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
    min_coherence: float = 0.5,
    f_max: float = 0.5,
    _smooth: bool = True,
    taper: str = "carspan_index",
    alpha_taper: float = 0.10,
    _full_beat_input: Optional[Tuple[np.ndarray, np.ndarray]] = None,
) -> TransferResult:
    """Compute an input->HR transfer function using the CARSPAN pipeline.

    Faithful port of ``T_AnaFunctions.pas:RunDFT`` + ``RunPDS`` +
    ``RunCrossSpectrum`` + ``RunTransfer`` for a single epoch.

    The input channel is selectable via *input_signal*: the classic
    respiration->HR transfer (default), or a blood-pressure->HR transfer
    (spectral baroreflex sensitivity) driven by per-beat systolic or diastolic
    pressure.  The output channel is always the IBI (HR) series.

    Parameters
    ----------
    series : series-like
        Heart-rate series exposing ``.times``, ``.ibi``, ``.labels``.
        Artefact-labelled beats are excluded via
        :func:`~spectHR.analysis.ibi_helpers.event_times_clean`.
    input_timeseries : TimeSeries
        Continuous recording with ``.times`` (seconds) and ``.values`` that
        drives the input channel.  For ``input_signal="rsp"`` this is the
        respiration waveform (linearly interpolated at R-peak times); for
        ``input_signal="bp_sys"`` / ``"bp_dia"`` it is the blood-pressure
        waveform, from which per-beat systolic / diastolic values are
        extracted (CARSPAN ``CalcDataColBPSYS`` / ``BPDIA``).  The time range
        should cover the cardiac epoch.
    input_signal : {"rsp", "bp_sys", "bp_dia"}
        Which signal drives the transfer-function input (see
        :data:`INPUT_SIGNALS`).  Default ``"rsp"`` reproduces the legacy
        respiration->HR behaviour exactly.
    bands : dict {name: (low_hz, high_hz)}, optional
        Frequency bands for which band-summary statistics are computed.
        Standard CARSPAN bands::

            {"VLF": (0.01, 0.04), "LF": (0.04, 0.15), "HF": (0.15, 0.40)}

    min_coherence : float
        Minimum squared coherence for a bin to contribute to the band
        modulus/phase means (CARSPAN ``MinCoh``, default 0.5).
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
    if input_signal not in INPUT_SIGNALS:
        raise ValueError(
            f"Unknown input_signal {input_signal!r}; "
            f"expected one of {INPUT_SIGNALS}."
        )

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
    # 2. Input signal sampled onto the IBI beat grid (beats 1..N-1)       #
    # Aligned with the IBI DFT grid (cumulative times end at R-peaks 1-N-1).
    # "rsp": interpolated waveform; "bp_sys"/"bp_dia": per-beat BP values.  #
    # ------------------------------------------------------------------ #
    in_vals = _resolve_input_beats(
        input_timeseries, rp_times, input_signal, _full_beat_input
    )

    # ------------------------------------------------------------------ #
    # 3. Mean-subtract both signals (Pascal: NData := DataIn - Mean)      #
    # ------------------------------------------------------------------ #
    nd_ibi = ibi_ms - float(np.mean(ibi_ms))
    nd_in  = in_vals - float(np.mean(in_vals))

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
    amp_in  = nd_in  * w * ibi_s    # (input_unit x s) -- input amplitude

    # Cumulative IBI times -- the DFT evaluation grid
    # (Pascal: T accumulates IData from 0 inside SOC main loop)
    cum_times = np.cumsum(ibi_s)    # (N-1,) seconds from first beat

    # ------------------------------------------------------------------ #
    # 5. Native frequency grid (df = 1/T, DC excluded)                   #
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
    dft_in  = _compute_dft(freqs, cum_times, amp_in)   # chosen input signal
    dft_ibi = _compute_dft(freqs, cum_times, amp_ibi)  # HR / IBI (output)

    # ------------------------------------------------------------------ #
    # 7. Auto- and cross-spectra                                          #
    # Pascal: RunPDS (WindowSize=0 spectra / 3 profiles)                  #
    #         RunCrossSpectrum (same WindowSize)                           #
    # ------------------------------------------------------------------ #
    auto_in  = _auto_spectrum(dft_in, T)
    auto_ibi = _auto_spectrum(dft_ibi, T)
    cross    = _cross_spectrum(dft_in, dft_ibi, T)

    if _smooth:
        # Profile path: 3-point triangular smoother (Pascal WindowSize=3,
        # T_AnaFunctions.pas 443-487/519-570).  Not exposed publicly,
        # compute_transfer_profile passes _smooth=True; single-epoch
        # callers never need it.
        auto_in  = _smooth3(auto_in)
        auto_ibi = _smooth3(auto_ibi)
        cross    = _smooth3(cross)

    # ------------------------------------------------------------------ #
    # 8. Transfer function, modulus, phase, coherence                     #
    # Pascal: RunTransfer                                                  #
    # ------------------------------------------------------------------ #
    H           = _transfer_function(cross, auto_in)
    mod         = _modulus(H)
    phase_w     = _phase_wrapped(H)
    phase_u     = _unwrap_phase(phase_w, thresh=np.pi, step=2.0 * np.pi)
    coh         = _coherence(cross, auto_in, auto_ibi)

    # ------------------------------------------------------------------ #
    # 9. Per-band summaries                                               #
    # ------------------------------------------------------------------ #
    band_out: Dict[str, BandTransfer] = {}
    if bands:
        n_freqs = freqs.size
        for name, (low_hz, high_hz) in bands.items():
            lo, hi = _band_slice(low_hz, high_hz, delta_f, n_freqs)
            wt_coh, n_pts  = _band_weighted_coherence(coh, auto_in, lo, hi)
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


def transfer_summary_scalars(
    tf_res: "TransferResult",
    *,
    min_coherence: float,
    f_max: float,
) -> dict:
    """Flatten a :class:`TransferResult` into the named scalar export columns.

    For each band with a :class:`BandTransfer` summary, emits
    ``{band}_tf_modulus``, ``{band}_tf_phase_w`` (wrapped), ``{band}_tf_phase_u``
    (unwrapped), ``{band}_tf_coherence`` (weighted), ``{band}_tf_n_points`` and
    ``{band}_tf_n_coherent``; plus the run-level metadata ``tf_method``,
    ``tf_freq_resolution``, ``tf_min_coherence`` and ``tf_f_max``.

    Centralising the column-naming here keeps the CSV/HDF5 column set defined in
    the analysis layer rather than in the UI export code.  The settings
    (*smooth*, *min_coherence*, *f_max*) are echoed into the metadata columns;
    they are taken as arguments because the result object does not carry them.
    """
    scalars: dict = {}
    for bname, bt in (tf_res.band_results or {}).items():
        if bt is None:
            continue
        scalars[f"{bname}_tf_modulus"]    = float(bt.modulus)
        scalars[f"{bname}_tf_phase_w"]    = float(bt.phase)
        scalars[f"{bname}_tf_phase_u"]    = float(bt.phase_unwrapped)
        scalars[f"{bname}_tf_coherence"]  = float(bt.weighted_coherence)
        scalars[f"{bname}_tf_n_points"]   = int(bt.n_points)
        scalars[f"{bname}_tf_n_coherent"] = int(bt.n_coherent)

    scalars["tf_method"]          = tf_res.method or ""
    scalars["tf_freq_resolution"] = float(tf_res.freq_resolution)
    scalars["tf_min_coherence"]   = float(min_coherence)
    scalars["tf_f_max"]           = float(f_max)
    return scalars


def compute_transfer_profile(
    series,
    input_timeseries,
    *,
    input_signal: str = INPUT_SIGNAL_RSP,
    bands: Dict[str, Tuple[float, float]],
    window_s: float,
    step_s: float,
    min_coherence: float = 0.5,
    f_max: float = 0.5,
    taper: str = "carspan_index",
    alpha_taper: float = 0.10,
) -> "TransferProfileResult":
    """Sliding-window band-transfer profile (CARSPAN ``RunTransfer`` profile path).

    Calls :func:`compute_transfer` with the 3-point triangular spectral
    smoother (CARSPAN ``AutoSpectrum`` / ``CrossSpectrum`` ``WindowSize=3``)
    enabled inside each window, then collects the :class:`BandTransfer`
    summaries into ``(n_bands, n_windows)`` arrays, exactly as
    ``T_AnaFunctions.pas:RunTransfer`` (profile branch, lines 2562-2608)
    feeds the band-summary loop in ``T_Output.pas``.

    The smoother is always applied in the profile path (not user-configurable):
    it is what allows per-window coherence estimates to fall below 1,
    matching CARSPAN's profile computation.

    Parameters
    ----------
    series : series-like
        Heart-rate series exposing ``.times``, ``.ibi``, ``.labels``,
        ``.view(t_start, t_end)``.
    input_timeseries : TimeSeries
        Continuous recording (``.times``, ``.values``) that drives the
        transfer-function input.  Passed unchanged to
        :func:`compute_transfer` inside each window: for
        ``input_signal="rsp"`` it is the respiration waveform (interpolated
        at R-peak times); for ``input_signal="bp_sys"`` / ``"bp_dia"`` it is
        the blood-pressure waveform (per-beat systolic / diastolic values).
    input_signal : {"rsp", "bp_sys", "bp_dia"}
        Which signal drives the transfer-function input (see
        :data:`INPUT_SIGNALS`).  Default ``"rsp"``.
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

    # Validate parameters and build the time axis (delegates to the helper
    # shared with spectHR.analysis.profile.compute_band_power_profile).
    n_windows, timestamps, t0 = _setup_profile_grid(
        series, window_s=window_s, step_s=step_s, context="transfer profile",
    )

    band_names = list(bands.keys())
    n_bands    = len(band_names)

    # Extract the per-beat BP input once over the whole recording, then let
    # each window slice it (see _resolve_input_beats).  bp_beat_parameters'
    # flat-line test scans the high-rate BP waveform, so calling it once
    # rather than once per overlapping window is the dominant speed-up for
    # the BP -> HR (baroreflex) profile.  None for "rsp" (interpolation per
    # window is already cheap).
    full_beat_input = _precompute_full_beat_input(
        input_timeseries, event_times_clean(series), input_signal,
    )

    mod_grid   = np.full((n_bands, n_windows), np.nan)
    phw_grid   = np.full((n_bands, n_windows), np.nan)
    phu_grid   = np.full((n_bands, n_windows), np.nan)
    coh_grid   = np.full((n_bands, n_windows), np.nan)
    ncoh_grid  = np.zeros((n_bands, n_windows), dtype=int)

    for i in range(n_windows):
        # Window span; timestamps were pre-filled by _setup_profile_grid.
        win_start = t0 + i * step_s
        win_end   = win_start + window_s

        win_view = series.window(win_start, win_end)
        if win_view.times.size < 4:
            continue

        try:
            result = compute_transfer(
                win_view,
                input_timeseries,
                input_signal=input_signal,
                bands=bands,
                min_coherence=min_coherence,
                _smooth=True,
                f_max=f_max,
                taper=taper,
                alpha_taper=alpha_taper,
                _full_beat_input=full_beat_input,
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
