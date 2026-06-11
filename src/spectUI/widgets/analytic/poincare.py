# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`PoincareWidget` — the IBI Poincaré scatter dock.

Plots ``IBIₙ`` vs ``IBIₙ₊₁`` for the R-peaks of the active epoch, with the
SD1/SD2 dispersion ellipse and the line of identity.  Both the point cloud
(:func:`poincare_pairs`) and the ellipse descriptors
(:func:`poincare_descriptors`) are computed in ``spectHR``; the widget only
draws.  Refreshed by the coordinator whenever the R-peaks change.
"""
from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Ellipse

from spectHR.analysis.derived_series import poincare_descriptors, poincare_pairs
from spectUI.widgets.analytic.base import AnalyticView

_C_POINT = "#2980b9"
_C_ELLIPSE = "#c0392b"
_C_IDENTITY = "#7f8c8d"


class PoincareWidget(AnalyticView):
    """IBI Poincaré scatter with the SD1/SD2 ellipse."""

    def _draw(self, fig: Figure) -> None:
        ax = fig.add_subplot(111)
        events = self._epoch_events()

        x, y = poincare_pairs(events) if events is not None else (np.array([]), np.array([]))
        if x.size < 2:
            ax.text(0.5, 0.5, "Not enough beats", ha="center", va="center",
                    transform=ax.transAxes, color="#999")
            ax.set_xticks([]); ax.set_yticks([])
            return

        ax.scatter(x, y, s=6, color=_C_POINT, alpha=0.4, zorder=2, edgecolors="none")

        lo = float(min(x.min(), y.min()))
        hi = float(max(x.max(), y.max()))
        ax.plot([lo, hi], [lo, hi], color=_C_IDENTITY, linewidth=0.8,
                linestyle="--", zorder=1)

        desc = poincare_descriptors(events)
        if desc is not None:
            # Ellipse axes along the identity (SD2) and its normal (SD1).
            ell = Ellipse(
                (desc.cx, desc.cy), width=2 * desc.sd2, height=2 * desc.sd1,
                angle=45.0, facecolor="none", edgecolor=_C_ELLIPSE,
                linewidth=1.5, zorder=3,
            )
            ax.add_patch(ell)
            ax.set_title(
                f"SD1 = {desc.sd1:.1f} ms    SD2 = {desc.sd2:.1f} ms",
                fontsize=9,
            )

        ax.set_xlabel("IBIₙ (ms)")
        ax.set_ylabel("IBIₙ₊₁ (ms)")
        ax.set_aspect("equal", adjustable="datalim")
        fig.tight_layout()

    def _epoch_events(self):
        """The ``"hrv"`` Events restricted to the active epoch, or the whole run."""
        s = self._session
        if s is None or s.hrv is None:
            return None
        ep = s.epochs.get(self._epoch_name) if self._epoch_name else None
        if ep is not None:
            return s.hrv.window(float(ep.start), float(ep.end))
        return s.hrv
