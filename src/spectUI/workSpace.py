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
    """Convert the workspace bands subdict to ``Dict[str, BandSpec]``."""
    out: Dict[str, BandSpec] = {}
    for name, spec in bands_dict.items():
        out[name] = BandSpec(
            low=float(spec["low"]),
            high=float(spec["high"]),
            color=str(spec.get("color", "gray")),
            alpha=(float(spec["alpha"]) if "alpha" in spec else None),
        )
    return out


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
