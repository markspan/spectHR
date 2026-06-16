# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/epoch_context.py
"""
Per-epoch evaluation context for ``@epoch_metric`` functions.

``Session.epochs_table`` builds one :class:`EpochContext` per
active epoch and passes it to every registered metric.  The context is a
``@dataclass`` that satisfies :class:`CardioSeriesProtocol` via explicit
``times`` / ``ibi`` / ``labels`` properties, so time-domain metrics written
against a bare ``Events`` window work unchanged when handed a context.

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

A bare ``Events`` window has no ``psd_method`` attribute; the dual-mode
band-power metrics distinguish the two call paths via ``isinstance(series,
EpochContext)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Protocol

import numpy as np


# ------------------------------------------------------------------ #
# Protocol — documents the series interface @epoch_metric relies on  #
# ------------------------------------------------------------------ #

class CardioSeriesProtocol(Protocol):
    """Minimal interface that ``@epoch_metric`` functions depend on.

    Both a bare :class:`~spectHR.session.Events` window and
    :class:`EpochContext` satisfy this protocol, so metrics written against a
    bare series continue to work when the table passes a context.
    """

    @property
    def times(self) -> np.ndarray: ...

    @property
    def ibi(self) -> np.ndarray: ...

    @property
    def labels(self) -> np.ndarray: ...


# ------------------------------------------------------------------ #
# Context                                                             #
# ------------------------------------------------------------------ #

@dataclass
class EpochContext:
    """Single argument handed to every ``@epoch_metric`` by the table.

    Parameters
    ----------
    view
        The epoch's ``Events`` window (the active HRV series restricted to
        the epoch bounds).
    psd_method
        Parameters-configured ``PsdMethod`` (or ``None``).  Drives :attr:`psd`
        and is read by the band-power metrics.
    bp_ts, rsp_ts
        Optional blood-pressure / respiration ``TimeSeries`` (objects exposing
        ``.times`` and ``.values``).  ``None`` when the channel is not loaded.
    """

    # Positional-only field — no default, must be supplied first
    view: Any

    # All remaining fields are keyword-only (mirrors the original * separator)
    psd_method:              Any   = field(default=None,  kw_only=True)
    bp_ts:                   Any   = field(default=None,  kw_only=True)
    rsp_ts:                  Any   = field(default=None,  kw_only=True)
    rsp_phases:              Any   = field(default=None,  kw_only=True)
    rsa_lag_s:               float = field(default=1.0,   kw_only=True)
    rsa_max_ibi_deviation:   Any   = field(default=None,  kw_only=True)
    rsa_max_rate_deviation:  Any   = field(default=None,  kw_only=True)
    icg_ts:                  Any   = field(default=None,  kw_only=True)
    ecg_ts:                  Any   = field(default=None,  kw_only=True)
    b_point_guard_ms:        float = field(default=30.0,  kw_only=True)
    # Dict with keys: input_signal, min_coherence, f_max, bands.
    # None disables transfer metrics.
    transfer_config:         Any   = field(default=None,  kw_only=True)
    prsa_window:             int   = field(default=30,    kw_only=True)

    # ------------------------------------------------------------------ #
    # CardioSeriesProtocol — explicit forwarding to self.view            #
    # ------------------------------------------------------------------ #

    @property
    def times(self) -> np.ndarray:
        return self.view.times

    @property
    def ibi(self) -> np.ndarray:
        return self.view.ibi

    @property
    def labels(self) -> np.ndarray:
        return self.view.labels

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
                np.asarray(self.bp_ts.times,  dtype=float),
                np.asarray(self.bp_ts.values, dtype=float),
                np.asarray(self.rpeak_times,  dtype=float),
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
                np.asarray(self.rsp_ts.times,  dtype=float),
                np.asarray(self.rsp_ts.values, dtype=float),
                np.asarray(self.rpeak_times,   dtype=float),
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
                    ecg_times=np.asarray(self.ecg_ts.times,  dtype=float),
                    ecg_values=np.asarray(self.ecg_ts.values, dtype=float),
                )
            return pep_ensemble(
                np.asarray(self.icg_ts.times,  dtype=float),
                np.asarray(self.icg_ts.values, dtype=float),
                np.asarray(self.rpeak_times,   dtype=float),
                b_guard_ms=self.b_point_guard_ms,
                return_detail=True,
                **ecg_kw,
            )
        except Exception:
            return None

    @cached_property
    def breath_times(self) -> np.ndarray:
        """Midpoint timestamps of INH→EXH breath pairs, aligned with rsa_beats."""
        rsp_phases = self.rsp_phases
        if rsp_phases is None:
            return np.array([], dtype=float)
        p_starts = np.asarray(rsp_phases.starts, dtype=float)
        p_ends   = np.asarray(rsp_phases.ends,   dtype=float)
        p_labels = np.asarray(rsp_phases.labels, dtype=object)
        x_pts: list[float] = []
        for i in range(len(p_starts) - 1):
            if p_labels[i] == "INH" and p_labels[i + 1] == "EXH":
                x_pts.append((p_starts[i] + p_ends[i + 1]) / 2.0)
        return np.array(x_pts, dtype=float)

    @cached_property
    def transfer_result(self):
        """Per-epoch transfer function result (cached), or ``None``.

        Uses the configured ``transfer_config`` dict.  ``None`` when no config
        is present, the required input channel is absent, or fewer than 4
        clean R-peaks are available.
        """
        cfg = self.transfer_config
        if cfg is None:
            return None
        sig = cfg.get("input_signal", "rsp")
        if sig.startswith("bp"):
            inp = self.bp_ts
        else:
            inp = self.rsp_ts
        if inp is None:
            return None
        try:
            from spectHR.analysis.transfer import compute_transfer
            return compute_transfer(
                self.view,
                inp,
                input_signal=sig,
                bands=cfg.get("bands") or {},
                min_coherence=float(cfg.get("min_coherence", 0.5)),
                f_max=float(cfg.get("f_max", 0.5)),
            )
        except Exception:
            return None

    @property
    def pep_value(self):
        """Epoch pre-ejection period (ms) from the ensemble-averaged ICG/ECG
        complex, or ``None`` when no ICG channel is present."""
        detail = self.pep_detail
        return None if detail is None else detail.get("pep")
