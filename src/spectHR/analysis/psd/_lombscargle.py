# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/psd/_lombscargle.py
"""Lomb-Scargle power spectral density for IBI series (output: ms²/Hz)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal as sp_signal

from spectHR.analysis.psd._utils import (
    PSDResult,
    _chi2_ci,
    _require_min_samples,
)


@dataclass(frozen=True)
class LombscargleOptions:
    """Configuration for ``compute_lombscargle_psd``."""

    nfreqs: int = 1000
    """Number of frequency evaluation points across ``[f_min, f_max]``."""

    fmin_floor: float = 1e-4
    """Lower frequency floor in Hz."""

    units: str = "mMI²"
    """Output unit hint: ``"mMI²"`` or ``"ms²"``."""


_DEFAULT_LS_OPTIONS = LombscargleOptions()


def compute_lombscargle_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    f_max: float = 0.5,
    options: Optional[LombscargleOptions] = None,
) -> PSDResult:
    """Lomb-Scargle PSD with chi-squared confidence intervals.

    Returns ``power`` in ms²/Hz. Unit conversion to mMI²/Hz is done by PSDEngine.
    """
    opts = options if options is not None else _DEFAULT_LS_OPTIONS

    nfreqs = int(opts.nfreqs)
    fmin_floor = float(opts.fmin_floor)

    N = ibi_times_s.size
    _require_min_samples(N, 4, "Lomb-Scargle PSD")

    T = float(ibi_times_s[-1] - ibi_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")

    f_min = max(1.0 / T, fmin_floor)
    freqs = np.linspace(f_min, f_max, nfreqs)

    pgram = sp_signal.lombscargle(
        ibi_times_s,
        ibi_values_ms - np.mean(ibi_values_ms),
        2.0 * np.pi * freqs,
        normalize=False,
    )
    power = (2.0 * T / N) * pgram

    f_range = float(freqs[-1] - freqs[0])
    M = max(1, int(np.floor(2.0 * f_range * T)))
    dof_per_bin = max(2.0, 2.0 * M / len(freqs))

    ci_lower, ci_upper = _chi2_ci(power, dof=dof_per_bin, alpha=alpha_ci)
    return PSDResult(
        freqs=freqs,
        power=power,
        unit="ms²/Hz",
        method="lombscargle",
        ci_lower=ci_lower,
        ci_upper=ci_upper,
    )
