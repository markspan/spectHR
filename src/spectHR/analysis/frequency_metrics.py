# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/frequency_metrics.py
"""
Frequency-domain HRV metrics.

The standard band powers (``fullrange_power``, ``vlf_power``, ``lf_power``,
``hf_power``) and ``lf_hf_ratio`` are registered as single-valued
``@epoch_metric`` functions, so each contributes one column to the parameters
table exactly like the time-domain metrics.

These functions are **dual-mode**:

* Called directly with a bare ``CardioSeriesLike`` (and optionally an explicit
  ``psd_method``) they integrate that band on a freshly-computed PSD — the
  backward-compatible signature external scripts and the test-suite rely on.
* Called by :meth:`~spectHR.DataSet.PhysioData.PhysioData.epoched_parameters_table`
  they receive an :class:`~spectHR.analysis.epoch_context.EpochContext`, read
  the workspace ``psd_method`` from it, and reuse its cached PSD so all five
  metrics share a single spectral computation per epoch.

Because the workspace lets the researcher rename or add bands, only the four
conventional band names are decorated here; any **non-standard** band still
gets a ``{name}_power`` column from the dynamic loop in
``epoched_parameters_table`` (the "hybrid" arrangement).  When a configured
method has no band of the conventional name (e.g. ``LF`` was renamed) the
matching metric simply yields ``NaN``.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.registry import epoch_metric
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.psd._config import _DEFAULT_PSD_METHOD

# Lower-cased ``{name}_power`` columns owned by the decorated metrics below.
# ``epoched_parameters_table`` consults this set so its dynamic band loop does
# not double-emit these columns.
STANDARD_BAND_POWER_COLUMNS = frozenset(
    {"fullrange_power", "vlf_power", "lf_power", "hf_power"}
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _resolve_method(series, psd_method):
    """Pick the PSD method for *series*.

    Resolution order:

    1. An explicit *psd_method* argument always wins.
    2. An :class:`EpochContext` carries ``psd_method`` (possibly ``None``); the
       table path uses it, and a configured ``None`` means "no band powers"
       (the caller returns ``NaN``).
    3. A bare series has no ``psd_method`` attribute → fall back to the default
       method, matching the historical direct-call behaviour.

    Returns the method, or ``None`` to signal "configured but no method →
    yield NaN".
    """
    if psd_method is not None:
        return psd_method
    if hasattr(series, "psd_method"):        # EpochContext
        return series.psd_method             # may be None → caller yields NaN
    return _DEFAULT_PSD_METHOD               # bare series, standalone call


def _band_power(series, band_name: str, psd_method=None) -> float:
    """Integrate one named band using *psd_method* (or the default if None).

    Internal helper shared by the decorated band-power metrics and any external
    callers that want a single-band scalar.  When *series* is an
    :class:`EpochContext` its cached :attr:`~EpochContext.psd` is reused;
    otherwise a PSD is computed on the spot.  Raises ``KeyError`` when the band
    name is absent from the method (mirroring the historical contract).
    """
    method = psd_method if psd_method is not None else _DEFAULT_PSD_METHOD
    if band_name not in method.bands:
        raise KeyError(f"Unknown band '{band_name}'.")
    band = method.bands[band_name]
    psd_res = getattr(series, "psd", None)   # cached on EpochContext, else None
    if psd_res is None:
        psd_res = PSDEngine(series).for_band_power(method)
    return float(
        band_power_rectangular(psd_res.freqs, psd_res.power, band.low, band.high)
    )


def _named_band_power(series, band_name: str, psd_method=None) -> float:
    """``_band_power`` wrapped to return ``NaN`` instead of raising/erroring."""
    try:
        method = _resolve_method(series, psd_method)
        if method is None:                   # table call without a method
            return np.nan
        if band_name not in method.bands:    # band renamed / absent
            return np.nan
        return _band_power(series, band_name, method)
    except (KeyError, AttributeError, ValueError):
        return np.nan


# ---------------------------------------------------------------------------
# Registered band-power metrics
# ---------------------------------------------------------------------------

@epoch_metric
def fullrange_power(series, psd_method=None) -> float:
    """Power across the FullRange band."""
    return _named_band_power(series, "FullRange", psd_method)


@epoch_metric
def vlf_power(series, psd_method=None) -> float:
    """Power in the very-low-frequency band."""
    return _named_band_power(series, "VLF", psd_method)


@epoch_metric
def lf_power(series, psd_method=None) -> float:
    """Power in the low-frequency band."""
    return _named_band_power(series, "LF", psd_method)


@epoch_metric
def hf_power(series, psd_method=None) -> float:
    """Power in the high-frequency band."""
    return _named_band_power(series, "HF", psd_method)


@epoch_metric
def lf_hf_ratio(series, psd_method=None) -> float:
    """LF/HF ratio. Historically read as sympatho-vagal balance, but that
    interpretation is not supported by current evidence (Billman 2013;
    Reyes del Paso et al. 2013) — LF reflects mixed autonomic influences,
    not a clean sympathetic index. Report the ratio descriptively."""
    try:
        method = _resolve_method(series, psd_method)
        if method is None:
            return np.nan
        if "LF" not in method.bands or "HF" not in method.bands:
            return np.nan
        lf = _band_power(series, "LF", method)
        hf = _band_power(series, "HF", method)
        if not np.isfinite(lf) or not np.isfinite(hf) or hf == 0.0:
            return np.nan
        return float(lf / hf)
    except (KeyError, AttributeError, ValueError):
        return np.nan
