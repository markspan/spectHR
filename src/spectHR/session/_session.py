# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/session/_session.py
"""
:class:`Session`, the root container for one physiological recording.

Architecture
------------
A ``Session`` owns three typed channel dicts (``samples``, ``events``,
``intervals``) and an epoch table.  The channel types,
:class:`~._core.Samples`, :class:`~._core.Events`,
:class:`~._core.Intervals`, are pure data; they know nothing about the
session.  The session is the sole owner; there are no circular references.

Computation flows one way::

    Session  →  AnalysisConfig  →  EpochContext  →  @epoch_metric

:meth:`Session.scoped_to` collapses all channels to a single epoch window
with zero copying and returns a ``Session`` with no epoch table, the
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
# AnalysisConfig, typed replacement for workspace-dict kwargs
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
    # Transfer config: dict with keys input_signal, min_coherence,
    # f_max, and bands {name: (lo, hi)}.  None disables transfer metrics.
    transfer_config:        Any   = None
    prsa_window:            int   = 30
    log_band_power:         bool  = False

    @classmethod
    def from_workspace(cls, workspace: dict | None) -> AnalysisConfig:
        """Build from a raw workspace dict."""
        from spectHR.config import (
            WorkspaceView,
            display_bands_from_workspace,
            transfer_settings_from_workspace,
        )
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
            log_band_power=ws.log_band_power,
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
    error_mask
        Boolean matrix parallel to :attr:`values`, ``True`` where the metric
        *raised* an exception (a real failure, logged when it happened) as
        opposed to legitimately returning ``NaN`` (e.g. too few IBIs to
        compute the metric).  A cell that is ``NaN`` with ``error_mask`` False
        is a valid "not enough data" result, not a bug.  ``None`` on the empty
        table.
    contexts
        ``label → EpochContext`` mapping.  Contexts carry cached PSD,
        RSA, and ICG results so an :class:`~spectHR.analysis.exporter.EpochExporter`
        can reuse them without recomputation.
    """

    labels:     np.ndarray
    columns:    list[str]
    values:     np.ndarray
    contexts:   dict[str, Any]
    error_mask: np.ndarray | None = None


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
    #
    # These resolve a channel by its *canonical* key (plus a couple of close
    # synonyms).  Device-suffixed keys (``ecg-[vuams]``, ``dzdt-[…]``) are
    # aliased onto the canonical keys once, early in the load pipeline, by
    # :func:`spectHR.dataset.preprocessing.apply_canonical_channels`; the
    # device-aware resolvers it uses (``resolve_ecg`` / ``resolve_resp`` / …)
    # are the layer that knows the device-naming conventions.  After that step
    # these getters are all downstream code needs.

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

        The returned session has an empty epoch table, it *is* the epoch.
        All windowing is zero-copy (O(log n) per channel).

        Example, per-breath RSA within one epoch::

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
        from spectHR.analysis.registry import get_metric_groups, get_metrics
        from spectHR.logger import logger

        config = config or AnalysisConfig()
        active = {k: v for k, v in self.epochs.items() if v.active}

        if not active or self.hrv is None:
            return MetricsTable(
                labels=np.array(list(active), dtype=object),
                columns=[],
                values=np.empty((len(active), 0)),
                contexts={},
                error_mask=np.empty((len(active), 0), dtype=bool),
            )

        metrics = get_metrics()
        groups  = get_metric_groups()
        contexts: dict[str, EpochContext] = {}
        rows: list[dict[str, float]] = []
        # Per-row set of column names whose metric *raised* (a real error),
        # kept apart from columns that are legitimately NaN (too little data).
        row_errors: list[set[str]] = []

        for label in active:
            # Zero-copy window every channel to the epoch in one place, then
            # hand the windowed channels plus the shared config to the context.
            scoped = self.scoped_to(label)
            ctx = EpochContext(
                view=scoped.events["hrv"],
                bp_ts=scoped.bp,
                rsp_ts=scoped.resp,
                rsp_phases=scoped.breath,
                icg_ts=scoped.icg,
                ecg_ts=scoped.ecg,
                config=config,
            )
            contexts[label] = ctx

            row: dict[str, float] = {}
            errored: set[str] = set()
            for mname, fn in metrics.items():
                try:
                    val = fn(ctx)
                    # ``None`` means "not applicable" (like NaN), not a failure.
                    row[mname] = np.nan if val is None else float(val)
                except Exception as exc:   # noqa: BLE001, one metric must not abort the table
                    # A raised exception is a genuine failure, not a legitimate
                    # NaN: log it (never silent) and flag the cell so it is
                    # distinguishable from an honest "not enough data" NaN.
                    logger.warning(
                        "Epoch metric %r failed for epoch %r: %s: %s",
                        mname, label, type(exc).__name__, exc,
                    )
                    logger.debug(
                        "Traceback for metric %r (epoch %r):", mname, label,
                        exc_info=True,
                    )
                    row[mname] = np.nan
                    errored.add(mname)
            for gname, fn in groups.items():
                try:
                    extra = fn(ctx)
                    if isinstance(extra, dict):
                        row.update({k: float(v) for k, v in extra.items()})
                except Exception as exc:   # noqa: BLE001
                    # A group failure drops its whole column set for this epoch;
                    # we cannot flag specific cells (the columns are unknown),
                    # but the failure is still logged rather than swallowed.
                    logger.warning(
                        "Epoch metric group %r failed for epoch %r: %s: %s",
                        gname, label, type(exc).__name__, exc,
                    )
                    logger.debug(
                        "Traceback for metric group %r (epoch %r):", gname, label,
                        exc_info=True,
                    )
            rows.append(row)
            row_errors.append(errored)

        all_cols = list(dict.fromkeys(c for r in rows for c in r))
        matrix   = np.full((len(rows), len(all_cols)), np.nan)
        errmask  = np.zeros((len(rows), len(all_cols)), dtype=bool)
        col_idx  = {c: i for i, c in enumerate(all_cols)}
        for i, (row, errored) in enumerate(zip(rows, row_errors)):
            for col, val in row.items():
                matrix[i, col_idx[col]] = val
            for col in errored:
                errmask[i, col_idx[col]] = True

        return MetricsTable(
            labels=np.array(list(active), dtype=object),
            columns=all_cols,
            values=matrix,
            contexts=contexts,
            error_mask=errmask,
        )

    # --- preprocessing helpers (functional, return new Session) ---

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
