# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""PSD configuration dataclasses - algorithm-agnostic.

``BandSpec`` (a frequency-band edge pair) and ``PsdMethod`` (the active
algorithm + its options bundles) live here so the PSD configuration types
sit alongside the algorithm-specific options dataclasses
(``WelchOptions``, ``LombscargleOptions``, ``CarspanOptions``).

``spectHR.analysis.psd`` re-exports :class:`BandSpec` and :class:`PsdMethod`
so callers can import them from the package root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal

from spectHR.analysis.psd._welch import WelchOptions
from spectHR.analysis.psd._lombscargle import LombscargleOptions
from spectHR.analysis.psd._carspan import CarspanOptions


__all__ = [
    "Algorithm",
    "MeanConvention",
    "BandSpec",
    "PsdMethod",
    "respiration_min",
    "respiration_max",
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
    JSON (which is the source of truth for any display attribute) - the
    fields on this dataclass were never consumed. Display attributes
    are now a UI-layer concern only; the library cares about the
    frequency edges.

    Respiration-tracked bands
    -------------------------
    When ``respiration_band`` is True, the profile builder
    (:func:`~spectHR.analysis.profile.compute_band_power_profile`) centers the
    band on the per-window breathing frequency using dedicated half-width fields
    :attr:`resp_low` and :attr:`resp_high`, which are completely
    independent of the absolute-Hz edges :attr:`low` / :attr:`high`.
    This mirrors CARSPAN's ``TAnaBand.RespirationBand`` flag and the
    :func:`respiration_min` / :func:`respiration_max` helpers below - a
    direct port of Pascal's ``GetRespirationMinBandValue`` /
    ``GetRespirationMaxBandValue`` (``T_AnaFunctions.pas`` 2837-2884).

    For example, a band configured with ``resp_low=0.04, resp_high=0.04,
    respiration_band=True`` evaluated inside a window whose mean
    breathing frequency is 0.27 Hz becomes the absolute band
    ``[0.23, 0.31] Hz`` for that window. The static edges
    ``low`` / ``high`` are left untouched and remain the edges used by
    whole-epoch :meth:`band_power` and :meth:`band_powers`.

    Static bands (``respiration_band=False``, the default) use
    ``low`` / ``high`` unconditionally. The ``respiration_band`` flag
    is consulted only by the profile builder.
    """

    low: float
    high: float
    respiration_band: bool = False
    # Half-widths used when respiration_band=True. The band edge becomes
    # [resp_freq - resp_low, resp_freq + resp_high] per profile window.
    # Stored separately from low/high so the static PSD edges are never
    # overwritten by the researcher setting up adaptive tracking.
    resp_low: float = 0.04
    resp_high: float = 0.04


def respiration_min(
    band: BandSpec,
    resp_freq_hz: float,
    freq_max_hz: float,
) -> float:
    """CARSPAN ``GetRespirationMinBandValue`` - port of
    ``T_AnaFunctions.pas`` 2837-2862.

    For a respiration-tracked band, :attr:`BandSpec.resp_low` is the
    **lower half-width** below ``resp_freq_hz``. A ``0.01 Hz`` floor
    and a ``freq_max_hz`` cap are applied identically to the Pascal
    helper.

    Parameters
    ----------
    band : BandSpec
        The configured band.
    resp_freq_hz : float
        Estimated mean breathing frequency inside the window (Hz).
    freq_max_hz : float
        Upper frequency of the per-window PSD grid - the Nyquist
        equivalent ``(PDSin_BCK.Count-1)·FreqRes`` in Pascal terms.

    Returns
    -------
    float
        The absolute lower edge of the band, ready for
        :func:`band_power_rectangular`.
    """
    if not band.respiration_band:
        return band.low
    # Bail-out: respiration too slow for the band even to start.
    if band.resp_low > freq_max_hz:
        return freq_max_hz
    # Avoid a near-DC lower edge - CARSPAN's hard floor.
    if (resp_freq_hz - band.resp_low) < 0.01:
        return 0.01
    return resp_freq_hz - band.resp_low


def respiration_max(
    band: BandSpec,
    resp_freq_hz: float,
    freq_max_hz: float,
) -> float:
    """CARSPAN ``GetRespirationMaxBandValue`` - port of
    ``T_AnaFunctions.pas`` 2865-2884.

    For a respiration-tracked band, :attr:`BandSpec.resp_high` is the
    **upper half-width** above ``resp_freq_hz``. Cap at
    ``freq_max_hz`` identically to the Pascal helper.

    Parameters
    ----------
    band : BandSpec
        The configured band.
    resp_freq_hz : float
        Estimated mean breathing frequency inside the window (Hz).
    freq_max_hz : float
        Upper frequency of the per-window PSD grid - the Nyquist
        equivalent ``(PDSin_BCK.Count-1)·FreqRes`` in Pascal terms.

    Returns
    -------
    float
        The absolute upper edge of the band, ready for
        :func:`band_power_rectangular`.
    """
    if not band.respiration_band:
        return band.high
    if (resp_freq_hz + band.resp_high) > freq_max_hz:
        return freq_max_hz
    return resp_freq_hz + band.resp_high


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

    Built by the spectUI layer via :attr:`~spectUI.parameters.Parameters.psd_method`
    and passed explicitly to ``PSDEngine.compute`` or ``compute_band_power_profile``.
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

    detrend_lambda: float = 0.0
    """Optional smoothness-priors (Tarvainen 2002) detrending strength.
    ``0`` (default) disables it. When > 0 the IBI tachogram is detrended
    before the **tachogram-based** PSD methods (Welch, Lomb-Scargle); the
    faithful CARSPAN paths are never altered. Larger values remove slower
    trends (a typical choice is ~500)."""


_DEFAULT_PSD_METHOD = PsdMethod()
