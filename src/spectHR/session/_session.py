# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/session/_session.py
"""
:class:`Session` — the root container for one physiological recording.

Architecture
------------
A ``Session`` owns three typed channel dicts (``samples``, ``events``,
``intervals``) and an epoch table.  The channel types —
:class:`~._core.Samples`, :class:`~._core.Events`,
:class:`~._core.Intervals` — are pure data; they know nothing about the
session.  The session is the sole owner; there are no circular references.

Computation flows one way::

    Session  →  AnalysisConfig  →  EpochContext  →  @epoch_metric

:meth:`Session.scoped_to` collapses all channels to a single epoch window
with zero copying and returns a ``Session`` with no epoch table — the
epoch IS the session.  This makes all channel operations naturally
epoch-scoped without any special casing in metric code.

:meth:`Session.epochs_table` evaluates every registered ``@epoch_metric``
and ``@epoch_metric_group`` for all active epochs and returns a
:class:`MetricsTable`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from spectHR.session._core import Events, Intervals, Samples  # noqa: F401 (re-used in methods)


# ---------------------------------------------------------------------------
# Epoch
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

    Replaces the scattered keyword arguments on
    ``Session.epochs_table``.  Build from a workspace dict
    via :meth:`from_workspace`.
    """

    psd_method:             Any   = None
    rsa_lag_s:              float = 1.0
    rsa_max_ibi_deviation:  float | None = None
    rsa_max_rate_deviation: float | None = None
    b_point_guard_ms:       float = 30.0
    # Transfer config: dict with keys input_signal, min_coherence, smooth,
    # f_max, and bands {name: (lo, hi)}.  None disables transfer metrics.
    transfer_config:        Any   = None
    prsa_window:            int   = 30

    @classmethod
    def from_workspace(cls, workspace: dict | None) -> AnalysisConfig:
        """Build from a raw workspace dict."""
        from spectHR.config import WorkspaceView, transfer_settings_from_workspace
        from spectHR.config import display_bands_from_workspace
        ws = WorkspaceView(workspace)
        ibi_dev, rate_dev = ws.rsa_rejection
        ts = transfer_settings_from_workspace(workspace)
        raw_bands = display_bands_from_workspace(workspace)
        bands = {
            name: (float(s["low"]), float(s["high"]))
            for name, s in raw_bands.items()
            if "low" in s and "high" in s and name != "FullRange"
        }
        tf_cfg = {
            "input_signal": ts["input_signal"],
            "min_coherence": ts["min_coherence"],
            "smooth": ts["smooth"],
            "f_max": ts["f_max"],
            "bands": bands,
        }
        return cls(
            psd_method=ws.psd_method,
            rsa_lag_s=ws.rsa_lag_s,
            rsa_max_ibi_deviation=ibi_dev,
            rsa_max_rate_deviation=rate_dev,
            b_point_guard_ms=ws.b_point_guard_ms,
            transfer_config=tf_cfg,
            prsa_window=ws.prsa_window,
        )


# ---------------------------------------------------------------------------
# MetricsTable
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricsTable:
    """Result of :meth:`Session.epochs_table`.

    Attributes
    ----------
    labels
        Epoch label for each row.  Shape ``(n_epochs,)``.
    columns
        Metric name for each column.  Length ``n_metrics``.
    values
        Float matrix, shape ``(n_epochs, n_metrics)``.  ``NaN`` when a
        metric could not be computed for an epoch.
    contexts
        ``label → EpochContext`` mapping.  Contexts carry cached PSD,
        RSA, and ICG results so an :class:`~spectHR.analysis.exporter.EpochExporter`
        can reuse them without recomputation.
    """

    labels:   np.ndarray
    columns:  list[str]
    values:   np.ndarray
    contexts: dict[str, Any]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """Root container for one physiological recording.

    Parameters
    ----------
    name
        Recording identifier (file name or study label).
    samples
        Continuous waveforms keyed by channel name.
        Conventional keys: ``"ecg"``, ``"resp"``, ``"bp"``, ``"icg"``.
    events
        Point-event series keyed by channel name.
        Conventional key: ``"hrv"`` for the R-peak series.
    intervals
        Labelled segment series keyed by channel name.
        Conventional key: ``"breath"`` for INH/EXH phases.
    epochs
        Named time windows.  Only ``active=True`` epochs are included in
        :meth:`epochs_table`.
    """

    name:      str
    samples:   dict[str, Samples]   = field(default_factory=dict)
    events:    dict[str, Events]    = field(default_factory=dict)
    intervals: dict[str, Intervals] = field(default_factory=dict)
    epochs:    dict[str, Epoch]     = field(default_factory=dict)

    # --- typed getters by convention ---

    @property
    def hrv(self) -> Events | None:
        return self.events.get("hrv")

    @property
    def breath(self) -> Intervals | None:
        return self.intervals.get("breath")

    @property
    def ecg(self) -> Samples | None:
        return self.samples.get("ecg")

    @property
    def resp(self) -> Samples | None:
        return self.samples.get("resp") or self.samples.get("respiration")

    @property
    def bp(self) -> Samples | None:
        return self.samples.get("bp") or self.samples.get("nibp")

    @property
    def icg(self) -> Samples | None:
        return self.samples.get("icg")

    # --- scoping ---

    def scoped_to(self, epoch_label: str) -> Session:
        """Return a new ``Session`` with every channel windowed to *epoch_label*.

        The returned session has an empty epoch table — it *is* the epoch.
        All windowing is zero-copy (O(log n) per channel).

        Example — per-breath RSA within one epoch::

            ep = session.scoped_to("A")
            for t0, t1 in ep.intervals["breath"].windows_of("INH"):
                phase_beats = ep.events["hrv"].window(t0, t1)
                rsa = compute_rsa(phase_beats, ...)
        """
        ep = self.epochs[epoch_label]
        return Session(
            name=f"{self.name}[{epoch_label}]",
            samples={k: v.window(ep.start, ep.end) for k, v in self.samples.items()},
            events={k: v.window(ep.start, ep.end) for k, v in self.events.items()},
            intervals={k: v.window(ep.start, ep.end) for k, v in self.intervals.items()},
        )

    # --- epoch metrics table ---

    def epochs_table(self, config: AnalysisConfig | None = None) -> MetricsTable:
        """Evaluate every registered ``@epoch_metric`` for all active epochs.

        Reuses :class:`~spectHR.analysis.epoch_context.EpochContext` caching:
        PSD, RSA, and ICG results are computed at most once per epoch regardless
        of how many metrics request them.

        Parameters
        ----------
        config
            Analysis parameters.  ``None`` uses :class:`AnalysisConfig` defaults.
        """
        from spectHR.analysis.epoch_context import EpochContext
        from spectHR.analysis.registry import get_metrics, get_metric_groups

        config = config or AnalysisConfig()
        active = {k: v for k, v in self.epochs.items() if v.active}

        if not active or self.hrv is None:
            return MetricsTable(
                labels=np.array(list(active), dtype=object),
                columns=[],
                values=np.empty((len(active), 0)),
                contexts={},
            )

        metrics = get_metrics()
        groups  = get_metric_groups()
        contexts: dict[str, EpochContext] = {}
        rows: list[dict[str, float]] = []

        for label, epoch in active.items():
            s, e = epoch.start, epoch.end

            def _win(ch: Samples | None) -> Samples | None:
                return ch.window(s, e) if ch is not None else None

            ctx = EpochContext(
                view=self.events["hrv"].window(s, e),
                psd_method=config.psd_method,
                bp_ts=_win(self.bp),
                rsp_ts=_win(self.resp),
                rsp_phases=(self.breath.window(s, e) if self.breath is not None else None),
                rsa_lag_s=config.rsa_lag_s,
                rsa_max_ibi_deviation=config.rsa_max_ibi_deviation,
                rsa_max_rate_deviation=config.rsa_max_rate_deviation,
                icg_ts=_win(self.icg),
                ecg_ts=_win(self.ecg),
                b_point_guard_ms=config.b_point_guard_ms,
                transfer_config=config.transfer_config,
                prsa_window=config.prsa_window,
            )
            contexts[label] = ctx

            row: dict[str, float] = {}
            for mname, fn in metrics.items():
                try:
                    row[mname] = float(fn(ctx))
                except Exception:
                    row[mname] = np.nan
            for _, fn in groups.items():
                try:
                    extra = fn(ctx)
                    if isinstance(extra, dict):
                        row.update({k: float(v) for k, v in extra.items()})
                except Exception:
                    pass
            rows.append(row)

        all_cols = list(dict.fromkeys(c for r in rows for c in r))
        matrix   = np.full((len(rows), len(all_cols)), np.nan)
        col_idx  = {c: i for i, c in enumerate(all_cols)}
        for i, row in enumerate(rows):
            for col, val in row.items():
                matrix[i, col_idx[col]] = val

        return MetricsTable(
            labels=np.array(list(active), dtype=object),
            columns=all_cols,
            values=matrix,
            contexts=contexts,
        )

    # --- preprocessing helpers (functional — return new Session) ---

    def with_detected_beats(
        self,
        signal_key: str = "ecg",
        *,
        events_key: str = "hrv",
        min_peak_distance_ms: float = 300.0,
        window_length: int = 20,
        n_std: float = 3.0,
        max_ibi_sec: float = 2.5,
        classify: bool = True,
    ) -> Session:
        """Return a new ``Session`` with R-peaks detected from *signal_key*.

        The detected :class:`~._core.Events` is stored under *events_key*
        (default ``"hrv"``).  All other channels and epochs are preserved.
        """
        sig = self.samples.get(signal_key)
        if sig is None:
            raise KeyError(f"No signal named {signal_key!r}")
        hrv = Events.detect(
            sig,
            min_peak_distance_ms=min_peak_distance_ms,
            window_length=window_length,
            n_std=n_std,
            max_ibi_sec=max_ibi_sec,
            classify=classify,
        )
        return Session(
            name=self.name,
            samples=self.samples,
            events={**self.events, events_key: hrv},
            intervals=self.intervals,
            epochs=self.epochs,
        )

    def with_detected_phases(
        self,
        signal_key: str = "resp",
        *,
        intervals_key: str = "breath",
        smooth_window: int = 5,
    ) -> Session:
        """Return a new ``Session`` with breath phases detected from *signal_key*.

        The detected :class:`~._core.Intervals` is stored under *intervals_key*
        (default ``"breath"``).  R-peaks must already be present under ``"hrv"``.
        """
        sig = self.samples.get(signal_key)
        if sig is None:
            raise KeyError(f"No signal named {signal_key!r}")
        if self.hrv is None:
            raise RuntimeError("Detect beats first (with_detected_beats) before phases.")
        phases = Intervals.detect_breath_phases(sig, self.hrv, smooth_window=smooth_window)
        return Session(
            name=self.name,
            samples=self.samples,
            events=self.events,
            intervals={**self.intervals, intervals_key: phases},
            epochs=self.epochs,
        )
