# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/detrend.py
"""
Smoothness-priors detrending for IBI tachograms (Tarvainen et al., 2002).

A regularised detrending method that removes slow, non-stationary trends
from an inter-beat-interval series **without** the band-edge distortion a
plain high-pass filter introduces. It is the de-facto standard
pre-processing step in modern HRV pipelines (it is built into Kubios).

The estimated trend is

    z_trend = (I + λ² · D₂ᵀ D₂)⁻¹ · z

where ``D₂`` is the discrete second-difference operator and ``λ`` (lambda)
controls how aggressively slow components are removed: larger ``λ`` removes
more of the low frequencies. The stationary residual returned to the
caller is ``z − z_trend``.

This is a pure-numpy/scipy routine with no Qt or matplotlib dependency, so
it lives in the headless library. It is wired into
:class:`~spectHR.analysis.psd._engine.PSDEngine` as an **optional**
pre-conditioning step for the tachogram-based PSD methods (Welch,
Lomb-Scargle); it is disabled by default (``λ = 0``) and never alters the
faithful CARSPAN spectral paths.

Reference
---------
Tarvainen, M. P., Ranta-aho, P. O., & Karjalainen, P. A. (2002). An
advanced detrending method with application to HRV analysis. *IEEE
Transactions on Biomedical Engineering*, 49(2), 172-175.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

__all__ = ["smoothness_priors_detrend"]


def smoothness_priors_detrend(x: np.ndarray, lam: float = 500.0) -> np.ndarray:
    """Return the stationary residual of *x* after smoothness-priors detrending.

    Parameters
    ----------
    x : np.ndarray
        1-D series (e.g. IBI values in ms), indexed by beat.
    lam : float
        Regularisation parameter ``λ``. ``λ <= 0`` disables detrending and
        the input is returned unchanged. Larger values remove slower
        trends; ``500`` is a reasonable default for a beat-indexed IBI
        series (roughly a 0.03-0.04 Hz high-pass corner at typical heart
        rates).

    Returns
    -------
    np.ndarray
        ``x - trend``, the zero-mean stationary component. Returned
        unchanged when the series is too short (< 4 samples) or ``λ <= 0``.
    """
    x = np.asarray(x, dtype=float)
    n = x.size
    if n < 4 or lam is None or lam <= 0:
        return x.copy()

    identity = sparse.identity(n, format="csc")
    # Second-order difference operator D₂ (shape (n-2, n)).
    d2 = sparse.diags(
        diagonals=[1.0, -2.0, 1.0],
        offsets=[0, 1, 2],
        shape=(n - 2, n),
    ).tocsc()

    a = (identity + (float(lam) ** 2) * (d2.transpose() @ d2)).tocsc()
    trend = spsolve(a, x)
    return x - trend
