# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/psd/_welch.py
"""Welch power spectral density for IBI series (output: ms²/Hz)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal
from scipy.interpolate import interp1d

from spectHR.analysis.psd._utils import (
    PSDResult,
    _chi2_ci,
    _require_min_samples,
    _resolve_window,
)


@dataclass(frozen=True)
class WelchOptions:
    """Configuration for ``compute_welch_psd``."""

    fs: float = 4.0
    """Resampling frequency in Hz used before Welch averaging."""

    nperseg: int = 256
    """Samples per Welch segment."""

    noverlap: int = 128
    """Overlap (samples) between consecutive segments."""

    nfft: Optional[int] = None
    """FFT length; falls through to ``nperseg`` when None."""

    window: str = "hann"
    """``scipy.signal.get_window`` name, or ``"quadratic"`` for the
    Welch/parabolic window used by VU-DAMS (see :func:`_quadratic_window`)."""

    units: str = "mMI²"
    """Output unit hint: ``"mMI²"`` (normalised) or ``"ms²"`` (raw)."""


_DEFAULT_WELCH_OPTIONS = WelchOptions()


def _quadratic_window(n: int) -> np.ndarray:
    """Welch (parabolic / quadratic) window of length *n*.

    .. math::

        w[k] = 1 - \\left(\\frac{2k}{N-1} - 1\\right)^2, \\quad k = 0,\\dots,N-1

    This is the window VU-DAMS applies per 1024-sample segment before the DFT
    (DAMS manual §5.3.1 / Appendix A).  It is zero at both endpoints, reaches
    its maximum of 1.0 at the centre, and tapers with a smooth parabolic
    profile — identical to what P.D. Welch (1967) originally called "the
    modified periodogram window."  scipy's ``signal.get_window`` does not
    expose it by name, so it is constructed here as a NumPy array.
    """
    if n < 2:
        return np.ones(n, dtype=float)
    k = np.arange(n, dtype=float)
    return 1.0 - (2.0 * k / (n - 1) - 1.0) ** 2


def compute_welch_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    options: Optional[WelchOptions] = None,
) -> PSDResult:
    """Welch PSD of an IBI series with chi-squared confidence intervals.

    Returns ``power`` in ms²/Hz. Unit conversion to mMI²/Hz is done by PSDEngine.
    """
    opts = options if options is not None else _DEFAULT_WELCH_OPTIONS

    fs = float(opts.fs)
    nperseg = int(opts.nperseg)
    noverlap = int(opts.noverlap)
    nfft = int(opts.nfft) if opts.nfft is not None else None
    window = _resolve_window(opts.window)

    _require_min_samples(ibi_times_s.size, 4, "Welch PSD")

    dt = 1.0 / fs
    t_uniform = np.arange(float(ibi_times_s[0]), float(ibi_times_s[-1]), dt)
    ibi_resampled = interp1d(
        ibi_times_s, ibi_values_ms, kind="cubic", fill_value="extrapolate",
    )(t_uniform)

    n_samples = len(ibi_resampled)
    if nperseg > n_samples:
        nperseg = n_samples
    if noverlap >= nperseg:
        noverlap = nperseg // 2

    # Build the actual window array for "quadratic" (VU-DAMS parabolic window).
    # For all other strings / tuples scipy resolves the name via get_window.
    if isinstance(window, str) and window == "quadratic":
        w_arr = _quadratic_window(nperseg)
    else:
        w_arr = signal.get_window(window, nperseg, fftbins=False).astype(float)

    freqs, power = signal.welch(
        ibi_resampled,
        fs=fs,
        window=w_arr,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=nfft,
        detrend="constant",
        scaling="density",
    )

    step = nperseg - noverlap
    n_segments = max(1, 1 + (n_samples - nperseg) // step)
    w_sq = float(np.dot(w_arr, w_arr))
    if step < nperseg and n_segments > 1 and w_sq > 0.0:
        rho = float(np.dot(w_arr[: nperseg - step], w_arr[step:])) / w_sq
        dof = 2.0 * n_segments / (1.0 + 2.0 * (1.0 - 1.0 / n_segments) * rho ** 2)
    else:
        dof = float(2 * n_segments)

    ci_lower, ci_upper = _chi2_ci(power, dof, alpha_ci)
    return PSDResult(
        freqs=freqs,
        power=power,
        unit="ms²/Hz",
        method="welch",
        ci_lower=ci_lower,
        ci_upper=ci_upper,
    )
