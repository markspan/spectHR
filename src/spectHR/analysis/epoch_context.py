# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/epoch_context.py
"""
Per-epoch evaluation context for ``@epoch_metric`` functions.

``PhysioData.epoched_parameters_table`` builds one :class:`EpochContext` per
active epoch and passes it to every registered metric.  The context is a thin
superset of the epoch's ``CardioSeriesView``: it **delegates** every unknown
attribute (``times``, ``ibi``, ``labels`` …) to the underlying view, so the
time-domain metrics — which only ever touch the series interface — work
unchanged whether they are handed a bare view or a context.

On top of the series interface it adds the extra inputs the BP / RESP /
band-power metrics need, each computed **lazily and cached** via
``functools.cached_property`` so the cost is paid at most once per epoch no
matter how many metrics consult it:

``psd``
    The band-power PSD (:meth:`PSDEngine.for_band_power`) for the configured
    ``psd_method``.  Shared by every standard band-power metric and the
    ``band_powers`` group metric for non-standard bands.  ``None`` when no
    method is configured or the PSD could not be computed.
``bp_beats`` / ``resp_beats``
    Per-beat blood-pressure / respiration parameter dicts gated on the epoch's
    R-peaks.  ``None`` when the corresponding waveform channel is absent.
``rsa_beats``
    Per-breath Grossman peak-to-valley RSA array (ms), or ``None``.
``pep_detail``
    Full ICG ensemble dict from :func:`~spectHR.analysis.icg_metrics.pep_ensemble`,
    or ``None`` when no ICG channel is present.

A bare ``CardioSeriesView`` carries none of these attributes, which is how the
dual-mode band-power metrics tell a direct call (use the default PSD method)
apart from a table call (use ``ctx.psd_method``, or yield ``NaN`` when it is
``None``).
"""
from __future__ import annotations

from functools import cached_property

import numpy as np


class EpochContext:
    """Single argument handed to every ``@epoch_metric`` by the table.

    Parameters
    ----------
    view
        The epoch's ``CardioSeriesView`` (the active HRV series restricted to
        the epoch bounds).  All series-interface attribute access is delegated
        here.
    psd_method
        Workspace-configured ``PsdMethod`` (or ``None``).  Drives :attr:`psd`
        and is read by the band-power metrics.
    bp_ts, rsp_ts
        Optional blood-pressure / respiration ``TimeSeries`` (objects exposing
        ``.times`` and ``.values``).  ``None`` when the channel is not loaded.
    """

    def __init__(self, view, *, psd_method=None, bp_ts=None, rsp_ts=None,
                 rsp_phases=None, rsa_lag_s: float = 1.0,
                 rsa_max_ibi_deviation=None, rsa_max_rate_deviation=None,
                 icg_ts=None, ecg_ts=None, b_point_guard_ms: float = 30.0):
        self.view = view
        self.psd_method = psd_method
        self.bp_ts = bp_ts
        self.rsp_ts = rsp_ts
        self.rsp_phases = rsp_phases
        self.rsa_lag_s = rsa_lag_s
        self.rsa_max_ibi_deviation = rsa_max_ibi_deviation
        self.rsa_max_rate_deviation = rsa_max_rate_deviation
        self.icg_ts = icg_ts
        self.ecg_ts = ecg_ts
        self.b_point_guard_ms = b_point_guard_ms

    # ------------------------------------------------------------------ #
    # Series-interface delegation                                         #
    # ------------------------------------------------------------------ #

    def __getattr__(self, name: str):
        # Reached only for names not found as instance/class attributes, so
        # the delegation never shadows view/psd_method/cached_property results.
        # Guard against view being missing (e.g. during unpickling) to avoid
        # infinite recursion.
        try:
            view = object.__getattribute__(self, "view")
        except AttributeError as exc:                       # pragma: no cover
            raise AttributeError(name) from exc
        return getattr(view, name)

    # ------------------------------------------------------------------ #
    # R-peaks                                                             #
    # ------------------------------------------------------------------ #

    @property
    def rpeak_times(self) -> np.ndarray:
        """R-peak timestamps for the epoch — the BP/RESP beat boundaries."""
        return self.view.times

    # ------------------------------------------------------------------ #
    # Lazily-cached spectral / waveform results                          #
    # ------------------------------------------------------------------ #

    @cached_property
    def psd(self):
        """Band-power PSD for ``psd_method`` (cached), or ``None``."""
        if self.psd_method is None:
            return None
        try:
            from spectHR.analysis.psd._engine import PSDEngine
            return PSDEngine(self.view).for_band_power(self.psd_method)
        except Exception:
            return None

    @cached_property
    def bp_beats(self):
        """Per-beat BP parameter dict (cached), or ``None`` when no BP channel."""
        if self.bp_ts is None:
            return None
        try:
            from spectHR.analysis.bp_metrics import bp_beat_parameters
            return bp_beat_parameters(
                np.asarray(self.bp_ts.times, dtype=float),
                np.asarray(self.bp_ts.values, dtype=float),
                np.asarray(self.rpeak_times, dtype=float),
            )
        except Exception:
            return None

    @cached_property
    def resp_beats(self):
        """Per-beat respiration parameter dict (cached), or ``None``."""
        if self.rsp_ts is None:
            return None
        try:
            from spectHR.analysis.bp_metrics import resp_beat_parameters
            return resp_beat_parameters(
                np.asarray(self.rsp_ts.times, dtype=float),
                np.asarray(self.rsp_ts.values, dtype=float),
                np.asarray(self.rpeak_times, dtype=float),
            )
        except Exception:
            return None

    @cached_property
    def rsa_beats(self):
        """Per-breath Grossman peak-to-valley RSA array (ms), or ``None``."""
        if self.rsp_phases is None or len(self.rsp_phases) < 2:
            return None
        try:
            from spectHR.analysis.bp_metrics import grossman_rsa_per_breath
            return grossman_rsa_per_breath(
                np.asarray(self.rpeak_times, dtype=float),
                np.asarray(self.labels,      dtype=object),
                self.rsp_phases,
                lag_s=self.rsa_lag_s,
                max_ibi_deviation=self.rsa_max_ibi_deviation,
                max_rate_deviation=self.rsa_max_rate_deviation,
            )
        except Exception:
            return None

    @cached_property
    def pep_detail(self):
        """Ensemble-PEP detail dict (cached) — scored Q/B/C landmarks plus the
        ensemble-averaged ICG/ECG complexes.  ``None`` when no ICG channel is
        present or no scorable ensemble could be formed."""
        if self.icg_ts is None:
            return None
        try:
            from spectHR.analysis.icg_metrics import pep_ensemble
            ecg_kw: dict = {}
            if self.ecg_ts is not None:
                ecg_kw = dict(
                    ecg_times=np.asarray(self.ecg_ts.times, dtype=float),
                    ecg_values=np.asarray(self.ecg_ts.values, dtype=float),
                )
            return pep_ensemble(
                np.asarray(self.icg_ts.times, dtype=float),
                np.asarray(self.icg_ts.values, dtype=float),
                np.asarray(self.rpeak_times, dtype=float),
                b_guard_ms=self.b_point_guard_ms,
                return_detail=True,
                **ecg_kw,
            )
        except Exception:
            return None

    @property
    def pep_value(self):
        """Epoch pre-ejection period (ms) from the ensemble-averaged ICG/ECG
        complex, or ``None`` when no ICG channel is present."""
        detail = self.pep_detail
        return None if detail is None else detail.get("pep")
