# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pre-processing helpers: BP calibration and respiration-source selection.

These are pure Session → Session transforms — no Qt, no side effects.
The preprocessing *widget* (PrepPlotWidget) will be built separately.
"""
from __future__ import annotations

import numpy as np

from spectHR.session import Session, Samples
from spectHR.config import WorkspaceView

# Accept either a Parameters instance (spectUI) or a raw dict (headless / tests).
_ParamsLike = "WorkspaceView | dict | None"


def _as_view(params: _ParamsLike) -> WorkspaceView:
    """Return a WorkspaceView regardless of whether *params* is already one."""
    if isinstance(params, WorkspaceView):
        return params
    return WorkspaceView(params)


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
