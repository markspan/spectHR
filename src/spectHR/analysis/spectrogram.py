# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Sliding-window PSD grid (spectrogram) computation.

The 2-D heat-map and 3-D surface renderers both need exactly the same
sliding-window PSD grid: a matrix of shape ``(n_freqs, n_windows)``
together with its frequency and time axes and an optional per-window
breathing-frequency overlay.

This is the algorithm half of that pipeline and lives in ``spectHR`` so it
shares the same window arithmetic as :mod:`spectHR.analysis.profile` and
stays usable headlessly. The display-only helpers (grid normalisation,
epoch-relative time axis, surface downsampling) live with the renderers in
``spectUI``.

Public surface
--------------
``SpectrogramData``            - the compute → render exchange container.
``fetch_spectrogram(...)``     - compute one epoch's grid; never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from spectHR.logger import logger
from spectHR.signal.respiration import mean_breath_frequency_hz
from spectHR.analysis.psd._config import PsdMethod, _DEFAULT_PSD_METHOD
from spectHR.analysis.psd._engine import PSDEngine


__all__ = ["SpectrogramData", "fetch_spectrogram"]


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass
class SpectrogramData:
    """All data needed to render one epoch spectrogram tile.

    This is the only object exchanged between the compute layer and the
    rendering layer.  Renderers must not call ``PSDEngine`` themselves;
    all spectral computation belongs here.

    Attributes
    ----------
    label : str
        Human-readable epoch name, used as the tile title.
    timestamps : ndarray, shape (n_windows,)
        Absolute time of each window centre in seconds.  Convert to
        epoch-relative seconds with the renderer's ``epoch_relative_times``.
    freqs : ndarray, shape (n_freqs,)
        Frequency axis in Hz, common to every column of ``power_grid``.
    power_grid : ndarray, shape (n_freqs, n_windows)
        Per-window PSD power.  ``NaN`` where a window could not be
        computed (too few beats, engine failure).  Not normalised.
    unit : str
        Physical unit of the power values (e.g. ``"mMI²"`` or ``"ms²"``).
    method : str
        Name of the PSD method used (e.g. ``"carspan_strict"``).
    window_s : float
        Analysis window length in seconds.
    step_s : float
        Window slide step in seconds.
    resp_freqs : ndarray or None, shape (n_windows,)
        Per-window breathing frequency in Hz, ``NaN`` where unavailable.
        ``None`` when no finite value was recovered for any window.
    error : str or None
        Non-``None`` when the epoch could not be computed.  All array
        fields are empty in that case.  Renderers should draw a
        placeholder tile when ``error`` is set.
    """

    label:       str
    timestamps:  np.ndarray          # (n_windows,)   absolute window centres
    freqs:       np.ndarray          # (n_freqs,)     Hz
    power_grid:  np.ndarray          # (n_freqs, n_windows)   raw PSD power
    unit:        str
    method:      str
    window_s:    float
    step_s:      float
    resp_freqs:  np.ndarray | None = None   # (n_windows,) or None
    error:       str | None        = None


# ---------------------------------------------------------------------------
# Main compute function
# ---------------------------------------------------------------------------


def fetch_spectrogram(
    series,
    label: str,
    *,
    window_s: float,
    step_s: float,
    psd_method: PsdMethod | None = None,
    adaptive_source: str = "respiration_channel",
    rsp_phases=None,
) -> SpectrogramData:
    """Compute the sliding-window PSD grid for one cardio series.

    This function never raises.  All failures produce a
    :class:`SpectrogramData` with ``error`` set and empty array fields,
    so renderers can draw a labelled placeholder tile without any
    ``try/except`` boilerplate of their own.

    Parameters
    ----------
    series
        An ``Events`` (or compatible) object exposing ``.times`` and
        ``.window(t_start, t_end)``.
    label : str
        Epoch name, stored verbatim in the returned ``SpectrogramData``.
    window_s : float
        Length of each analysis window in seconds.
    step_s : float
        Slide step in seconds.  Must be less than ``window_s``.
    psd_method : PsdMethod or None
        PSD configuration dataclass.  When ``None`` the module-level
        ``_DEFAULT_PSD_METHOD`` is used.
    adaptive_source : str
        Controls how the per-window breathing frequency is estimated.

        ``"respiration_channel"``
            Stage 1: ``mean_breath_frequency_hz`` on *rsp_phases* sliced to
            the window.  Stage 2 (PSD peak in the HF band) runs as a fallback
            for windows where Stage 1 produces no result.

        ``"psd_peak"``
            Stage 1 is skipped; every window uses the PSD-peak
            fallback.  Chosen when no respiration channel is loaded,
            or when the Profile settings select this source.

    Returns
    -------
    SpectrogramData
        On success all fields are populated.
        On failure ``error`` is set and array fields are empty.

    Notes
    -----
    The CARSPAN display-grid resample step (interpolation to 0.01 Hz)
    is disabled per-window, matching the profile-widget convention.
    This preserves the native frequency resolution inside each window
    and avoids aliasing when windows are short.

    The common frequency grid is taken from the first successfully
    computed window.  Subsequent windows that land on a different grid
    (e.g. slightly shorter windows at the tail of an epoch) are
    interpolated onto the common grid; extrapolated bins are set to
    ``NaN``.
    """
    # ---- sentinel value returned on any early exit -------------------
    empty = SpectrogramData(
        label=label,
        timestamps=np.array([]),
        freqs=np.array([]),
        power_grid=np.empty((0, 0)),
        unit="",
        method="",
        window_s=window_s,
        step_s=step_s,
    )

    try:
        method = psd_method if psd_method is not None else _DEFAULT_PSD_METHOD

        # Disable the CARSPAN display-grid resample per window so the
        # native frequency resolution survives.  This mirrors exactly
        # what the band-power profile does for its per-window integrals.
        per_window_method = replace(
            method,
            carspan=replace(method.carspan, resample_to_display_grid=False),
        )

        if series.times.size == 0:
            return replace(empty, error="Empty series")

        t0       = float(series.times[0])
        duration = float(series.times[-1]) - t0

        if duration < window_s:
            return replace(empty, error="Epoch shorter than window")

        n_windows = int((duration - window_s) / step_s) + 1
        if n_windows < 1:
            return replace(empty, error="No window fits in epoch")

        # ---- respiration setup (mirrors profile.py exactly) ----------
        # The breath phases are supplied by the caller (the epoch's INH/EXH
        # Intervals); each window is sliced from them inside the loop.
        rsp_series = rsp_phases

        # PSD-peak fallback search range: use the first band whose
        # respiration_band flag is set, else fall back to standard HF.
        _HF_LOW_DEFAULT  = 0.15   # Hz, standard HF lower edge
        _HF_HIGH_DEFAULT = 0.40   # Hz, standard HF upper edge
        resp_band_low  = _HF_LOW_DEFAULT
        resp_band_high = _HF_HIGH_DEFAULT
        for _band in method.bands.values():
            if _band.respiration_band:
                resp_band_low  = _band.low
                resp_band_high = _band.high
                break

        # ---- window loop ---------------------------------------------
        common_freqs: np.ndarray | None = None
        psd_cache:    dict[int, object] = {}    # window index -> PSDResult
        method_label = ""
        unit         = ""
        resp_freqs_arr = np.full(n_windows, np.nan, dtype=np.float64)

        for i in range(n_windows):
            win_start = t0 + i * step_s
            win_end   = win_start + window_s
            win_view  = series.window(win_start, win_end)

            # Four beats is the minimum the PSD engine will accept.
            if win_view.times.size < 4:
                continue

            try:
                psd_result = PSDEngine(win_view).for_band_power(per_window_method)
            except Exception as exc:
                logger.debug("Spectrogram: window %d skipped, %s", i, exc)
                continue

            psd_cache[i] = psd_result

            # The first successful window defines the reference grid.
            if common_freqs is None and psd_result.freqs.size:
                common_freqs = psd_result.freqs.copy()
                method_label = psd_result.method or ""
                unit         = psd_result.unit   or ""

            # ---- Stage 1: RSP channel --------------------------------
            # Only attempted when the caller requested "respiration_channel"
            # and a series is actually loaded.
            if adaptive_source == "respiration_channel" and rsp_series is not None:
                try:
                    rsp_view = rsp_series.window(win_start, win_end)
                    rf = mean_breath_frequency_hz(rsp_view)
                    if rf is not None:
                        resp_freqs_arr[i] = float(rf)
                except Exception as exc:
                    logger.debug(
                        "Spectrogram: resp-freq RSP stage failed for window %d, %s",
                        i, exc,
                    )

            # ---- Stage 2: PSD peak fallback --------------------------
            # Always runs when adaptive_source == "psd_peak".
            # Also runs as a fallback when Stage 1 left this window NaN.
            if not np.isfinite(resp_freqs_arr[i]) and psd_result.freqs.size:
                mask = (
                    (psd_result.freqs >= resp_band_low)
                    & (psd_result.freqs <= resp_band_high)
                )
                if mask.any():
                    peak_idx = int(np.argmax(psd_result.power[mask]))
                    resp_freqs_arr[i] = float(psd_result.freqs[mask][peak_idx])

        # ---- assemble the output grid --------------------------------
        if common_freqs is None or common_freqs.size == 0:
            return replace(empty, error="No spectra could be computed")

        n_freqs = common_freqs.size
        grid    = np.full((n_freqs, n_windows), np.nan, dtype=np.float64)

        for i, psd_result in psd_cache.items():
            if psd_result.freqs.size == 0:
                continue
            if np.array_equal(psd_result.freqs, common_freqs):
                # Fast path: grids are identical, direct assignment.
                grid[:, i] = psd_result.power
            else:
                # Slow path: interpolate onto the common grid.
                # Bins outside the window's native range become NaN
                # so the grid boundary stays clean.
                grid[:, i] = np.interp(
                    common_freqs, psd_result.freqs, psd_result.power,
                    left=np.nan, right=np.nan,
                )

        # Window-centre timestamps (absolute seconds).
        timestamps = np.array(
            [t0 + i * step_s + window_s / 2.0 for i in range(n_windows)],
            dtype=np.float64,
        )

        # Only carry resp_freqs if at least one window yielded a value.
        resp_freqs: np.ndarray | None = (
            resp_freqs_arr if np.any(np.isfinite(resp_freqs_arr)) else None
        )

        return SpectrogramData(
            label=label,
            timestamps=timestamps,
            freqs=common_freqs,
            power_grid=grid,
            unit=unit,
            method=method_label,
            window_s=window_s,
            step_s=step_s,
            resp_freqs=resp_freqs,
        )

    except Exception as exc:
        return replace(empty, error=f"Spectrogram compute failed: {exc}")
