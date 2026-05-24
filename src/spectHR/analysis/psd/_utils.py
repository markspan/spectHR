# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/psd/_utils.py
"""Shared helpers and result types for all PSD back-ends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.stats import chi2


@dataclass(frozen=True)
class PSDResult:
    """Immutable container for a PSD computation result.

    Returned by every ``compute_*_psd`` function. Compute functions fill it
    with the raw unit (e.g. ``"ms²/Hz"`` for Welch) and the algorithm name;
    PSDEngine applies unit conversion and band-range masking before handing
    the result to the caller.
    """

    freqs: np.ndarray
    power: np.ndarray
    unit: str = ""
    method: str = ""
    ci_lower: Optional[np.ndarray] = None
    ci_upper: Optional[np.ndarray] = None


@dataclass(frozen=True)
class ProfileResult:
    """Immutable container for a spectral-profile computation result.

    A profile is the time-resolved band-power of a recording: the same
    band-power integration that PSDResult would yield for a whole epoch,
    recomputed inside each of a series of overlapping sliding windows
    (CARSPAN manual §3.3.5, Eq. 3.34 / 3.35). The result is a 2-D array
    with one band-power time series per band.

    Fields
    ------
    timestamps : (n_windows,) float array
        Window-centre times in seconds.
    band_names : list[str]
        Band names in the row order of ``band_power``.
    band_power : (n_bands, n_windows) float array
        Integrated power per band per window. ``np.nan`` when a window had
        too few samples.
    unit : str
        Display unit (e.g. ``"mMI²"``). No ``/Hz`` suffix.
    method : str
        PSD algorithm used inside each window.
    window_s : float
        Window length (seconds).
    step_s : float
        Step between successive windows (seconds).
    resp_freqs : (n_windows,) float array or None
        Per-window breathing frequency used as adaptive band centre. ``None``
        when no adaptive band was configured.
    """

    timestamps: np.ndarray
    band_names: list
    band_power: np.ndarray
    unit: str = ""
    method: str = ""
    window_s: float = 0.0
    step_s: float = 0.0
    resp_freqs: Optional[np.ndarray] = None


def _chi2_ci(
    power: np.ndarray,
    dof: "float | np.ndarray",
    alpha: float,
) -> "tuple[np.ndarray, np.ndarray]":
    """Chi-squared confidence interval for a PSD estimate."""
    if alpha <= 0:
        return np.zeros_like(power), np.full_like(power, np.inf)
    if alpha >= 1:
        return power.copy(), power.copy()
    dof_arr = np.asarray(dof, dtype=float)
    lo = chi2.ppf(alpha / 2, dof_arr)
    hi = chi2.ppf(1.0 - alpha / 2, dof_arr)
    return dof_arr * power / hi, dof_arr * power / lo


def _resolve_window(window_spec):
    """Translate a ``"X% cosine bell"`` spec into a scipy ``("tukey", ...)`` tuple."""
    if isinstance(window_spec, str) and "cosine bell" in window_spec:
        try:
            percent = float(window_spec.split("%")[0].strip())
            return ("tukey", percent / 50.0)
        except (ValueError, IndexError):
            pass
    return window_spec


def _require_min_samples(n, min_n, context):
    """Raise ``ValueError`` when sample count falls below the minimum."""
    if n < min_n:
        raise ValueError(
            f"Need at least {min_n} valid samples for {context}, got {n}."
        )
