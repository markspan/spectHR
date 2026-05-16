"""PSD configuration dataclasses — algorithm-agnostic.

``BandSpec`` (a frequency-band edge pair) and ``PsdMethod`` (the active
algorithm + its options bundles) used to live in
:mod:`spectHR.DataSet.Series.CardioMetricsMixin`. They moved here so the
PSD configuration types sit alongside the algorithm-specific options
dataclasses (``WelchOptions``, ``LombscargleOptions``, ``CarspanOptions``)
instead of being buried inside the mixin file.

``CardioMetricsMixin`` re-exports :class:`BandSpec` and :class:`PsdMethod`
for back-compat, so existing imports
``from spectHR.DataSet.Series.CardioMetricsMixin import BandSpec``
keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal

from spectHR.Tools.PSD.WelchPSD import WelchOptions
from spectHR.Tools.PSD.LombScarglePSD import LombscargleOptions
from spectHR.Tools.PSD.CarspanPSD import CarspanOptions


__all__ = [
    "Algorithm",
    "MeanConvention",
    "BandSpec",
    "PsdMethod",
]


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Algorithm = Literal["welch", "lombscargle", "carspan", "carspan_strict"]
MeanConvention = Literal["harmonic", "arithmetic"]


# ---------------------------------------------------------------------------
# BandSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BandSpec:
    """One HRV band: lower and upper frequency edge, in Hz.

    Earlier versions also carried ``color`` / ``alpha`` for the plot
    widget, but the plot widget reads those straight from the workspace
    JSON (which is the source of truth for any display attribute) — the
    fields on this dataclass were never consumed. Display attributes
    are now a UI-layer concern only; the library cares about the
    frequency edges.
    """

    low: float
    high: float


def _default_bands() -> Dict[str, BandSpec]:
    """Fallback band table used when no PsdMethod is supplied.

    Matches the spectUI workspace defaults.
    """
    return {
        "FullRange": BandSpec(low=0.02, high=0.5),
        "VLF": BandSpec(low=0.02, high=0.06),
        "LF": BandSpec(low=0.07, high=0.14),
        "HF": BandSpec(low=0.15, high=0.40),
    }


# ---------------------------------------------------------------------------
# PsdMethod
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PsdMethod:
    """Full PSD configuration: which algorithm, with which options.

    Built by the spectUI layer from a workspace dict and assigned to
    each series via ``series.psd_method = …``.
    """

    algorithm: Algorithm = "carspan"
    bands: Dict[str, BandSpec] = field(default_factory=_default_bands)
    alpha_ci: float = 0.05
    mean_convention: MeanConvention = "harmonic"
    """Mean rate convention for the events²/Hz → mMI²/Hz conversion.
    ``"harmonic"`` (= ``T/N``) is the manual definition; ``"arithmetic"``
    (= ``Σ 1/IBI / N``) matches the reference CARSPAN Pascal SOC and is
    picked automatically by the UI for ``algorithm == "carspan_strict"``."""

    welch: WelchOptions = field(default_factory=WelchOptions)
    lombscargle: LombscargleOptions = field(default_factory=LombscargleOptions)
    carspan: CarspanOptions = field(default_factory=CarspanOptions)


_DEFAULT_PSD_METHOD = PsdMethod()
