# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/Tools/Profile.py
"""
Sliding-window band-power profile computation.

This module contains the standalone implementation of the CARSPAN
``RunProfileSommation`` pipeline (``T_AnaFunctions.pas`` 2888–3056).
It was extracted from ``CardioMetricsMixin`` so the algorithm can be
developed, tested, and reasoned about independently of the series class.

Public surface
--------------
compute_band_power_profile(series, *, window_s, step_s, ...) -> ProfileResult

``CardioMetricsMixin.band_power_profile`` is a thin wrapper that calls
this function; existing call sites need no changes.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

import numpy as np

from spectHR.Tools.PSD._psd_config import (
    PsdMethod,
    _DEFAULT_PSD_METHOD,
    respiration_min,
    respiration_max,
)
from spectHR.Tools.PSD._band_power import band_power_rectangular
from spectHR.Tools.PSD._psd_utils import ProfileResult
from spectHR.Tools.Logger import logger


__all__ = ["compute_band_power_profile"]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resolve_psd_method(series, override: Optional[PsdMethod]) -> PsdMethod:
    """Pick the PsdMethod: explicit override → series attribute → module default."""
    if override is not None:
        return override
    instance_attr = getattr(series, "psd_method", None)
    if instance_attr is not None:
        return instance_attr
    return _DEFAULT_PSD_METHOD


def _ma3(arr: np.ndarray) -> np.ndarray:
    """Pascal-faithful 3-point moving average (same kernel as the display smoother).

    Boundary weights match CARSPAN's ``MAW`` pass:
        out[0]   = 3/8 · arr[0] + 5/8 · arr[1]
        out[N-1] = 5/8 · arr[N-2] + 3/8 · arr[N-1]
    """
    if arr.size < 3:
        return arr.copy()
    out = np.empty_like(arr, dtype=np.float64)
    out[1:-1] = (arr[:-2] + arr[1:-1] + arr[2:]) / 3.0
    out[0]    = 3.0 / 8.0 * arr[0]  + 5.0 / 8.0 * arr[1]
    out[-1]   = 5.0 / 8.0 * arr[-2] + 3.0 / 8.0 * arr[-1]
    return out


def _strip_hz(unit_str: str) -> str:
    """Remove a trailing '/Hz' suffix from a unit label."""
    raw = str(unit_str).strip()
    for suffix in ("/Hz", "/hz", " /Hz", " /hz"):
        if raw.endswith(suffix):
            return raw[: -len(suffix)].rstrip()
    return raw


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
    2888–3056).  See ``CardioMetricsMixin.band_power_profile`` for the
    full step-by-step docstring.

    Parameters
    ----------
    series : CardioSeriesLike
        Must implement ``.times``, ``.ibi``, ``.labels``, ``.view()``,
        ``._psd_for_band_power()``, and optionally ``._pd``.
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
    # Validation
    if window_s <= 0 or step_s <= 0:
        raise ValueError("window_s and step_s must both be > 0.")
    if step_s >= window_s:
        raise ValueError(
            f"step_s ({step_s}) must be strictly smaller than "
            f"window_s ({window_s}) so the windows overlap."
        )

    method = _resolve_psd_method(series, psd_method)

    if series.times.size < 2:
        raise ValueError("Need at least 2 R-peaks for a profile.")

    # CARSPAN manual §3.3.5: "the interpolation to a fixed frequency of
    # 0.01 Hz is not applied" for the profile compute path.
    profile_method = replace(
        method,
        carspan=replace(method.carspan, resample_to_display_grid=False),
    )

    # Step 1: window enumeration
    t0       = float(series.times[0])
    t_end    = float(series.times[-1])
    duration = t_end - t0
    if duration < window_s:
        raise ValueError(
            f"View too short ({duration:.1f}s) for window={window_s}s."
        )
    n_windows  = int((duration - window_s) / step_s) + 1
    band_names = list(method.bands.keys())
    bands_list = list(method.bands.items())
    n_bands    = len(band_names)
    grid       = np.full((n_bands, n_windows), np.nan, dtype=np.float64)
    timestamps = np.empty(n_windows, dtype=np.float64)

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
            win_start = t0 + i * step_s
            win_end   = win_start + window_s
            timestamps[i] = win_start + window_s / 2.0
            win_view = series.view(win_start, win_end)
            if win_view.times.size < 4:
                continue
            try:
                psd_result = win_view._psd_for_band_power(profile_method)
            except Exception:
                continue
            psd_cache[i] = psd_result
            if not unit:
                unit = _strip_hz(psd_result.unit)

            if adaptive_source == "respiration_channel" and rsp_series is not None:
                rsp_view = rsp_series.view(win_start, win_end)
                rf = rsp_view.mean_breath_frequency_hz()
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
            win_start = t0 + i * step_s
            win_end   = win_start + window_s
            timestamps[i] = win_start + window_s / 2.0
            win_view = series.view(win_start, win_end)
            if win_view.times.size < 4:
                continue
            try:
                psd_result = win_view._psd_for_band_power(profile_method)
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
