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
            "FullRange": {"low": 0.02, "high": 0.5, "color": "gray", "alpha": 0.35},
            "VLF": {"low": 0.02, "high": 0.06, "color": "blue"},
            "LF": {"low": 0.07, "high": 0.14, "color": "darkgreen"},
            "HF": {"low": 0.15, "high": 0.40, "color": "red"},
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
    # inside one epoch — implemented as the standard PSD pipeline
    # applied to a window that slides along the recording with a fixed
    # step (see CARSPAN manual §3.3.5, Eq. 3.34 / 3.35). The compute
    # algorithm and band definitions are inherited from
    # ``FrequencyAnalysis`` so a profile of `band X` is computed with
    # the same PSD method (Welch / Lomb-Scargle / CARSPAN / strict) and
    # the same edges as the corresponding PSD band — they're two views
    # of the same underlying analysis.
    #
    # ``bands`` lists the band names (matching keys in
    # ``FrequencyAnalysis.bands``) the profile plot should draw. The
    # profile compute may compute all configured bands; this list is a
    # display filter only.
    #
    # ``window_s`` and ``step_s`` are the sliding-window parameters in
    # seconds; ``step_s`` must be strictly smaller than ``window_s``
    # (otherwise there's no overlap → no profile), and the manual
    # recommends ``window_s ≥ 3 · 1/f_l_min`` for reliable estimates.
    "Profiles": {
        "window (sec)": 30.0,
        "step (sec)":   5.0,
        "bands":    ["LF", "HF"],
        # Apply Pascal's 3-point MA along each band's time series before
        # plotting. Same kernel + edge policy as the PSD smoother — plot
        # only; band-power integration is unaffected. Defaults to
        # False because the reference Delphi profile view doesn't apply
        # any time-axis smoother — the plotted line is the raw
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
    # concatenated together. The default ``experiment`` epoch — which
    # the loaders create as a placeholder spanning the entire recording —
    # is skipped when it still covers the whole signal, so turning the
    # flag on without defining task epochs yet is a no-op.
    "RespirationAnalysis": {
        "per_epoch": False,
    },
}


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
    PSD configuration is **not** pushed into any module-level globals —
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

    _ensure_dirs(workspace)
    return workspace


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


def _bands_from_workspace(bands_dict: Dict[str, dict]) -> Dict[str, BandSpec]:
    """Convert the workspace bands subdict to ``Dict[str, BandSpec]``.

    Only the frequency edges go into :class:`BandSpec`. Display
    attributes (``color``, ``alpha``) stay on the raw workspace dict
    and are consumed directly by ``PSDPlotWidget``.
    """
    return {
        name: BandSpec(low=float(spec["low"]), high=float(spec["high"]))
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

    bands = _bands_from_workspace(fa.get("bands", {}))
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
