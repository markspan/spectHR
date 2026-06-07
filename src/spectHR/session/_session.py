# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/session/_session.py
"""
:class:`PhysioSession` — the modern root container for a physiological recording.

Design goals
------------
* **No circular references.**  Data objects (:class:`~._data.Signal`,
  :class:`~._data.Beats`, :class:`~._data.BreathPhases`) know nothing about
  the session; the session owns them.
* **Typed configuration.**  :class:`AnalysisConfig` replaces the flat
  workspace-dict kwargs pattern with validated, documented fields.
* **Functional epoch iteration.**  :meth:`PhysioSession.epochs_table` is a
  pure function: same session + same config → same result.
* **Bridge compatibility.**  :meth:`PhysioSession.from_physio_data` wraps an
  existing :class:`~spectHR.DataSet.PhysioData.PhysioData` so all current
  loaders work without modification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from spectHR.session._data import (
    Beats, BeatSlice, BreathPhases, PhaseSlice, Signal, SignalSlice,
)


# ---------------------------------------------------------------------------
# Epoch — a labelled time window
# ---------------------------------------------------------------------------

@dataclass
class Epoch:
    """A labelled time window within a recording."""
    label:  str
    start:  float
    end:    float
    active: bool = True

    @property
    def duration(self) -> float:
        return self.end - self.start

    def contains(self, t: float) -> bool:
        return self.start <= t <= self.end


# ---------------------------------------------------------------------------
# AnalysisConfig — typed replacement for workspace-dict kwargs
# ---------------------------------------------------------------------------

@dataclass
class AnalysisConfig:
    """All parameters needed to run epoch metrics.

    Replaces the scattered ``psd_method=..., rsa_lag_s=..., ...`` keyword
    arguments passed to ``PhysioData.epoched_parameters_table``.
    """
    psd_method:             Any   = None
    rsa_lag_s:              float = 1.0
    rsa_max_ibi_deviation:  float | None = None
    rsa_max_rate_deviation: float | None = None
    b_point_guard_ms:       float = 30.0

    @classmethod
    def from_workspace(cls, workspace: dict | None) -> AnalysisConfig:
        """Build from a workspace dict (bridges the old config path)."""
        from spectHR.config import WorkspaceView
        ws = WorkspaceView(workspace)
        ibi_dev, rate_dev = ws.rsa_rejection
        return cls(
            psd_method=ws.psd_method,
            rsa_lag_s=ws.rsa_lag_s,
            rsa_max_ibi_deviation=ibi_dev,
            rsa_max_rate_deviation=rate_dev,
            b_point_guard_ms=ws.b_point_guard_ms,
        )


# ---------------------------------------------------------------------------
# EpochsResult — structured return type for epochs_table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpochsResult:
    """Return value of :meth:`PhysioSession.epochs_table`."""
    labels:   np.ndarray          # shape (n_epochs,)
    columns:  list[str]           # length n_metrics
    values:   np.ndarray          # shape (n_epochs, n_metrics)
    contexts: dict[str, Any]      # label → EpochContext (for export reuse)


# ---------------------------------------------------------------------------
# PhysioSession — the root container
# ---------------------------------------------------------------------------

@dataclass
class PhysioSession:
    """Root container for one physiological recording.

    Owns all channels as typed, immutable data objects.  Epoch analysis
    flows one-way: session → config → contexts → metrics.

    Parameters
    ----------
    filename
        Source file path (informational).
    signals
        Dict of continuous waveforms keyed by channel name
        (e.g. ``"ecg"``, ``"resp"``, ``"icg"``).
    beats
        Dict of R-peak series keyed by band name.  ``"default"`` is the
        primary band used when no band is specified.
    phases
        Dict of breath-phase series keyed by band name.
    epochs
        Ordered dict of epoch windows.
    active_band
        Which key in *beats* / *phases* is the current analysis band.
    """

    filename:    str
    signals:     dict[str, Signal]       = field(default_factory=dict)
    beats:       dict[str, Beats]        = field(default_factory=dict)
    phases:      dict[str, BreathPhases] = field(default_factory=dict)
    epochs:      dict[str, Epoch]        = field(default_factory=dict)
    active_band: str                     = "default"

    # --- channel shortcuts ---

    def signal(self, *names: str) -> Signal | None:
        """Return the first named signal found, or ``None``."""
        for n in names:
            s = self.signals.get(n)
            if s is not None:
                return s
        return None

    @property
    def ecg(self) -> Signal | None:
        return self.signal("ecg")

    @property
    def resp(self) -> Signal | None:
        return self.signal("resp", "respiration")

    @property
    def icg(self) -> Signal | None:
        return self.signal("icg")

    @property
    def hrv(self) -> Beats | None:
        return self.beats.get(self.active_band) or self.beats.get("default")

    @property
    def breath(self) -> BreathPhases | None:
        return self.phases.get(self.active_band) or self.phases.get("default")

    # --- epoch analysis ---

    def epochs_table(
        self, config: AnalysisConfig | None = None
    ) -> EpochsResult:
        """Evaluate all registered epoch metrics for every active epoch.

        Replaces ``PhysioData.epoched_parameters_table``.  Returns an
        :class:`EpochsResult` whose ``contexts`` dict can be passed directly
        to :class:`~spectHR.analysis.exporter.EpochExporter`.

        Parameters
        ----------
        config
            Analysis parameters.  ``None`` uses :class:`AnalysisConfig`
            defaults.
        """
        from spectHR.analysis.epoch_context import EpochContext
        from spectHR.analysis.registry import get_metrics, get_metric_groups

        config = config or AnalysisConfig()
        active = {k: v for k, v in self.epochs.items() if v.active}

        if not active or self.hrv is None:
            return EpochsResult(
                labels=np.array(list(active), dtype=object),
                columns=[],
                values=np.empty((len(active), 0)),
                contexts={},
            )

        hrv    = self.hrv
        breath = self.breath
        bp_sig = self.signal("bp", "nibp")
        rsp_sig = self.resp
        icg_sig = self.icg
        ecg_sig = self.ecg

        metrics = get_metrics()
        groups  = get_metric_groups()
        contexts: dict[str, EpochContext] = {}
        rows: list[dict[str, float]] = []

        for label, epoch in active.items():
            beat_sl: BeatSlice = hrv.slice(epoch.start, epoch.end)

            rsp_phases: PhaseSlice | None = None
            if breath is not None:
                rsp_phases = breath.slice(epoch.start, epoch.end)

            def _sig_slice(sig: Signal | None) -> SignalSlice | None:
                return sig.slice(epoch.start, epoch.end) if sig is not None else None

            ctx = EpochContext(
                view=beat_sl,
                psd_method=config.psd_method,
                bp_ts=_sig_slice(bp_sig),
                rsp_ts=_sig_slice(rsp_sig),
                rsp_phases=rsp_phases,
                rsa_lag_s=config.rsa_lag_s,
                rsa_max_ibi_deviation=config.rsa_max_ibi_deviation,
                rsa_max_rate_deviation=config.rsa_max_rate_deviation,
                icg_ts=_sig_slice(icg_sig),
                ecg_ts=_sig_slice(ecg_sig),
                b_point_guard_ms=config.b_point_guard_ms,
            )
            contexts[label] = ctx

            row: dict[str, float] = {}
            for name, fn in metrics.items():
                try:
                    row[name] = float(fn(ctx))
                except Exception:
                    row[name] = np.nan
            for name, fn in groups.items():
                try:
                    extra = fn(ctx)
                    if isinstance(extra, dict):
                        row.update({k: float(v) for k, v in extra.items()})
                except Exception:
                    pass
            rows.append(row)

        # Assemble rectangular matrix, preserving first-seen column order
        all_cols = list(dict.fromkeys(c for r in rows for c in r))
        labels_arr = np.array(list(active), dtype=object)
        matrix = np.full((len(rows), len(all_cols)), np.nan)
        col_idx = {c: i for i, c in enumerate(all_cols)}
        for i, row in enumerate(rows):
            for col, val in row.items():
                matrix[i, col_idx[col]] = val

        return EpochsResult(labels_arr, all_cols, matrix, contexts)

    # --- bridge from legacy PhysioData ---

    @classmethod
    def from_physio_data(cls, pd) -> PhysioSession:
        """Wrap a :class:`~spectHR.DataSet.PhysioData.PhysioData` instance.

        Converts legacy ``TimeSeries``, ``CardioSeries``, and
        ``RespirationSeries`` objects to the new immutable types so all
        existing loaders work without modification.

        The returned session shares array *data* with the original (zero
        extra memory for large waveforms).
        """
        signals: dict[str, Signal] = {}
        for name, ts in pd.timeseries.items():
            signals[name] = Signal(
                times=np.asarray(ts.times,  dtype=np.float64),
                values=np.asarray(ts.values, dtype=np.float64),
                name=name,
            )

        beats: dict[str, Beats] = {}
        for band, cs in pd.hrv_map.items():
            beats[band] = Beats(
                times=np.asarray(cs.times,  dtype=np.float64),
                labels=np.asarray(cs.labels, dtype=object),
            )
        if beats and "default" not in beats:
            beats["default"] = next(iter(beats.values()))

        phases: dict[str, BreathPhases] = {}
        for band, rs in pd.rsp_map.items():
            phases[band] = BreathPhases(
                starts=np.asarray(rs.starts, dtype=np.float64),
                ends=np.asarray(rs.ends,     dtype=np.float64),
                labels=np.asarray(rs.labels, dtype=object),
            )
        if phases and "default" not in phases:
            phases["default"] = next(iter(phases.values()))

        epochs: dict[str, Epoch] = {
            label: Epoch(
                label=label,
                start=float(ep.start),
                end=float(ep.end),
                active=bool(ep.active),
            )
            for label, ep in pd.epochs.items()
        }

        active_band: str = pd.active_band or "default"

        return cls(
            filename=str(pd.filename),
            signals=signals,
            beats=beats,
            phases=phases,
            epochs=epochs,
            active_band=active_band,
        )
