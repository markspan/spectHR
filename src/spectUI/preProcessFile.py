# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pre-processing helpers: BP calibration and respiration-source selection.

These are pure Session → Session transforms — no Qt, no side effects.
The preprocessing *widget* (PrepPlotWidget) will be built separately.
"""
from __future__ import annotations

import numpy as np

from spectHR.session import Events, Session, Samples
from spectHR.config import CardioParams, WorkspaceView
from spectHR.Tools.Logger import logger

# Accept either a Parameters instance (spectUI) or a raw dict (headless / tests).
_ParamsLike = "WorkspaceView | dict | None"


def _as_view(params: _ParamsLike) -> WorkspaceView:
    """Return a WorkspaceView regardless of whether *params* is already one."""
    if isinstance(params, WorkspaceView):
        return params
    return WorkspaceView(params)


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------
#
# Loaders disagree on sample-channel keys: the NFF/EVT path uses canonical
# ``"ecg"`` / ``"resp"`` keys, while the XDF/EDF paths suffix them with the
# device id (``"ecg-[8554112A]"``, ``"RSP-[8554112A]"``).  These resolvers
# prefer the canonical accessor and fall back to a case-insensitive prefix
# scan, so every downstream consumer (detection here, display in the prep
# widget) finds the same channel regardless of source.


def resolve_ecg(session: Session) -> Samples | None:
    """Return the ECG channel: canonical ``"ecg"`` or first ``ecg*`` channel."""
    return session.ecg or _first_with_prefix(session, ("ecg",))


def resolve_resp(session: Session) -> Samples | None:
    """Return the respiration channel: canonical, or first ``resp*`` / ``rsp*``."""
    return session.resp or _first_with_prefix(session, ("resp", "rsp"))


def _first_with_prefix(session: Session, prefixes: tuple[str, ...]) -> Samples | None:
    """First sample channel whose key starts (case-insensitively) with a prefix."""
    for key, sig in session.samples.items():
        if key.lower().startswith(prefixes):
            return sig
    return None


# ---------------------------------------------------------------------------
# ECG preprocessing + R-peak detection
# ---------------------------------------------------------------------------


def filter_ecg(ecg: Samples | None, cardio: CardioParams) -> Samples | None:
    """Apply the configured ECG prefilter, falling back to the raw signal.

    Honours :attr:`CardioParams.ecg_filter_type` / ``ecg_filter_cutoff``
    (e.g. a 0.5 Hz high-pass to strip baseline wander).  Returns the input
    unchanged when no filter is configured, the signal is too short, or the
    cutoff is invalid for the channel's sampling rate.
    """
    if ecg is None or ecg.times.size < 2 or not cardio.ecg_filter_type:
        return ecg
    try:
        return ecg.filtered(
            filter_type=cardio.ecg_filter_type, cutoff=cardio.ecg_filter_cutoff
        )
    except Exception as exc:  # noqa: BLE001 — bad cutoff / too-short signal
        logger.warning("ECG prefilter skipped (%s).", exc)
        return ecg


def apply_beat_detection(session: Session, params: _ParamsLike) -> Session:
    """Return a new ``Session`` with R-peaks detected when none are present.

    Runs on the background load thread (see ``MainWindow._LoadWorker``) so the
    O(n) detection never blocks the UI.  The ECG is resolved (canonical or
    device-suffixed key), prefiltered per ``CardioParameters.EcgPreprocessing``,
    and passed to :meth:`Events.detect` with the workspace
    ``CardioParameters.IbiClassification`` thresholds.  Sessions that already
    carry an ``"hrv"`` channel (e.g. CARSPAN ``.evt`` recordings) — or that
    have no usable ECG — are returned unchanged.
    """
    if session.events.get("hrv") is not None:
        return session

    ecg = resolve_ecg(session)
    if ecg is None or ecg.times.size < 2:
        return session

    cardio = _as_view(params).cardio_params
    filtered = filter_ecg(ecg, cardio)
    try:
        hrv = Events.detect(
            filtered,
            min_peak_distance_ms=cardio.min_peak_distance_ms,
            window_length=cardio.window_length,
            n_std=cardio.n_std,
            max_ibi_sec=cardio.max_ibi_sec,
        )
    except Exception:  # noqa: BLE001 — detection must never abort a load
        logger.exception("R-peak detection failed; loading without beats.")
        return session

    logger.info("Detected %d R-peaks from %s", hrv.times.size, ecg.name or "ecg")
    return Session(
        name=session.name,
        samples=session.samples,
        events={**session.events, "hrv": hrv},
        intervals=session.intervals,
        epochs=session.epochs,
    )


# ---------------------------------------------------------------------------
# BP calibration
# ---------------------------------------------------------------------------


def apply_bp_calibration(session: Session, params: _ParamsLike) -> Session:
    """Return a new ``Session`` with the ``bp`` channel scaled to mmHg.

    Reads ``bp_scale`` and ``bp_zero`` from the analysis parameters and
    applies ``mmHg = scale * raw + zero``.  When scale is zero (no
    calibration available) the channel is left unchanged.
    """
    bp = session.bp
    if bp is None:
        return session

    scale, zero = _as_view(params).bp_calibration
    if scale == 0.0:
        return session

    calibrated = Samples(
        times=bp.times,
        values=bp.values * scale + zero,
        name=bp.name,
    )
    return Session(
        name=session.name,
        samples={**session.samples, "bp": calibrated},
        events=session.events,
        intervals=session.intervals,
        epochs=session.epochs,
    )


# ---------------------------------------------------------------------------
# Respiration source selection
# ---------------------------------------------------------------------------


def apply_rsp_source(session: Session, params: _ParamsLike) -> Session:
    """Return a new ``Session`` with the canonical ``resp`` channel set.

    Reads ``rsp_source`` from the analysis parameters and copies the
    appropriate channel to ``session.samples["resp"]``.

    * ``"icg"`` — uses the ``icg`` channel if present (thoracic impedance).
    * ``"accelerometer"`` — uses ``accel_rsp`` if present (PCA surrogate).

    When the requested source is not available the session is returned
    unchanged.
    """
    source = _as_view(params).rsp_source
    key = "icg" if source == "icg" else "accel_rsp"

    sig = session.samples.get(key)
    if sig is None:
        return session

    rsp = Samples(times=sig.times, values=sig.values, name="resp")
    return Session(
        name=session.name,
        samples={**session.samples, "resp": rsp},
        events=session.events,
        intervals=session.intervals,
        epochs=session.epochs,
    )


# ---------------------------------------------------------------------------
# Stub class (full PrepPlotWidget to be built separately)
# ---------------------------------------------------------------------------


class PreProcessFile:
    """Placeholder — the full preprocessing dialog will be added later."""
