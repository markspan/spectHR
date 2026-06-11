# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`PrepModel` — everything the pre-processing view needs about *one* load.

The widget used to hold a dozen ``| None`` attributes — session, window,
navigator, controller, three channels, the cardio settings — all set
together in ``set_session`` and all guarded with ``assert ... is not None``
on every use.  :class:`PrepModel` bundles them into a single value object
that is *either fully present or absent*: the widget holds one
``PrepModel | None`` and asks one question, ``is a session loaded?``, instead
of twelve.

Building a model is pure (no Qt, no matplotlib): channel resolution, the
detection/classification settings, the editing controller and the initial
window all come together in :meth:`PrepModel.build`, which makes the whole
load step testable without a display.

The matplotlib axes, canvas and blit cache deliberately stay on the widget —
they are render state, not model state, and are rebuilt on every load.
"""
from __future__ import annotations

from dataclasses import dataclass

from spectHR.config import CardioParams
from spectHR.DataSet.preprocessing import filter_ecg, resolve_ecg, resolve_resp
from spectHR.session import Samples, Session
from spectUI.widgets.prep.navigation import TimelineNavigator
from spectUI.widgets.prep.rtop_controller import RTopController
from spectUI.widgets.prep.state import WindowState


@dataclass
class PrepModel:
    """Data and interaction state for one loaded session.

    Attributes
    ----------
    session
        The loaded recording (edits are committed back into it).
    cardio
        Detection / classification / prefilter settings from the workspace.
    ecg
        Raw ECG channel (drives the time extent).  ``None`` when the session
        has no usable ECG.
    ecg_display
        The trace actually plotted: ``ecg`` by default, or its prefiltered
        copy when ``cardio.display_filtered`` is set.
    resp
        Resolved respiration channel, or ``None``.
    rtop_ctrl
        R-peak editing controller, or ``None`` when the session has no
        ``"hrv"`` channel (editing is then disabled).
    window
        The visible time window and any in-progress overview drag.
    navigator
        Zoom / pan / goto arithmetic over :attr:`window`.
    extent
        ``(t_first, t_last)`` of the ECG, or ``None`` — the recording bounds
        navigation clamps to.
    """

    session: Session
    cardio: CardioParams
    ecg: Samples | None
    ecg_display: Samples | None
    resp: Samples | None
    rtop_ctrl: RTopController | None
    window: WindowState
    navigator: TimelineNavigator
    extent: tuple[float, float] | None

    @classmethod
    def build(cls, session: Session, cardio: CardioParams) -> PrepModel:
        """Resolve channels, controller, window and navigator for *session*.

        R-peak detection has already happened on the load thread, so this is
        purely view assembly: it never mutates *session*.  The window opens on
        the full recording; the navigator clamps to the (immutable) ECG extent.
        """
        ecg = resolve_ecg(session)
        ecg_display = filter_ecg(ecg, cardio) if cardio.display_filtered else ecg
        resp = resolve_resp(session)
        rtop_ctrl = (
            RTopController(session, classify_params=cardio.classify_kwargs)
            if session.events.get("hrv") is not None
            else None
        )

        extent: tuple[float, float] | None = None
        if ecg is not None and ecg.times.size:
            extent = (float(ecg.times[0]), float(ecg.times[-1]))

        t0, t1 = extent if extent is not None else (0.0, 1.0)
        window = WindowState(x_min=t0, x_max=t1)
        # The ECG never changes during a session, so the extent is constant —
        # the navigator closes over it rather than re-reading the channel.
        navigator = TimelineNavigator(window, lambda e=extent: e)

        return cls(
            session=session,
            cardio=cardio,
            ecg=ecg,
            ecg_display=ecg_display,
            resp=resp,
            rtop_ctrl=rtop_ctrl,
            window=window,
            navigator=navigator,
            extent=extent,
        )

    def has_resp(self) -> bool:
        """Whether a non-empty respiration channel was resolved."""
        return self.resp is not None and bool(self.resp.times.size)
