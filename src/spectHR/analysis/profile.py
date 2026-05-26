# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/profile.py
"""
Sliding-window band-power profile computation.

Standalone implementation of the CARSPAN ``RunProfileSommation`` pipeline
(``T_AnaFunctions.pas`` 2888-3056).

Public surface
--------------
compute_band_power_profile(series, *, window_s, step_s, ...) -> ProfileResult
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional, Tuple

import numpy as np

from spectHR.analysis.psd._config import (
    PsdMethod,
    _DEFAULT_PSD_METHOD,
    respiration_min,
    respiration_max,
)
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.psd._utils import ProfileResult
from spectHR.Tools.Logger import logger
from spectHR.Tools.RespirationSegmentation import mean_breath_frequency_hz
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.analysis._smoothing import smooth3 as _ma3  # CARSPAN MAW kernel (T_AnaFunctions.pas:595-643)


__all__ = ["compute_band_power_profile"]





def _strip_hz(unit_str: str) -> str:
    """Remove a trailing '/Hz' suffix from a unit label."""
    raw = str(unit_str).strip()
    for suffix in ("/Hz", "/hz", " /Hz", " /hz"):
        if raw.endswith(suffix):
            return raw[: -len(suffix)].rstrip()
    return raw


def _setup_profile_grid(
    series,
    *,
    window_s: float,
    step_s: float,
    context: str = "profile",
) -> Tuple[int, np.ndarray, float]:
    """Validate sliding-window parameters and build the window time-axis.

    Shared by :func:`compute_band_power_profile` and
    :func:`spectHR.analysis.transfer.compute_transfer_profile` so both
    pipelines enumerate windows on exactly the same arithmetic - the
    Delphi ``GetNrOfProfiles`` / ``GetProfileData`` rules
    (``T_AnaFunctions.pas`` 1115, 1153).

    Parameters
    ----------
    series : CardioSeriesLike
        Series exposing ``.times`` (sorted seconds).
    window_s, step_s : float
        Sliding-window length and step in seconds.  ``step_s`` must be
        strictly smaller than ``window_s`` so consecutive windows overlap.
    context : str
        Label used in error messages (e.g. ``"transfer profile"``) so the
        ValueError points the user at the right pipeline.

    Returns
    -------
    n_windows : int
        ``N = floor((T - W) / S) + 1`` where ``T = times[-1] - times[0]``.
    timestamps : (n_windows,) ndarray
        Window-centre times in seconds - pre-filled so callers can leave
        empty-window NaN cells without losing their time-axis entry.
    t0 : float
        Time of the first R-peak; window ``i`` spans
        ``[t0 + i * step_s,  t0 + i * step_s + window_s]``.

    Raises
    ------
    ValueError
        On non-positive parameters, ``step_s >= window_s``, a sub-2-peak
        series, or a series shorter than one window.
    """
    if window_s <= 0 or step_s <= 0:
        raise ValueError(
            f"window_s and step_s must both be > 0 "
            f"(got window_s={window_s}, step_s={step_s})."
        )
    if step_s >= window_s:
        raise ValueError(
            f"step_s ({step_s}) must be strictly smaller than "
            f"window_s ({window_s}) so the windows overlap."
        )
    if series.times.size < 2:
        raise ValueError(f"Need at least 2 R-peaks for a {context}.")

    t0       = float(series.times[0])
    t_end    = float(series.times[-1])
    duration = t_end - t0
    if duration < window_s:
        raise ValueError(
            f"View too short ({duration:.1f}s) for window={window_s}s."
        )
    n_windows  = int((duration - window_s) / step_s) + 1
    # Window centres t_i^c = t0 + i*step_s + W/2 (Delphi GetProfileData,
    # T_AnaFunctions.pas:1115). Pre-filled so windows that hit the < 4
    # R-peak gate still get a correct time-axis entry.
    timestamps = t0 + np.arange(n_windows) * step_s + window_s / 2.0
    return n_windows, timestamps, t0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_band_power_profile(
    series,
    *,
    window_s: float,
    step_s: float,
    psd_method: Optional[PsdMethod] = None,
    adaptive_source: str = "respiration_channel",
    smooth_breath_freq: bool = False,
) -> ProfileResult:
    """Sliding-window band-power profile (CARSPAN ``RunProfileSommation``).

    Faithful port of CARSPAN's ``RunAnalysis(Tag=1)`` profile pipeline
    from ``T_AnaFunctions.pas`` (``RunDFT`` 2032, ``RunPDS`` 2152,
    ``RunResample`` 2320, ``RunMAW`` 2421, ``RunProfileSommation``
    2888-3056).

    Parameters
    ----------
    series : CardioSeriesLike
        Must expose ``.times``, ``.ibi``, ``.labels``, ``.view()``,
        and optionally ``._pd`` (for respiration channel access).
    window_s : float
        Window length in seconds.
    step_s : float
        Step between successive windows in seconds.  Must be < ``window_s``.
    psd_method : PsdMethod, optional
        Explicit PSD configuration override.
    adaptive_source : {"respiration_channel", "psd_peak"}
        Where per-window breathing frequency comes from when an adaptive
        band is configured.
    smooth_breath_freq : bool
        Apply a 3-point MA to the breathing-frequency sequence before
        computing adaptive band edges.  Requires a two-pass run.

    Returns
    -------
    ProfileResult
        ``timestamps`` (window centres in s), ``band_names``,
        ``band_power`` of shape ``(n_bands, n_windows)``, ``unit``,
        ``method``, ``window_s``, ``step_s``, ``resp_freqs``.
    """
    # Validate parameters and build the time axis (delegates to the helper
    # shared with spectHR.analysis.transfer.compute_transfer_profile).
    n_windows, timestamps, t0 = _setup_profile_grid(
        series, window_s=window_s, step_s=step_s, context="profile",
    )

    method = psd_method if psd_method is not None else _DEFAULT_PSD_METHOD

    # CARSPAN manual 3.3.5: "the interpolation to a fixed frequency of
    # 0.01 Hz is not applied" for the profile compute path.
    profile_method = replace(
        method,
        carspan=replace(method.carspan, resample_to_display_grid=False),
    )

    band_names = list(method.bands.keys())
    bands_list = list(method.bands.items())
    n_bands    = len(band_names)
    grid       = np.full((n_bands, n_windows), np.nan, dtype=np.float64)

    has_adaptive_band = any(b.respiration_band for _, b in bands_list)
    resp_freqs: "np.ndarray | None" = (
        np.full(n_windows, np.nan, dtype=np.float64)
        if has_adaptive_band else None
    )

    # Locate the respiration series once, before the window loop.
    rsp_series = None
    pd = getattr(series, "_pd", None)
    if pd is not None:
        rsp_map = getattr(pd, "rsp_map", None)
        if rsp_map:
            rsp_series = next(iter(rsp_map.values()))

    if (
        has_adaptive_band
        and adaptive_source == "respiration_channel"
        and rsp_series is None
    ):
        logger.warning(
            "compute_band_power_profile: adaptive_source='respiration_channel' "
            "but no respiration channel is loaded in this dataset. "
            "Falling back to psd_peak for every window."
        )

    unit = ""

    if has_adaptive_band:
        # Phase A: collect per-window resp_freqs and cache PSDs.
        psd_cache: list = [None] * n_windows

        for i in range(n_windows):
            # Window span; timestamps were pre-filled by _setup_profile_grid.
            win_start = t0 + i * step_s
            win_end   = win_start + window_s
            win_view  = series.view(win_start, win_end)
            if win_view.times.size < 4:
                continue
            try:
                psd_result = PSDEngine(win_view).for_band_power(profile_method)
            except Exception:
                continue
            psd_cache[i] = psd_result
            if not unit:
                unit = _strip_hz(psd_result.unit)

            if adaptive_source == "respiration_channel" and rsp_series is not None:
                rsp_view = rsp_series.view(win_start, win_end)
                rf = mean_breath_frequency_hz(rsp_view)
                if rf is not None and resp_freqs is not None:
                    resp_freqs[i] = rf

            # Fall back to psd_peak if respiration_channel yielded nothing.
            use_psd_peak = adaptive_source == "psd_peak" or (
                adaptive_source == "respiration_channel"
                and resp_freqs is not None
                and not np.isfinite(resp_freqs[i])
            )
            if use_psd_peak:
                for _, band in bands_list:
                    if band.respiration_band:
                        mask = (
                            (psd_result.freqs >= band.low)
                            & (psd_result.freqs <= band.high)
                        )
                        if mask.any() and resp_freqs is not None:
                            peak_idx = int(np.argmax(psd_result.power[mask]))
                            resp_freqs[i] = float(psd_result.freqs[mask][peak_idx])
                        break  # only one adaptive band at a time

        # Phase B: optionally smooth the breathing-frequency sequence.
        if smooth_breath_freq and resp_freqs is not None:
            finite_mask = np.isfinite(resp_freqs)
            if finite_mask.any():
                rf_clean = np.where(finite_mask, resp_freqs, 0.0)
                smoothed = _ma3(rf_clean)
                smoothed[~finite_mask] = np.nan
                resp_freqs[:] = smoothed

        # Phase C: band power from cached PSDs + (smoothed) freqs.
        for i in range(n_windows):
            psd_result = psd_cache[i]
            if psd_result is None:
                continue
            resp_freq_max = (
                float(psd_result.freqs[-1])
                if psd_result.freqs.size else float("inf")
            )
            window_resp_freq: "float | None" = (
                float(resp_freqs[i])
                if (resp_freqs is not None and np.isfinite(resp_freqs[i]))
                else None
            )

            for b, (name, band) in enumerate(bands_list):
                if band.respiration_band and window_resp_freq is not None:
                    lo = respiration_min(band, window_resp_freq, resp_freq_max)
                    hi = respiration_max(band, window_resp_freq, resp_freq_max)
                else:
                    lo, hi = band.low, band.high
                if hi <= lo:
                    continue
                grid[b, i] = band_power_rectangular(
                    psd_result.freqs, psd_result.power, lo, hi
                )

    else:
        # Single-pass: no adaptive bands, no PSD caching needed.
        for i in range(n_windows):
            # Window span; timestamps were pre-filled by _setup_profile_grid.
            win_start = t0 + i * step_s
            win_end   = win_start + window_s
            win_view  = series.view(win_start, win_end)
            if win_view.times.size < 4:
                continue
            try:
                psd_result = PSDEngine(win_view).for_band_power(profile_method)
            except Exception:
                continue

            for b, (name, band) in enumerate(bands_list):
                lo, hi = band.low, band.high
                if hi <= lo:
                    continue
                grid[b, i] = band_power_rectangular(
                    psd_result.freqs, psd_result.power, lo, hi
                )

            if not unit:
                unit = _strip_hz(psd_result.unit)

    return ProfileResult(
        timestamps=timestamps,
        band_names=band_names,
        band_power=grid,
        unit=unit,
        method=method.algorithm,
        window_s=float(window_s),
        step_s=float(step_s),
        resp_freqs=resp_freqs,
    )
