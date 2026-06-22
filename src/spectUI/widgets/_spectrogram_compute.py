# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Display-side helpers for the spectrogram renderers.

The sliding-window PSD computation itself is the algorithm half and lives
in :mod:`spectHR.analysis.spectrogram`; ``SpectrogramData`` and
``fetch_spectrogram`` are re-exported here so the two renderers
(``spectrogramPlotWidget``, ``spectrogram3dPlotWidget``) keep a single
import point. What remains in this module is purely about *display*: grid
normalisation, the epoch-relative time axis, and surface downsampling.

Typical call sequence
---------------------
::

    from spectUI.widgets._spectrogram_compute import (
        SpectrogramData,
        fetch_spectrogram,
        normalise_grid,
        epoch_relative_times,
        downsample_for_surface,
    )

    data = fetch_spectrogram(series, label, window_s=30, step_s=5,
                             psd_method=method)
    if data.error:
        ...  # draw placeholder
    t_rel     = epoch_relative_times(data)
    norm_grid = normalise_grid(data.power_grid)
"""
from __future__ import annotations

import numpy as np

# Algorithm half lives in spectHR; re-exported so renderers import it here.
from spectHR.analysis.spectrogram import SpectrogramData

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

# Maximum number of bins on each axis when downsampling for a 3-D surface.
# Matplotlib's plot_surface builds one OpenGL polygon per grid cell, so very
# dense grids (> ~10 000 cells) cause visible lag on integrated GPU hardware.
# A cap of 80 × 80 keeps the cell count below 6 400 on every realistic
# dataset while preserving the qualitative shape of the surface.
#
# Rationale for 80: typical CARSPAN profile has 50 freq bins × 60 windows
# = 3 000 cells (no downsampling needed).  Welch at short step with a
# dense grid might reach 100 × 120 = 12 000; halving each axis to 50 × 60
# brings it back to 3 000.  80 is a comfortable head-room above the typical
# case while staying well inside the performance budget.
MAX_SURFACE_BINS: int = 80


# ---------------------------------------------------------------------------
# Shared utility functions used by both renderers
# ---------------------------------------------------------------------------


def normalise_grid(power_grid: np.ndarray) -> np.ndarray:
    """Map raw power values to the [0, 1] range across the whole epoch.

    The normalisation is epoch-local: the minimum and maximum are taken
    from finite values in the full grid, not per-window or per-frequency.
    This means a window with very low total power still reveals the
    *shape* of its spectral distribution (high-frequency detail) rather
    than appearing uniformly dark.

    Parameters
    ----------
    power_grid : ndarray, shape (n_freqs, n_windows)
        Raw PSD power as returned by :func:`fetch_spectrogram`.

    Returns
    -------
    ndarray, shape (n_freqs, n_windows)
        Values in [0, 1].  ``NaN`` cells remain ``NaN``.

    Raises
    ------
    ValueError
        If ``power_grid`` contains no finite values at all.
    """
    finite = power_grid[np.isfinite(power_grid)]
    if finite.size == 0:
        raise ValueError("power_grid contains no finite values, cannot normalise")

    p_min = float(np.nanmin(finite))
    p_max = float(np.nanmax(finite))

    # Guard against a flat grid (all power equal): shift p_max up by
    # one unit so the denominator is never zero.
    if p_max <= p_min:
        p_max = p_min + 1.0

    return (power_grid - p_min) / (p_max - p_min)


def epoch_relative_times(data: SpectrogramData) -> np.ndarray:
    """Convert absolute window-centre timestamps to epoch-relative seconds.

    The origin (t = 0) is aligned to the left edge of the *first*
    window, not to the first R-peak.  This matches the x-axis origin
    convention used by the Profile tab.

    Parameters
    ----------
    data : SpectrogramData
        As returned by :func:`fetch_spectrogram`.

    Returns
    -------
    ndarray, shape (n_windows,)
        Time in seconds from the left edge of the first analysis window.
    """
    # The first timestamp is the *centre* of the first window, so the
    # left edge of that window is half a window_s earlier.
    t0 = float(data.timestamps[0]) - data.window_s / 2.0
    return data.timestamps - t0


def downsample_for_surface(
    power_grid: np.ndarray,
    freqs:      np.ndarray,
    timestamps: np.ndarray,
    max_bins:   int = MAX_SURFACE_BINS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reduce the grid to at most ``max_bins × max_bins`` for 3-D rendering.

    ``matplotlib``'s ``plot_surface`` builds one OpenGL polygon per
    grid cell, so very dense grids cause visible lag on integrated GPU
    hardware.  This function applies uniform stride-based downsampling
    on both axes independently.

    The original ``power_grid`` is never modified, this works on a
    strided view and is only called by the 3-D renderer.

    Parameters
    ----------
    power_grid : ndarray, shape (n_freqs, n_windows)
        The full-resolution spectrogram matrix.
    freqs : ndarray, shape (n_freqs,)
        Frequency axis values in Hz.
    timestamps : ndarray, shape (n_windows,)
        Time axis values in seconds (absolute window centres).
    max_bins : int
        Maximum number of bins retained on each axis.
        Defaults to :data:`MAX_SURFACE_BINS`.

    Returns
    -------
    tuple of (downsampled_grid, downsampled_freqs, downsampled_timestamps)
        Each array has at most ``max_bins`` elements on its respective
        axis.  Lengths on the two axes may differ if the original aspect
        ratio is not square.
    """
    # Compute independent strides for frequency and time so a grid that
    # is wide but short (many windows, few frequency bins) is not
    # over-downsampled on the frequency axis.
    freq_stride = max(1, len(freqs)      // max_bins)
    time_stride = max(1, len(timestamps) // max_bins)

    ds_freqs      = freqs[::freq_stride]
    ds_timestamps = timestamps[::time_stride]
    ds_grid       = power_grid[::freq_stride, ::time_stride]

    return ds_grid, ds_freqs, ds_timestamps
