# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import json
import os
from typing import Any, Dict

from spectHR.Tools.Logger import logger
from spectHR.DataSet.Series.CardioMetricsMixin import (
    BandSpec,
    PsdMethod,
)
from spectHR.Tools.PSD.WelchPSD import WelchOptions
from spectHR.Tools.PSD.LombScarglePSD import LombscargleOptions
from spectHR.Tools.PSD.CarspanPSD import CarspanOptions

from platformdirs import user_documents_path
from PySide6.QtWidgets import QTreeWidgetItem
from PySide6.QtCore import Qt

_DEFAULT_WORKSPACE = {
    "Directories": {
        "DataDirectory": str(user_documents_path() / "spectHR"),
        "CacheDirectory": str(user_documents_path() / "spectHR/cache"),
        "OutputDirectory": str(user_documents_path() / "spectHR/export"),
    },
    "FrequencyAnalysis": {
        "method": "carspan",
        "bands": {
            "FullRange": {"low": 0.02, "high": 0.5,  "color": "gray", "alpha": 0.35},
            "VLF":       {"low": 0.02, "high": 0.06, "color": "blue"},
            "LF":        {"low": 0.07, "high": 0.14, "color": "darkgreen"},
            "HF":        {"low": 0.15, "high": 0.40, "color": "red"},
        },
        "carspan": {
            "freq_resolution": 0.01,
            "signal": "events",
            "window": "10% cosine bell",
            "smooth_for_display": True,
            "plot_units": "mMI²/Hz",
            "dc_removal": False,
        },
        "welch": {
            "fs": 4.0,
            "nperseg": 256,
            "noverlap": 128,
            "nfft": 1024,
            "window": "hann",
            "units": "mMI²",
        },
        "lombscargle": {
            "nfreqs": 100,
            "fmin_floor": 1e-4,
            "units": "mMI²",
        },
        "confidence_interval_alpha": 0.05,
    },
    "CardioParameters": {
        "IbiClassification": {
            "window_length": 51,
            "n_std": 4.0,
            "max_ibi_sec": 2.0,
            "min_peak_distance_ms": 300.0,
        },
        "EcgPreprocessing": {
            "filter_type": "highpass",
            "filter_cutoff": 1.0,
        },
    },
    # ------------------------------------------------------------------
    # Spectral profiles
    # ------------------------------------------------------------------
    # A spectral profile is the time course of a band-power measure
    # inside one epoch - implemented as the standard PSD pipeline
    # applied to a window that slides along the recording with a fixed
    # step (see CARSPAN manual §3.3.5, Eq. 3.34 / 3.35). The compute
    # algorithm and band definitions are inherited from
    # ``FrequencyAnalysis`` so a profile of `band X` is computed with
    # the same PSD method (Welch / Lomb-Scargle / CARSPAN / strict) and
    # the same edges as the corresponding PSD band - they're two views
    # of the same underlying analysis.
    #
    # ``bands`` lists the band names (matching keys in
    # ``FrequencyAnalysis.bands``) the profile plot should draw. The
    # profile compute may compute all configured bands; this list is a
    # display filter only.
    #
    # ``window (sec)`` and ``step (sec)`` are the sliding-window parameters
    # in seconds; step must be strictly smaller than window (otherwise
    # there's no overlap → no profile), and the manual recommends
    # window ≥ 3 · 1/f_l_min for reliable estimates.
    # The pre-formatted key names (spaces + parentheses) are intentional:
    # they bypass the _label() camelCase/snake_case splitter and appear
    # in the dialog exactly as written here.
    "Profiles": {
        "window (sec)": 30.0,
        "step (sec)":   5.0,
        "bands":    ["LF", "HF"],
        # ``adaptive_bands`` maps band names to their adaptive half-width
        # settings. Each entry opts that band into respiration-centered
        # profile integration (same idea as CARSPAN's
        # ``TAnaBand.RespirationBand`` flag, "Add variable band" button
        # in ``F_SpecAnalysisProfiles.pas``).
        #
        # Stored here on Profiles - not on FrequencyAnalysis.bands -
        # because the flag is consulted *only* by the sliding-window
        # profile compute (``band_power_profile``). Whole-epoch PSDs and
        # band_powers always use the absolute Hz edges from
        # ``FrequencyAnalysis.bands`` and are unaffected.
        #
        # Format:
        #   {"HF": {"lower half-width (Hz)": 0.04,
        #           "upper half-width (Hz)": 0.04}}
        #
        # "lower half-width (Hz)": how far below the per-window mean
        #   breathing frequency the band edge falls
        #   (band_low  = resp_freq − lower_half_width).
        # "upper half-width (Hz)": how far above it
        #   (band_high = resp_freq + upper_half_width).
        #
        # The static ``FrequencyAnalysis.bands`` edges (``low``/``high``)
        # are left untouched - they remain the edges for whole-epoch
        # band powers and PSD display. Only the profile builder uses
        # these half-widths.
        #
        # Default is empty: every band starts static. Researchers add
        # bands here when their recording involves breathing-rate changes
        # (paced breathing, stress protocols, biofeedback). Typically
        # only HF is tracked. Has effect only when a RespirationSeries
        # is present; without a breathing signal the bands silently fall
        # back to their static edges - exactly what CARSPAN does when
        # ``FRespFreqList`` is empty.
        "adaptive_bands": {},
        # How the per-window breathing frequency is derived for adaptive bands:
        #   "respiration_channel" - CARSPAN-faithful: use the mean breath
        #     frequency from the RespirationSeries in PhysioData.rsp_map.
        #     Falls back to static edges if no respiration channel is loaded.
        #   "psd_peak" - no respiration channel required: find the frequency
        #     of maximum power within the band's static [low, high] range in
        #     the per-window PSD, and centre the adaptive band there.
        "adaptive_source": "respiration_channel",
        # Smooth the per-window breathing frequency before using it to
        # position the adaptive band edges. The same Pascal-faithful
        # 3-point MA kernel used by the PSD smoother is applied to the
        # full sequence of per-window breath frequencies; single-window
        # spikes (e.g. a missed breath cycle or a noisy rsp signal) are
        # replaced by their neighbours' average before the band edges are
        # computed. Setting this to True requires a two-pass calculation
        # (freq-collection pass → smooth → band-power pass); the
        # smoothed frequencies are also what the right-axis overlay in
        # the profile plot draws. Defaults to False (CARSPAN-faithful:
        # raw per-window breathing frequency, no temporal smoothing).
        "smooth_breath_freq": False,
        # Apply Pascal's 3-point MA along each band's time series before
        # plotting. Same kernel + edge policy as the PSD smoother - plot
        # only; band-power integration is unaffected. Defaults to
        # False because the reference Delphi profile view doesn't apply
        # any time-axis smoother - the plotted line is the raw
        # band-power per profile window. Flip to True for an
        # easier-on-the-eye curve when the data is noisy.
        "smooth_for_display": False,
    },
    # ------------------------------------------------------------------
    # Respiration analysis
    # ------------------------------------------------------------------
    # ``RespirationSeries.from_timeseries`` derives its peak-detection
    # prominence from the signal's own MAD/sigma (see the docstring at
    # ``spectHR.DataSet.Series.RespirationSeries.from_timeseries``):
    #
    #   sigma     = 1.4826 · MAD(y)        # robust noise estimate
    #   prominence = prominence_rel · sigma
    #
    # When the full recording mixes resting and task periods, breathing
    # depth and noise level can differ substantially between them. A
    # single global prominence threshold then either misses shallow
    # breaths in one epoch or admits noise as breaths in another. Running
    # the segmentation **per epoch** lets the threshold adapt to each
    # epoch's typical breath amplitude.
    #
    # Set ``per_epoch: true`` to iterate over the recording's epochs and
    # build the RespirationSeries from per-epoch segmentations
    # concatenated together. The default ``experiment`` epoch - which
    # the loaders create as a placeholder spanning the entire recording -
    # is skipped when it still covers the whole signal, so turning the
    # flag on without defining task epochs yet is a no-op.
    "RespirationAnalysis": {
        "per_epoch": False,
    },
}


# ---------------------------------------------------------------------------
# Workspace-level accessors (free functions, since the workspace is a dict)
# ---------------------------------------------------------------------------

# Fallback used by :func:`get_export_dir` when a workspace is missing or
# lacks the ``Directories.OutputDirectory`` entry. Mirrors the value in
# ``_DEFAULT_WORKSPACE`` so the two stay in lock-step automatically.
DEFAULT_EXPORT_DIR = user_documents_path() / "spectHR" / "export"


def get_export_dir(workspace, *, context: str = "Export"):
    """Return ``workspace["Directories"]["OutputDirectory"]`` as a :class:`Path`.

    The workspace is a plain ``dict`` (no class wrapper), so this is the
    canonical accessor for the configured export folder. Centralising it
    here means every widget that writes files (PSDPlotWidget,
    ProfilePlotWidget, ParametersPlotWidget, ...) reaches the directory
    through one code path and shares one fallback rule.

    Parameters
    ----------
    workspace : dict or None
        The workspace dictionary as loaded by :func:`LoadWorkspace`. May
        be ``None`` when a widget was constructed without one.
    context : str, optional
        Short label inserted into the warning message (e.g. ``"PSD"``,
        ``"Profile"``, ``"Parameters"``). Defaults to ``"Export"``.

    Returns
    -------
    pathlib.Path
        The directory the caller should write to. Existence is **not**
        guaranteed - callers should call ``mkdir(parents=True,
        exist_ok=True)`` and handle ``OSError`` themselves.

    Notes
    -----
    When the workspace is ``None`` or the expected nesting is missing
    the function emits a single ``logger.warning`` and falls back to
    :data:`DEFAULT_EXPORT_DIR`, so an export attempt always has somewhere
    to land instead of crashing on a ``KeyError``.
    """
    from pathlib import Path  # localised to keep the module top tidy
    if workspace is not None:
        try:
            return Path(workspace["Directories"]["OutputDirectory"])
        except (KeyError, TypeError):
            logger.warning(
                f"{context} export: workspace lacks "
                "Directories.OutputDirectory; falling back to default "
                "export folder."
            )
    return DEFAULT_EXPORT_DIR


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override values win."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def LoadWorkspace(json_file=None) -> dict:
    """Load the workspace JSON, create the file from defaults if missing.

    Side effects are intentionally minimal: this function only reads /
    writes the JSON file and ensures cache / output directories exist.
    PSD configuration is **not** pushed into any module-level globals -
    callers should use :func:`psd_method_from_workspace` to build a
    :class:`PsdMethod` and assign it to each series via
    ``series.psd_method = …``.

    Returns
    -------
    dict
        The full nested workspace with all chapters.
    """
    workspace = copy.deepcopy(_DEFAULT_WORKSPACE)

    if json_file is None:
        json_file = user_documents_path() / "DefaultWorkSpace.json"

    specthr_dir = user_documents_path() / "spectHR"
    if not specthr_dir.exists():
        os.makedirs(specthr_dir)

    if os.path.exists(json_file):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            workspace = _deep_merge(workspace, loaded)
        except Exception as e:
            logger.warning(f"Could not load workspace file: {e}")
    else:
        _ensure_dirs(workspace)
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(workspace, f, indent=4, ensure_ascii=False)

    _migrate_respiration_band_to_profiles(workspace)
    _migrate_window_keys(workspace)
    _ensure_dirs(workspace)
    return workspace


def _migrate_respiration_band_to_profiles(workspace: dict) -> None:
    """One-time migration of an earlier flag location.

    An interim version of the editor stored the profile-adaptive flag
    *per band* under ``FrequencyAnalysis.bands.<name>.respiration_band``.
    That location was wrong: the flag is consulted only by the profile
    compute, so it conceptually belongs on the Profiles section.

    This function sweeps every band entry, accumulates any band where
    the legacy flag is True into ``Profiles.adaptive_bands``, and
    strips the legacy key from the band dict in place. Bands that
    never had the legacy flag set are left untouched. No-op on
    workspaces that never went through the interim version.

    Logged at INFO level so a user who notices their old JSON has
    been silently rewritten can tell what happened.
    """
    fa_bands = (workspace.get("FrequencyAnalysis", {}) or {}).get("bands", {})
    if not isinstance(fa_bands, dict):
        return
    profiles = workspace.setdefault("Profiles", {})
    adaptive = list(profiles.get("adaptive_bands", []) or [])
    migrated: list[str] = []
    for name, spec in fa_bands.items():
        if not isinstance(spec, dict) or "respiration_band" not in spec:
            continue
        was_adaptive = bool(spec.pop("respiration_band"))
        if was_adaptive and name not in adaptive:
            adaptive.append(name)
            migrated.append(name)
    if migrated:
        profiles["adaptive_bands"] = adaptive
        logger.info(
            "Migrated respiration_band flag from FrequencyAnalysis.bands "
            f"to Profiles.adaptive_bands: {migrated}"
        )

    # Second pass: if adaptive_bands is still a list (old format from the
    # first iteration of the feature), convert it to the new dict format
    # with default half-widths, keeping only the first entry - adaptive
    # tracking is now a single-band setting.
    adaptive_val = profiles.get("adaptive_bands")
    if isinstance(adaptive_val, list):
        first = adaptive_val[:1]   # keep at most one band
        profiles["adaptive_bands"] = {
            name: {
                "lower half-width (Hz)": 0.04,
                "upper half-width (Hz)": 0.04,
            }
            for name in first
        }
        if adaptive_val:
            logger.info(
                "Migrated Profiles.adaptive_bands from list to dict format "
                f"(single-band): {first}"
            )
    # Third pass: if the dict somehow has more than one entry (saved by an
    # interim multi-select version), collapse to the first entry.
    elif isinstance(adaptive_val, dict) and len(adaptive_val) > 1:
        first_key = next(iter(adaptive_val))
        profiles["adaptive_bands"] = {first_key: adaptive_val[first_key]}
        logger.info(
            "Collapsed multi-entry Profiles.adaptive_bands to single band: "
            f"{first_key}"
        )


def _migrate_window_keys(workspace: dict) -> None:
    """Rename legacy ``window_s`` / ``step_s`` profile keys.

    An earlier version of ``_DEFAULT_WORKSPACE`` stored the sliding-window
    parameters as ``window_s`` and ``step_s``. The canonical names are now
    ``"window (sec)"`` and ``"step (sec)"`` - the pre-formatted spelling
    that passes through ``_label()`` unchanged and appears cleanly in the
    Edit-Parameters dialog.

    This migration runs on every ``LoadWorkspace`` call. It is idempotent:
    if the new keys already exist they are left untouched (the old values
    are still dropped so the dialog doesn't show duplicates).
    """
    profiles = workspace.get("Profiles")
    if not isinstance(profiles, dict):
        return
    renamed: list[str] = []
    for old, new in (("window_s", "window (sec)"), ("step_s", "step (sec)")):
        if old not in profiles:
            continue
        if new not in profiles:
            profiles[new] = profiles[old]
            renamed.append(f"{old} → {new!r}")
        del profiles[old]
    if renamed:
        logger.info(
            "Migrated Profiles window/step keys: %s", ", ".join(renamed)
        )


def SaveWorkspace(workspace: dict, json_file) -> None:
    """Save the full workspace dict (all chapters) to a JSON file."""
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(workspace, f, indent=4, ensure_ascii=False)


def _ensure_dirs(workspace: dict) -> None:
    """Create CacheDirectory and OutputDirectory if they do not exist."""
    dirs = workspace.get("Directories", {})
    for key in ("CacheDirectory", "OutputDirectory"):
        path = dirs.get(key)
        if path and not os.path.exists(path):
            os.makedirs(path)


# ---------------------------------------------------------------------------
# Workspace → PsdMethod translation
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
    ``Profiles.adaptive_bands``, a dict that maps band name →
    ``{"lower half-width (Hz)": float, "upper half-width (Hz)": float}``.
    Only bands listed there get ``respiration_band=True``; the others
    keep static edges. This separation matches the user-facing layout
    (adaptive settings live on the Profile Settings tab, not mixed into
    the PSD band definitions) and mirrors CARSPAN's behaviour where
    ``RunProfileSommation`` is the only consumer of
    ``TAnaBand.RespirationBand``.

    Parameters
    ----------
    bands_dict
        ``workspace["FrequencyAnalysis"]["bands"]``.
    adaptive_bands
        ``workspace["Profiles"]["adaptive_bands"]`` - a dict of
        ``{band_name: {"lower half-width (Hz)": float,
                       "upper half-width (Hz)": float}}``.
        ``None`` or ``{}`` ⇒ every band is static.
    """
    adaptive = adaptive_bands or {}
    return {
        name: BandSpec(
            low=float(spec["low"]),
            high=float(spec["high"]),
            respiration_band=(name in adaptive),
            resp_low=float(
                adaptive[name].get("lower half-width (Hz)", 0.04)
            ) if name in adaptive else 0.04,
            resp_high=float(
                adaptive[name].get("upper half-width (Hz)", 0.04)
            ) if name in adaptive else 0.04,
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
    """Build a :class:`PsdMethod` from a workspace dict.

    The UI calls this once after :func:`LoadWorkspace` and again after
    every Edit-Parameters save, then assigns the result to every
    series instance via ``series.psd_method = method``.
    """
    fa = workspace.get("FrequencyAnalysis", {}) or {}

    # The adaptive-bands dict lives on the Profiles tab (see the
    # ``adaptive_bands`` comment in ``_DEFAULT_WORKSPACE``). It is
    # propagated down to :class:`BandSpec` here so the compute layer
    # (``band_power_profile``) sees a unified band table - each adaptive
    # band carries its own resp_low/resp_high half-widths - without
    # having to reach into the workspace dict itself.
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
    # CARSPAN-strict uses the arithmetic-mean-of-rate convention; every
    # other algorithm uses the simpler T/N harmonic mean.
    mean_convention = "arithmetic" if algorithm == "carspan_strict" else "harmonic"

    return PsdMethod(
        algorithm=algorithm,
        bands=bands,
        alpha_ci=float(fa.get("confidence_interval_alpha", 0.05)),
        mean_convention=mean_convention,
        welch=welch_opts,
        lombscargle=ls_opts,
        carspan=carspan_opts,
    )


def PopulateTree(treewidget, workspace: dict) -> None:
    """Populate a QTreeWidget with files from workspace DataDirectory."""
    treewidget.clear()
    data_dir = workspace["Directories"]["DataDirectory"]
    categories = {
        "XDF Files": "*.xdf",
        "CARSPAN EVT Files": "*.evt",
        "RR Text Files": "*.txt",
    }
    treewidget.setHeaderLabels(["WorkSpace Data"])
    for label, pattern in categories.items():
        parent = QTreeWidgetItem([label])
        extension = pattern.split("*")[-1].lower()
        files = sorted(
            [f for f in os.listdir(data_dir) if f.lower().endswith(extension)]
        )
        for fname in files:
            if fname.lower() == "requirements.txt":
                continue
            item = QTreeWidgetItem(parent, [fname])
            item.setData(
                0,
                Qt.UserRole,
                {
                    "type": "dataset",
                    "filename": fname,
                    "bands_expanded": False,
                },
            )
        treewidget.addTopLevelItem(parent)
    treewidget.expandAll()

