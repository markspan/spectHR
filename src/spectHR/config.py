# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/config.py
"""
Headless configuration bridge: workspace dict -> spectHR algorithm parameters.

These functions translate the application's plain (JSON-serialisable)
*workspace* configuration dict into the concrete parameter objects the
headless analysis layer consumes — :class:`~spectHR.analysis.psd._config.PsdMethod`,
band tables, and the flat settings dicts read by the profile / transfer /
spectrogram computations.

The whole module is **Qt-free and UI-free**: it depends only on the
standard library and ``spectHR.analysis``. It lives in ``spectHR`` (not
``spectUI``) precisely so that scripts, the test-suite, and any headless
caller can build a ``PsdMethod`` from a config dict *without* importing the
Qt UI. The ``spectUI`` layer exposes these via :class:`~spectUI.parameters.Parameters`
typed properties.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Dict

from spectHR.analysis.psd._config import BandSpec, PsdMethod
from spectHR.analysis.psd._welch import WelchOptions
from spectHR.analysis.psd._lombscargle import LombscargleOptions
from spectHR.analysis.psd._carspan import CarspanOptions


__all__ = [
    "WorkspaceView",
    "display_bands_from_workspace",
    "psd_ci_alpha",
    "bp_calibration_from_workspace",
    "log_level_from_workspace",
    "LOG_LEVELS",
    "profile_settings_from_workspace",
    "resolved_profile_bands",
    "spectrogram_settings_from_workspace",
    "transfer_settings_from_workspace",
    "psd_method_from_workspace",
    "RSP_SOURCES",
    "rsp_source_from_workspace",
    "RSA_REJECTION_MODES",
    "rsa_rejection_from_workspace",
    "CardioParams",
    "cardio_params_from_workspace",
]


# ---------------------------------------------------------------------------
# Cardio preprocessing / R-peak detection / IBI classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardioParams:
    """R-peak detection, ECG preprocessing and IBI-classification settings.

    Mirrors the workspace ``CardioParameters`` section.  One object carries
    everything the preprocessing pipeline needs — the ECG prefilter, the
    peak-detector refractory period, and the rolling-window IBI classifier
    thresholds — so detection and post-edit re-classification stay in lockstep.

    Attributes
    ----------
    window_length, n_std, max_ibi_sec
        Passed straight to :func:`~spectHR.Tools.IbiClassification.classify_ibi`.
    min_peak_distance_ms
        Refractory period for :func:`~spectHR.Tools.RPeakDetection.detect_rpeaks`.
    ecg_filter_type
        ``"highpass"`` / ``"lowpass"`` prefilter applied to the ECG before
        detection, or ``None`` to skip filtering.
    ecg_filter_cutoff
        Prefilter cutoff in Hz.
    """

    window_length:        int   = 20
    n_std:                float = 3.0
    max_ibi_sec:          float = 2.5
    min_peak_distance_ms: float = 300.0
    ecg_filter_type:      str | None = "highpass"
    ecg_filter_cutoff:    float = 0.5
    display_filtered:     bool  = False

    @property
    def classify_kwargs(self) -> "Dict[str, Any]":
        """Keyword args for :func:`classify_ibi` (window_length, n_std, max_ibi_sec)."""
        return {
            "window_length": self.window_length,
            "n_std":         self.n_std,
            "max_ibi_sec":   self.max_ibi_sec,
        }


def cardio_params_from_workspace(workspace: "Dict[str, Any] | None") -> CardioParams:
    """Build a :class:`CardioParams` from a workspace dict (defaults when absent)."""
    cp  = (workspace or {}).get("CardioParameters", {}) or {}
    ibi = cp.get("IbiClassification", {}) or {}
    ecg = cp.get("EcgPreprocessing", {}) or {}
    filt = ecg.get("filter_type", "highpass")
    return CardioParams(
        window_length=int(ibi.get("window_length", 20)),
        n_std=float(ibi.get("n_std", 3.0)),
        max_ibi_sec=float(ibi.get("max_ibi_sec", 2.5)),
        min_peak_distance_ms=float(ibi.get("min_peak_distance_ms", 300.0)),
        ecg_filter_type=(str(filt) if filt else None),
        ecg_filter_cutoff=float(ecg.get("filter_cutoff", 0.5)),
        display_filtered=bool(ecg.get("display_filtered", False)),
    )


# ---------------------------------------------------------------------------
# Frequency-analysis helpers
# ---------------------------------------------------------------------------


def display_bands_from_workspace(workspace: "Dict[str, Any] | None") -> Dict[str, dict]:
    """Return the raw bands dict from the workspace for plot rendering.

    The plotting helpers (``_band_bounds``, ``_draw_band_fill``, etc.) work
    on this raw ``{name: {low, high, color, alpha, ...}}`` form. A separate
    :class:`PsdMethod` is built from the same source for the compute path.
    """
    if workspace is None:
        return {}
    return dict((workspace.get("FrequencyAnalysis", {}) or {}).get("bands", {}) or {})


def psd_ci_alpha(workspace: "Dict[str, Any] | None") -> float:
    """Read ``FrequencyAnalysis.confidence_interval_alpha``, default 0.05."""
    if workspace is None:
        return 0.05
    fa = workspace.get("FrequencyAnalysis", {}) or {}
    return float(fa.get("confidence_interval_alpha", 0.05))


def bp_calibration_from_workspace(
    workspace: "Dict[str, Any] | None",
) -> "tuple[float, float]":
    """Return ``(bp_scale, bp_zero)`` for the manual BP calibration.

    The blood-pressure waveform is converted from raw ADC counts to mmHg
    via ``mmHg = bp_scale * raw + bp_zero``. Defaults mirror
    ``_DEFAULT_WORKSPACE["Calibration"]`` (0.125 / 0.0, the values the
    CARSPAN manual's worked example specifies for ``example1.nff``).
    """
    if workspace is None:
        return 0.125, 0.0
    cal = workspace.get("Calibration", {}) or {}
    return (
        float(cal.get("bp_scale", 0.125)),
        float(cal.get("bp_zero", 0.0)),
    )


#: Accepted respiration sources for ICG-capable (VU-AMS) recordings. Also
#: the choice list the workspace editor offers for
#: ``RespirationAnalysis.rsp_source``.
RSP_SOURCES = ("icg", "accelerometer")
_DEFAULT_RSP_SOURCE = "icg"


def rsp_source_from_workspace(workspace: "Dict[str, Any] | None") -> str:
    """Return the configured respiration source for ICG-capable recordings.

    One of :data:`RSP_SOURCES`:

    * ``"icg"`` (default) — the thoracic-impedance (ICG / dZ) signal, which
      VU-AMS itself segments breaths and scores RSA from.
    * ``"accelerometer"`` — the 3-axis chest-wall accelerometer PCA
      surrogate (for ambulatory recordings or devices without an ICG
      channel).

    Falls back to ``"icg"`` when the workspace, section, or value is missing
    or unrecognised.
    """
    if workspace is None:
        return _DEFAULT_RSP_SOURCE
    ra = workspace.get("RespirationAnalysis", {}) or {}
    src = str(ra.get("rsp_source", _DEFAULT_RSP_SOURCE)).lower()
    return src if src in RSP_SOURCES else _DEFAULT_RSP_SOURCE


#: Accepted RSA breath-rejection modes for the ``RespirationAnalysis`` workspace
#: section.  Also the choice list the workspace editor offers for
#: ``RespirationAnalysis.rsa_rejection_mode``.
#:
#: * ``"none"``   — no extra rejection; all valid INH→EXH pairs are scored
#:                  (default, preserves the legacy spectHR behaviour).
#: * ``"strict"`` — apply the two automatic rejection guards that VU-DAMS runs
#:                  by default (Appendix A, DAMS 5.0 manual):
#:                  - code -5: exclude IBIs that deviate >50 % from the
#:                    preceding IBI from the shortest/longest candidate pool.
#:                  - code -6: reject a whole breath whose respiration rate
#:                    deviates >50 % from the running average of the 20
#:                    preceding breaths.
RSA_REJECTION_MODES = ("none", "strict")
_DEFAULT_RSA_REJECTION_MODE = "none"

# VU-DAMS default thresholds — both 50 % (Appendix A).
# Imported by bp_metrics too; kept here as the single source of truth.
_STRICT_IBI_DEV: float = 0.50   # code -5: max fractional IBI-to-IBI deviation
_STRICT_RATE_DEV: float = 0.50  # code -6: max fractional rate deviation from 20-breath avg


def rsa_rejection_from_workspace(
    workspace: "Dict[str, Any] | None",
) -> "tuple[float | None, float | None]":
    """Return ``(max_ibi_deviation, max_rate_deviation)`` for the configured mode.

    Returns ``(None, None)`` for mode ``"none"`` (no rejection guards).
    Returns ``(_STRICT_IBI_DEV, _STRICT_RATE_DEV)`` for mode ``"strict"``.
    Falls back to ``"none"`` when the workspace key is absent or unrecognised.
    """
    if workspace is None:
        return None, None
    ra = workspace.get("RespirationAnalysis", {}) or {}
    mode = str(ra.get("rsa_rejection_mode", _DEFAULT_RSA_REJECTION_MODE)).lower()
    if mode not in RSA_REJECTION_MODES:
        mode = _DEFAULT_RSA_REJECTION_MODE
    if mode == "strict":
        return _STRICT_IBI_DEV, _STRICT_RATE_DEV
    return None, None


#: Accepted log-level names, most verbose first. Also the choice list the
#: workspace editor offers for ``Logging.level``.
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_DEFAULT_LOG_LEVEL = "INFO"


def log_level_from_workspace(workspace: "Dict[str, Any] | None") -> int:
    """Return the configured minimum log level as a ``logging`` constant.

    Reads ``workspace["Logging"]["level"]`` (one of :data:`LOG_LEVELS`) and
    maps it to the numeric level (e.g. ``"WARNING" -> logging.WARNING``).
    Falls back to ``INFO`` when the workspace, section, or name is missing
    or unrecognised.
    """
    name = _DEFAULT_LOG_LEVEL
    if workspace is not None:
        log_cfg = workspace.get("Logging", {}) or {}
        name = str(log_cfg.get("level", _DEFAULT_LOG_LEVEL)).upper()
    return getattr(logging, name, logging.INFO)


# ---------------------------------------------------------------------------
# Profile / spectrogram / transfer settings
# ---------------------------------------------------------------------------


def profile_settings_from_workspace(
    workspace: "Dict[str, Any] | None",
) -> Dict[str, Any]:
    """Return ``workspace["Profiles"]`` flattened with defaults applied.

    ``window (sec)`` / ``step (sec)`` are the canonical key names; the
    legacy ``window_s`` / ``step_s`` spellings are still accepted as a
    fallback so older workspace files don't break.

    Returned keys: ``window_s``, ``step_s``, ``bands``,
    ``smooth_for_display``, ``adaptive_source``, ``smooth_breath_freq``,
    ``adaptive_bands``.
    """
    if workspace is None:
        return {
            "window_s": 30.0,
            "step_s": 5.0,
            "bands": [],
            "smooth_for_display": False,
            "adaptive_source": "respiration_channel",
            "smooth_breath_freq": False,
            "adaptive_bands": {},
        }
    profs = workspace.get("Profiles", {}) or {}
    return {
        "window_s": float(profs.get("window (sec)", profs.get("window_s", 30.0))),
        "step_s": float(profs.get("step (sec)", profs.get("step_s", 5.0))),
        "bands": list(profs.get("bands", []) or []),
        "smooth_for_display": bool(profs.get("smooth_for_display", False)),
        "adaptive_source": str(profs.get("adaptive_source", "respiration_channel")),
        "smooth_breath_freq": bool(profs.get("smooth_breath_freq", False)),
        "adaptive_bands": dict(profs.get("adaptive_bands", {}) or {}),
    }


def resolved_profile_bands(
    workspace: "Dict[str, Any] | None",
) -> "tuple[list[str], str | None]":
    """Return ``(effective_bands, adaptive_band_name)`` for profile display/export.

    Centralises the band-selection rule used by both ``ProfilePlotWidget``
    and the profile CSV exporter so they always show the same bands:

    * If an adaptive band is configured **and** that band exists in the
      workspace's ``FrequencyAnalysis.bands`` → return ``[adaptive_name]``
      and ``adaptive_name``.
    * Otherwise return the user-selected static list filtered against the
      live band universe, with a fallback to *all* bands when nothing is
      selected.  ``adaptive_band_name`` is ``None``.

    Parameters
    ----------
    workspace
        Full workspace dict (or ``None``).

    Returns
    -------
    effective_bands : list[str]
        Band names in workspace display order.
    adaptive_band_name : str or None
        Name of the active adaptive band, or ``None``.
    """
    cfg = profile_settings_from_workspace(workspace)
    fa = (workspace or {}).get("FrequencyAnalysis", {}) or {}
    all_bands = list((fa.get("bands", {}) or {}).keys())

    adaptive_bands = cfg["adaptive_bands"]
    adaptive_name = next(iter(adaptive_bands), None)
    if adaptive_name and adaptive_name in all_bands:
        return [adaptive_name], adaptive_name

    static = [n for n in cfg["bands"] if n in all_bands]
    # Fall back to all configured bands when the static selection is empty
    # (nothing ticked in Profile Settings) so neither the plot nor the CSV
    # silently shows nothing.
    return (static or all_bands), None


def spectrogram_settings_from_workspace(
    workspace: "Dict[str, Any] | None",
) -> Dict[str, Any]:
    """Return ``workspace["Spectrogram"]`` flattened with defaults applied.

    Reads from two workspace chapters: ``Spectrogram`` for window /
    step / overlay / colormap, and ``Profiles`` for ``adaptive_source``
    so the spectrogram and profile views agree on how the per-window
    breathing frequency is derived.

    Returned keys: ``window_s``, ``step_s``, ``show_respiration_overlay``,
    ``colormap``, ``adaptive_source``.
    """
    default_colormap = "RdYlBu_r"
    if workspace is None:
        return {
            "window_s": 30.0,
            "step_s": 5.0,
            "show_respiration_overlay": True,
            "colormap": default_colormap,
            "adaptive_source": "respiration_channel",
        }
    spec = workspace.get("Spectrogram", {}) or {}
    profs = workspace.get("Profiles", {}) or {}
    return {
        "window_s": float(spec.get("window (sec)", spec.get("window_s", 30.0))),
        "step_s": float(spec.get("step (sec)", spec.get("step_s", 5.0))),
        "show_respiration_overlay": bool(spec.get("show_respiration_overlay", True)),
        "colormap": str(spec.get("colormap", default_colormap)),
        "adaptive_source": str(profs.get("adaptive_source", "respiration_channel")),
    }


def transfer_settings_from_workspace(
    workspace: "Dict[str, Any] | None",
) -> Dict[str, Any]:
    """Return ``workspace["TransferAnalysis"]`` flattened with defaults applied.

    Returned keys: ``input_signal``, ``window_s``, ``step_s``,
    ``min_coherence``, ``f_min``, ``f_max``, ``smooth``, ``phase_view``,
    ``show_coherence_threshold``, ``coherence_mask_alpha``.

    The Bode-plot widgets read this dict directly, the band edges they
    feed to :func:`spectHR.analysis.transfer.compute_transfer` are
    pulled separately from ``FrequencyAnalysis.bands`` via
    :func:`display_bands_from_workspace`.
    """
    defaults = {
        "input_signal": "bp_sys",
        "window_s": 30.0,
        "step_s": 5.0,
        "min_coherence": 0.5,
        "f_min": 0.0,
        "f_max": 0.5,
        "smooth": True,
        "phase_view": "wrapped",
        "show_coherence_threshold": True,
        "coherence_mask_alpha": 0.20,
    }
    if workspace is None:
        return defaults
    cfg = workspace.get("TransferAnalysis", {}) or {}
    return {
        "input_signal": str(cfg.get("input_signal", defaults["input_signal"])),
        "window_s": float(
            cfg.get("window (sec)", cfg.get("window_s", defaults["window_s"]))
        ),
        "step_s": float(cfg.get("step (sec)", cfg.get("step_s", defaults["step_s"]))),
        "min_coherence": float(cfg.get("min_coherence", defaults["min_coherence"])),
        "f_min": float(cfg.get("f_min", defaults["f_min"])),
        "f_max": float(cfg.get("f_max", defaults["f_max"])),
        "smooth": bool(cfg.get("smooth", defaults["smooth"])),
        "phase_view": str(cfg.get("phase_view", defaults["phase_view"])),
        "show_coherence_threshold": bool(
            cfg.get("show_coherence_threshold", defaults["show_coherence_threshold"])
        ),
        "coherence_mask_alpha": float(
            cfg.get("coherence_mask_alpha", defaults["coherence_mask_alpha"])
        ),
    }


# ---------------------------------------------------------------------------
# PsdMethod construction
# ---------------------------------------------------------------------------


def _bands_from_workspace(
    bands_dict: Dict[str, dict],
    adaptive_bands: "Dict[str, dict] | None" = None,
) -> Dict[str, BandSpec]:
    """Convert the workspace bands subdict to ``Dict[str, BandSpec]``.

    Frequency edges (``low`` / ``high``) come from each band's own
    entry in ``FrequencyAnalysis.bands``. Display attributes
    (``color``, ``alpha``) stay on the raw workspace dict and are
    consumed directly by ``PSDPlotWidget``.

    Adaptive (respiration-centered) half-widths come from
    ``Profiles.adaptive_bands``, a dict that maps band name to
    ``{"lower half-width (Hz)": float, "upper half-width (Hz)": float}``.
    Only bands listed there get ``respiration_band=True``; the others
    keep static edges.
    """
    adaptive = adaptive_bands or {}
    return {
        name: BandSpec(
            low=float(spec["low"]),
            high=float(spec["high"]),
            respiration_band=(name in adaptive),
            resp_low=float(adaptive[name].get("lower half-width (Hz)", 0.04))
            if name in adaptive
            else 0.04,
            resp_high=float(adaptive[name].get("upper half-width (Hz)", 0.04))
            if name in adaptive
            else 0.04,
        )
        for name, spec in bands_dict.items()
    }


def _filter_kwargs(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the keys *cls* accepts; silently drop unknown ones.

    Lets the workspace JSON carry forward-compatible extra keys without
    blowing up the dataclass constructor.
    """
    try:
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
    except AttributeError:
        allowed = set()
    return {k: v for k, v in raw.items() if k in allowed}


def psd_method_from_workspace(workspace: Dict[str, Any]) -> PsdMethod:
    """Build a :class:`PsdMethod` from a workspace dict."""
    fa = workspace.get("FrequencyAnalysis", {}) or {}

    profiles_cfg = workspace.get("Profiles", {}) or {}
    adaptive_bands = dict(profiles_cfg.get("adaptive_bands", {}) or {})

    bands = _bands_from_workspace(fa.get("bands", {}), adaptive_bands)
    # ``f_max`` must extend at least to the highest configured band edge,
    # otherwise the band-power integration would silently truncate
    # FullRange. Override whatever the JSON has.
    f_max = max((b.high for b in bands.values()), default=0.5)

    welch_cfg = _filter_kwargs(WelchOptions, dict(fa.get("welch", {})))
    welch_opts = WelchOptions(**welch_cfg)

    ls_cfg = _filter_kwargs(LombscargleOptions, dict(fa.get("lombscargle", {})))
    ls_opts = LombscargleOptions(**ls_cfg)

    carspan_cfg = _filter_kwargs(CarspanOptions, dict(fa.get("carspan", {})))
    carspan_cfg["f_max"] = f_max
    carspan_opts = CarspanOptions(**carspan_cfg)

    algorithm = str(fa.get("method", "carspan"))
    mean_convention = "arithmetic" if algorithm == "carspan_strict" else "harmonic"

    return PsdMethod(
        algorithm=algorithm,
        bands=bands,
        alpha_ci=float(fa.get("confidence_interval_alpha", 0.05)),
        mean_convention=mean_convention,
        welch=welch_opts,
        lombscargle=ls_opts,
        carspan=carspan_opts,
        detrend_lambda=(
            float(fa.get("detrend_lambda", 500.0) or 500.0)
            if fa.get("detrend", False)
            else 0.0
        ),
    )


# ---------------------------------------------------------------------------
# Typed workspace accessor
# ---------------------------------------------------------------------------


class WorkspaceView:
    """Read-only typed view over a workspace configuration dict.

    Build once from the raw workspace dict, then access all analysis settings
    as typed attributes instead of repeated ``(workspace or {}).get(...)``
    lookups.  Expensive settings (PSD method, profile/transfer/spectrogram
    configs) are cached via ``cached_property`` so they are parsed at most once
    per ``WorkspaceView`` instance regardless of how many call sites access them.

    All existing ``*_from_workspace`` standalone functions remain unchanged and
    are the implementation back-end of the matching properties here.  Either
    interface works; ``WorkspaceView`` is preferred when multiple settings are
    needed from the same workspace in the same call scope.

    Example
    -------
    >>> ws = WorkspaceView(workspace)
    >>> method = ws.psd_method         # PsdMethod
    >>> lag, (idev, rdev) = ws.rsa_lag_s, ws.rsa_rejection
    """

    __slots__ = ("_ws", "__dict__")   # __dict__ needed for cached_property storage

    def __init__(self, workspace: "Dict[str, Any] | None") -> None:
        self._ws: Dict[str, Any] = workspace or {}

    # ---- frequency analysis -----------------------------------------

    @cached_property
    def psd_method(self) -> PsdMethod:
        """Parameters-configured :class:`~spectHR.analysis.psd._config.PsdMethod`."""
        return psd_method_from_workspace(self._ws)

    @property
    def psd_ci_alpha(self) -> float:
        """Confidence-interval alpha (default 0.05)."""
        fa = self._ws.get("FrequencyAnalysis", {}) or {}
        return float(fa.get("confidence_interval_alpha", 0.05))

    @property
    def display_bands(self) -> Dict[str, dict]:
        """Raw ``{name: {low, high, color, …}}`` bands dict for plot rendering."""
        return dict(
            (self._ws.get("FrequencyAnalysis", {}) or {}).get("bands", {}) or {}
        )

    # ---- calibration ------------------------------------------------

    @property
    def bp_calibration(self) -> "tuple[float, float]":
        """``(bp_scale, bp_zero)`` for manual BP calibration."""
        cal = self._ws.get("Calibration", {}) or {}
        return float(cal.get("bp_scale", 0.125)), float(cal.get("bp_zero", 0.0))

    # ---- respiration / RSA ------------------------------------------

    @property
    def rsp_source(self) -> str:
        """Respiration source: ``"icg"`` or ``"accelerometer"``."""
        return rsp_source_from_workspace(self._ws)

    @property
    def rsa_lag_s(self) -> float:
        """RSA window lag in seconds (default 1.0)."""
        ra = self._ws.get("RespirationAnalysis", {}) or {}
        return float(ra.get("rsa_lag_s", 1.0))

    @property
    def rsp_per_epoch(self) -> bool:
        """Detect breath phases per epoch (default False).

        When True, the respiration surrogate is rebuilt and segmented within
        each epoch separately.  For the accelerometer source this re-runs the
        PCA per epoch, so a posture change between epochs no longer corrupts a
        single global principal axis.
        """
        ra = self._ws.get("RespirationAnalysis", {}) or {}
        return bool(ra.get("per_epoch", False))

    @property
    def rsa_rejection(self) -> "tuple[float | None, float | None]":
        """``(max_ibi_deviation, max_rate_deviation)`` for the configured mode."""
        return rsa_rejection_from_workspace(self._ws)

    @property
    def rsa_overlay(self) -> str:
        """RSA overlay choice (``"rsa"`` or ``"rsa0"``, default ``"rsa0"``)."""
        ra = self._ws.get("RespirationAnalysis", {}) or {}
        return str(ra.get("rsa_overlay", "rsa0"))

    # ---- cardio / R-peak detection ----------------------------------

    @cached_property
    def cardio_params(self) -> CardioParams:
        """ECG preprocessing, R-peak detection and IBI-classification settings."""
        return cardio_params_from_workspace(self._ws)

    # ---- ICG --------------------------------------------------------

    @property
    def b_point_guard_ms(self) -> float:
        """PEP B-point guard zone width in ms (default 30)."""
        icg = self._ws.get("IcgAnalysis", {}) or {}
        return float(icg.get("b_point_guard_ms", 30.0))

    @property
    def prsa_window(self) -> int:
        """PRSA half-window size in beats (default 30, Bauer 2006)."""
        pa = (self._ws.get("CardioParameters", {}) or {}).get("PrsaAnalysis", {}) or {}
        return int(pa.get("prsa_window", 30))

    # ---- profile / spectrogram / transfer ---------------------------

    @cached_property
    def profile_settings(self) -> Dict[str, Any]:
        """Flattened profile settings dict (window_s, step_s, bands, …)."""
        return profile_settings_from_workspace(self._ws)

    @cached_property
    def resolved_profile_bands(self) -> "tuple[list[str], str | None]":
        """``(effective_bands, adaptive_band_name)`` for profile display/export."""
        return resolved_profile_bands(self._ws)

    @cached_property
    def spectrogram_settings(self) -> Dict[str, Any]:
        """Flattened spectrogram settings dict."""
        return spectrogram_settings_from_workspace(self._ws)

    @cached_property
    def transfer_settings(self) -> Dict[str, Any]:
        """Flattened transfer-function settings dict."""
        return transfer_settings_from_workspace(self._ws)

    # ---- logging ----------------------------------------------------

    @property
    def log_level(self) -> int:
        """Configured minimum log level as a ``logging`` constant."""
        return log_level_from_workspace(self._ws)
