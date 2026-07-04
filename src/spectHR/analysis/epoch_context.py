# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/epoch_context.py
"""
Per-epoch evaluation context for ``@epoch_metric`` functions.

``Session.epochs_table`` builds one :class:`EpochContext` per active epoch (from
``Session.scoped_to``) and passes it to every registered metric.  The context is
a ``@dataclass`` that satisfies :class:`CardioSeriesProtocol` via explicit
``times`` / ``ibi`` / ``labels`` properties, so time-domain metrics written
against a bare ``Events`` window work unchanged when handed a context.

It holds the epoch's windowed channels plus one
:class:`~spectHR.session.AnalysisConfig`; every setting the config carries is
reachable as ``ctx.<name>`` (delegated via ``__getattr__``), so a new analysis
parameter is added once on ``AnalysisConfig`` and needs no change here.

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

from spectHR.logger import logger
from spectHR.session._session import AnalysisConfig

# ------------------------------------------------------------------ #
# Protocol, documents the series interface @epoch_metric relies on  #
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

    It carries two things: the epoch's **data** (the windowed channels) and
    the **settings** (one :class:`~spectHR.session.AnalysisConfig`).  Splitting
    them this way means a new analysis parameter is declared once, on
    ``AnalysisConfig``, and reaches metrics with no change here.

    Parameters
    ----------
    view
        The epoch's ``Events`` window (the active HRV series restricted to the
        epoch bounds).
    bp_ts, rsp_ts, rsp_phases, icg_ts, ecg_ts
        Per-epoch blood-pressure / respiration / breath-phase / ICG / ECG
        channels (windowed to the epoch).  ``None`` when the channel is absent.
    config
        All analysis settings (``psd_method``, ``rsa_lag_s``,
        ``b_point_guard_ms``, ``transfer_config``, ``prsa_window``,
        ``log_band_power``, ``rsa_max_*``).
    """

    # Positional-only field, no default, must be supplied first.
    view: Any

    # Per-epoch waveform channels (windowed), keyword-only, None when absent.
    bp_ts:      Any = field(default=None, kw_only=True)
    rsp_ts:     Any = field(default=None, kw_only=True)
    rsp_phases: Any = field(default=None, kw_only=True)
    icg_ts:     Any = field(default=None, kw_only=True)
    ecg_ts:     Any = field(default=None, kw_only=True)

    # All analysis settings in one place.  Their values are reachable directly
    # as ``ctx.<name>`` via __getattr__ below, so metric code that reads e.g.
    # ``getattr(ctx, "psd_method")`` works unchanged whether it is handed a
    # context or a bare ``Events`` series.
    config: AnalysisConfig = field(default_factory=AnalysisConfig, kw_only=True)

    def __getattr__(self, name: str):
        """Expose every ``AnalysisConfig`` field as ``ctx.<field>``.

        Only fires for names not found normally (real fields, properties,
        cached_properties), so it never shadows them, and only delegates the
        config's *declared fields* (not its methods).  ``config`` itself is
        guarded to avoid recursion during construction.
        """
        if name == "config":
            raise AttributeError(name)
        config = self.__dict__.get("config")
        if config is not None and name in type(config).__dataclass_fields__:
            return getattr(config, name)
        raise AttributeError(name)

    # ------------------------------------------------------------------ #
    # CardioSeriesProtocol, explicit forwarding to self.view            #
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
        """R-peak timestamps for the epoch, the BP/RESP beat boundaries."""
        return self.view.times

    # ------------------------------------------------------------------ #
    # Lazily-cached spectral / waveform results                          #
    #                                                                    #
    # Each guards the legitimately-absent case (channel not loaded) and  #
    # returns None silently; a genuine computation failure is logged via #
    # _guarded rather than swallowed, so a real bug leaves a trace.      #
    # ------------------------------------------------------------------ #

    def _guarded(self, name: str, compute):
        """Run *compute*; on failure log it (not silent) and return ``None``.

        Callers guard the legitimately-absent case (no channel) *before*
        calling this, so anything reaching here is a real computation error
        worth surfacing in the log rather than silently swallowing to ``None``.
        """
        try:
            return compute()
        except Exception as exc:   # noqa: BLE001, one bad epoch must not abort the table
            logger.warning(
                "Epoch resource %r failed: %s: %s",
                name, type(exc).__name__, exc,
            )
            logger.debug("Traceback for epoch resource %r:", name, exc_info=True)
            return None

    @cached_property
    def psd(self):
        """Band-power PSD for ``config.psd_method`` (cached), or ``None``."""
        if self.config.psd_method is None:
            return None
        from spectHR.analysis.psd._engine import PSDEngine
        return self._guarded(
            "psd",
            lambda: PSDEngine(self.view).for_band_power(self.config.psd_method),
        )

    @cached_property
    def bp_beats(self):
        """Per-beat BP parameter dict (cached), or ``None`` when no BP channel."""
        if self.bp_ts is None:
            return None
        from spectHR.analysis.bp_metrics import bp_beat_parameters
        return self._guarded(
            "bp_beats",
            lambda: bp_beat_parameters(
                np.asarray(self.bp_ts.times,  dtype=float),
                np.asarray(self.bp_ts.values, dtype=float),
                np.asarray(self.rpeak_times,  dtype=float),
            ),
        )

    @cached_property
    def resp_beats(self):
        """Per-beat respiration parameter dict (cached), or ``None``."""
        if self.rsp_ts is None:
            return None
        from spectHR.analysis.respiration_metrics import resp_beat_parameters
        return self._guarded(
            "resp_beats",
            lambda: resp_beat_parameters(
                np.asarray(self.rsp_ts.times,  dtype=float),
                np.asarray(self.rsp_ts.values, dtype=float),
                np.asarray(self.rpeak_times,   dtype=float),
            ),
        )

    @cached_property
    def rsa_beats(self):
        """Per-breath Grossman peak-to-valley RSA array (ms), or ``None``."""
        if self.rsp_phases is None or len(self.rsp_phases) < 2:
            return None
        from spectHR.analysis.respiration_metrics import grossman_rsa_per_breath
        return self._guarded(
            "rsa_beats",
            lambda: grossman_rsa_per_breath(
                np.asarray(self.rpeak_times, dtype=float),
                np.asarray(self.labels,      dtype=object),
                self.rsp_phases,
                lag_s=self.config.rsa_lag_s,
                max_ibi_deviation=self.config.rsa_max_ibi_deviation,
                max_rate_deviation=self.config.rsa_max_rate_deviation,
            ),
        )

    @cached_property
    def pep_detail(self):
        """Ensemble-PEP detail dict (cached), scored Q/B/C landmarks plus the
        ensemble-averaged ICG/ECG complexes.  ``None`` when no ICG channel is
        present or no scorable ensemble could be formed."""
        if self.icg_ts is None:
            return None
        from spectHR.analysis.icg_metrics import pep_ensemble

        def _compute():
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
                b_guard_ms=self.config.b_point_guard_ms,
                return_detail=True,
                **ecg_kw,
            )

        return self._guarded("pep_detail", _compute)

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

        Uses the configured :class:`~spectHR.session.TransferConfig`.  ``None``
        when no config is present, the required input channel is absent, or
        fewer than 4 clean R-peaks are available.
        """
        cfg = self.config.transfer_config
        if cfg is None:
            return None
        sig = cfg.input_signal
        inp = self.bp_ts if sig.startswith("bp") else self.rsp_ts
        if inp is None:
            return None
        from spectHR.analysis.transfer import compute_transfer
        return self._guarded(
            "transfer_result",
            lambda: compute_transfer(
                self.view,
                inp,
                input_signal=sig,
                bands=cfg.bands or {},
                min_coherence=cfg.min_coherence,
                f_max=cfg.f_max,
            ),
        )

    @property
    def pep_value(self):
        """Epoch pre-ejection period (ms) from the ensemble-averaged ICG/ECG
        complex, or ``None`` when no ICG channel is present."""
        detail = self.pep_detail
        return None if detail is None else detail.get("pep")
