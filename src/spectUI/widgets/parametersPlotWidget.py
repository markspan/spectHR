# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Parameters table widget and export.

**Exports two files per recording:**

``{basename}.csv``
    One row per active epoch.  Every column is a plain scalar — ready to
    open directly in JASP, SPSS, R, or any spreadsheet.  Contains:

    * Time-domain HRV metrics (count, mean, RMSSD, SDNN, …).
    * Poincaré metrics (SD1, SD2, ellipse_area, …).
    * Integrated band powers from the PSD (``{band}_power``, mMI² by
      default).
    * Spectral-profile summary statistics per band
      (``{band}_prof_mean/std/min/max/t_max``).
    * Transfer-function band summaries per band
      (``{band}_tf_modulus``, ``_tf_phase_w``, ``_tf_phase_u``,
      ``_tf_coherence``, ``_tf_n_points``, ``_tf_n_coherent``);
      written only when the recording has a respiration channel.
    * Settings metadata (``prof_window_s``, ``tf_smooth``, …).

``{basename}.h5``
    HDF5 file with one group per active epoch.  Inside each epoch group
    the full array data lives in four sub-groups:

    ``/psd/``        — frequency axis, power spectrum, per-band raw slices.
    ``/profile/``    — per-window band-power time series, breathing-frequency
                       overlay.
    ``/transfer/``   — full Bode spectrum (modulus, phase, coherence) and
                       per-band raw slices; present only when the recording
                       has a respiration channel.
    ``/transfer_profile/``
                     — sliding-window transfer-function time series per band;
                       present only when the recording has a respiration
                       channel.
    ``/respiration/`` — per-breath RSA and RSA0 arrays (ms), breath midpoint
                       timestamps, and metadata (lag_s, n_breaths, n_valid);
                       present only when a respiration channel with detected
                       INH/EXH phases is available.

    Scalar summaries are stored as HDF5 attributes on the relevant group
    so they are visible without loading any dataset.  All arrays are
    native ``float64`` (or ``int32`` for count columns).

Why two files?
    JASP and SPSS understand only flat tables — one row per observation,
    every cell a plain number.  Variable-length arrays (spectra, window
    time series) have no representation in either tool.  The CSV covers
    everything those tools need.  R and Python users who want the full
    spectral data load the HDF5 file with ``hdf5r::h5file()`` or
    ``h5py.File()``.
"""
from __future__ import annotations

import csv
import datetime
import textwrap
from pathlib import Path

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spectHR.Tools.Logger import logger
from spectHR.analysis.registry import get_metrics
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.analysis.profile import compute_band_power_profile
from spectHR.analysis.transfer import resolve_transfer_input
from spectUI.common import show_export_summary
from spectUI.workSpace import (
    display_bands_from_workspace,
    get_export_dir,
    profile_settings_from_workspace,
    psd_method_from_workspace,
    resolved_profile_bands,
    transfer_settings_from_workspace,
)

# Display order for HRV metrics in the parameters table and CSV export.
# Columns not listed here are appended alphabetically after these.
METRIC_ORDER = [
    "count",
    "mean",
    "stationarity",
    "median",
    "min",
    "max",
    "rmssd",
    "sdnn",
    "sdsd",
    "sd1",
    "sd2",
    "sd_ratio",
    "ellipse_area",
    "fullrange_power",
    "vlf_power",
    "lf_power",
    "hf_power",
    "lf_hf_ratio",
    # Beat-by-beat blood-pressure parameters (CARSPAN).
    "bp_sbp",
    "bp_dbp",
    "bp_pp",
    "bp_map",
    # Beat-by-beat respiratory-volume parameters (CARSPAN).
    "resp_mvo",
    "resp_svo",
    # Grossman (1990) peak-to-valley RSA.
    "rsa",
    "rsa0",
]


# ---------------------------------------------------------------------------
# Column help text (header tooltips)
# ---------------------------------------------------------------------------
#
# Tooltips shown when hovering a column header.  Time-domain HRV metrics fall
# back automatically to their ``@epoch_metric`` docstring (see
# ``_tooltip_for_column``); the entries below cover the identifier columns,
# the beat-by-beat BP/RESP parameters and the export-only settings columns.
# Frequency / profile / transfer columns are described by pattern below.

_COLUMN_HELP_STATIC: dict[str, str] = {
    "Subject": "Recording identifier (file basename).",
    "epoch":   "Epoch label.",

    # Beat-by-beat blood pressure (CARSPAN, averaged over the epoch).
    "bp_sbp": "Systolic blood pressure: per-beat maximum of the BP waveform "
              "between two R-peaks, averaged over the epoch "
              "(CARSPAN CalcDataColBPSYS).",
    "bp_dbp": "Diastolic blood pressure: per-beat minimum of the BP waveform "
              "just before the systolic peak, averaged over the epoch "
              "(CARSPAN CalcDataColBPDIA).",
    "bp_pp":  "Pulse pressure: per-beat systolic minus diastolic, averaged "
              "over the epoch (CARSPAN CalcDataColBPPUL).",
    "bp_map": "Mean arterial pressure: integral mean of the BP waveform "
              "between two successive diastolic minima, averaged over the "
              "epoch. The true waveform mean, not (SBP + 2·DBP)/3 "
              "(CARSPAN CalcDataColBPMPR).",

    # Beat-by-beat respiration (CARSPAN, averaged over the epoch).
    "resp_mvo": "Mean respiratory volume: mean of the respiration signal over "
                "each cardiac interval [R_i, R_{i+1}], averaged over the epoch "
                "(CARSPAN CalcDataColRESMVO).",
    "resp_svo": "Sample respiratory volume: mean of the respiration signal "
                "over a short window of samples ending at each R-peak, "
                "averaged over the epoch (CARSPAN CalcDataColRESSVO).",

    "lf_hf_ratio": "Ratio of LF to HF band power (sympatho-vagal balance "
                   "indicator).",

    # Spectral-profile settings (export metadata).
    "prof_method":          "PSD method used for the band-power profile.",
    "prof_unit":            "Unit of the band-power profile values.",
    "prof_window_s":        "Sliding-window length (s) of the band-power profile.",
    "prof_step_s":          "Sliding-window step (s) of the band-power profile.",
    "prof_n_windows":       "Number of profile windows in the epoch.",
    "prof_adaptive_band":   "Name of the adaptive (breathing-tracking) band.",
    "prof_adaptive_source": "Source signal driving the adaptive band centre.",

    # Transfer-function settings (export metadata).
    "tf_method":         "Transfer-function estimation method.",
    "tf_freq_resolution":"Frequency resolution (Hz) of the transfer function.",
    "tf_smooth":         "Whether spectral smoothing was applied (1 = yes).",
    "tf_min_coherence":  "Minimum coherence for a frequency bin to count as "
                         "coherent.",
    "tf_f_max":          "Upper frequency bound (Hz) of the transfer analysis.",
}

# Pattern help for ``{band}_prof_{stat}`` columns.
_PROFILE_STAT_HELP: dict[str, str] = {
    "mean":  "Mean of the {band} band-power profile over the epoch.",
    "std":   "Standard deviation of the {band} band-power profile over the epoch.",
    "min":   "Minimum of the {band} band-power profile over the epoch.",
    "max":   "Maximum of the {band} band-power profile over the epoch.",
    "t_max": "Time (s, relative to epoch start) at which the {band} band-power "
             "profile peaks.",
}

# Pattern help for ``{band}_tf_{field}`` columns.
_TRANSFER_FIELD_HELP: dict[str, str] = {
    "modulus":   "Transfer-function modulus (gain) in the {band} band "
                 "(respiration → IBI).",
    "phase_w":   "Transfer-function phase (wrapped, rad) in the {band} band.",
    "phase_u":   "Transfer-function phase (unwrapped, rad) in the {band} band.",
    "coherence": "Coherence-weighted mean coherence in the {band} band.",
    "n_points":  "Number of frequency bins in the {band} band.",
    "n_coherent":"Number of coherent frequency bins (above the coherence "
                 "threshold) in the {band} band.",
}


def _doc_summary(doc: str | None) -> str:
    """Collapse a docstring's first paragraph into a single tooltip line."""
    if not doc:
        return ""
    text = textwrap.dedent(doc).strip()
    first = text.split("\n\n", 1)[0]
    return " ".join(first.split())


# ---------------------------------------------------------------------------
# Helper: write a float64 array to an h5py group, handling empty arrays
# ---------------------------------------------------------------------------

def _h5write(grp, name: str, arr) -> None:
    """Create dataset *name* in *grp* from array *arr*.

    Empty arrays are written with shape (0,) so the dataset always
    exists and downstream code can check ``.shape[0] == 0`` rather than
    catching ``KeyError``.
    """
    a = np.asarray(arr, dtype=np.float64).ravel()
    grp.create_dataset(name, data=a, compression="gzip", compression_opts=4)


def _h5str(grp, key: str, value: str) -> None:
    """Store *value* as a UTF-8 string attribute on *grp*."""
    grp.attrs[key] = str(value)


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------


class ParametersPlotWidget(QWidget):
    """HRV parameters table with scalar-CSV + HDF5 export."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowTitle("Parameters Plot")

        self.table_widget = QTableWidget()
        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)
        self.main_layout.addWidget(self.table_widget)

        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_data)
        button_layout.addWidget(self.save_button)
        self.main_layout.addLayout(button_layout)

        self.headers: list[str] = []
        self.data: np.ndarray | None = None
        self.csvfile: Path | None = None
        self.h5file:  Path | None = None
        self.workspace: dict | None = None

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def display_parameters(self, dataset, workspace):
        self.dataset   = dataset
        self.workspace = workspace
        self.setFocus()

        output_dir    = get_export_dir(workspace, context="Parameters")
        self.csvfile  = output_dir / f"{dataset.basename}.csv"
        self.h5file   = output_dir / f"{dataset.basename}.h5"

        psd_method = psd_method_from_workspace(workspace)
        rsa_lag_s = ((workspace or {}).get("RespirationAnalysis") or {}).get("rsa_lag_s", 1.0)
        labels, cols, values = self.dataset.epoched_parameters_table(
            psd_method=psd_method, rsa_lag_s=float(rsa_lag_s)
        )

        # Re-order columns: known metrics first, then extras alphabetically.
        ordered = [c for c in METRIC_ORDER if c in cols]
        ordered += sorted(c for c in cols if c not in ordered)
        if ordered != list(cols):
            col_idx   = {c: i for i, c in enumerate(cols)}
            new_order = [col_idx[c] for c in ordered]
            values    = values[:, new_order] if values.size else values
            cols      = ordered

        subject     = getattr(dataset, "basename", None)
        n_rows      = int(labels.shape[0])
        n_metrics   = int(values.shape[1]) if values.size else 0

        self.headers = ["Subject", "epoch"] + list(cols)
        self.data    = np.empty((n_rows, 2 + n_metrics), dtype=object)
        self.data[:, 0] = subject
        self.data[:, 1] = labels
        if n_metrics:
            self.data[:, 2:] = values

        self.table_widget.clear()
        self.table_widget.setRowCount(n_rows)
        self.table_widget.setColumnCount(len(self.headers))
        self.table_widget.setHorizontalHeaderLabels(self.headers)

        # Header hover help: attach a tooltip to every column header.
        for col, name in enumerate(self.headers):
            header_item = self.table_widget.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setToolTip(self._tooltip_for_column(name))

        for i in range(n_rows):
            for j, v in enumerate(self.data[i]):
                if isinstance(v, (float, np.floating)) and np.isnan(v):
                    txt = ""
                elif isinstance(v, (int, np.integer)):
                    txt = str(int(v))
                elif isinstance(v, (float, np.floating)):
                    txt = f"{float(v):.5f}"
                elif isinstance(v, str):
                    txt = v
                else:
                    txt = "" if v is None else str(v)
                self.table_widget.setItem(i, j, QTableWidgetItem(txt))

        self.table_widget.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Save entry point
    # ------------------------------------------------------------------

    def save_data(self):
        if self.csvfile is None or self.data is None:
            return

        # Single computation pass: returns per-epoch dicts with both
        # scalar summaries (for the CSV) and full arrays (for HDF5).
        epoch_data = self._collect_epoch_data()

        # Inject the epoched_parameters_table scalars (RMSSD, SDNN, band
        # powers, Poincaré metrics, BP/RESP parameters, and any future
        # @epoch_metric additions) into every epoch's "scalars" dict so they
        # travel to the HDF5 file as well as the CSV.  self.data rows skip
        # "Subject" (col 0) and "epoch" (col 1); the remaining columns come
        # from epoched_parameters_table, which is already complete.
        table_scalars = self._table_scalars_by_epoch()
        for label, ed in epoch_data.items():
            ts = table_scalars.get(label, {})
            # table scalars first so spectral scalars with the same name
            # (shouldn't happen, but defensive) take precedence.
            ed["scalars"] = {**ts, **ed["scalars"]}

        # --- scalar CSV (always) ---
        self._write_csv(epoch_data)

        # --- HDF5 (best-effort) ---
        try:
            self._write_hdf5(epoch_data)
        except Exception as exc:          # pragma: no cover
            logger.warning(f"HDF5 export failed: {exc}")

        export_dir    = get_export_dir(self.workspace, context="Parameters")
        files_written = [
            p.name for p in (self.csvfile, self.h5file)
            if p is not None and p.exists()
        ]
        summary = (
            f"Parameters export: wrote {len(files_written)} file(s) "
            f"to {export_dir!s}"
        )
        if files_written:
            summary += "\n  - " + "\n  - ".join(files_written)
        logger.info(summary)
        show_export_summary(self, context="Parameters", summary=summary)

    # ------------------------------------------------------------------
    # Computation pass
    # ------------------------------------------------------------------

    def _collect_epoch_data(self) -> dict[str, dict]:
        """Compute all spectral data for every active epoch.

        Returns a dict mapping epoch label → data dict with keys:

        ``scalars``        Extra scalar columns to append to the CSV row.
        ``psd``            Dict with freqs, power, unit, method, freq_res,
                           bands (dict band → {freqs, power, integrated}).
        ``profile``        Dict with timestamps, t_rel, unit, method, resp_freqs,
                           settings, bands (dict band → {power, mean,std,min,max,t_max}).
        ``transfer``       Dict or ``None`` (no rsp channel).
        ``transfer_profile`` Dict or ``None``.
        """
        if self.workspace is None:
            return {}

        hrv = getattr(self.dataset, "hrv", None)
        if hrv is None:
            return {}

        psd_method   = psd_method_from_workspace(self.workspace)
        prof_cfg     = profile_settings_from_workspace(self.workspace)
        tf_cfg       = transfer_settings_from_workspace(self.workspace)
        emit_bands, adaptive_band_name = resolved_profile_bands(self.workspace)

        # Band edges for transfer (FullRange excluded — meaningless as a
        # 0.02–0.5 Hz single-number summary alongside the rest).
        bands_dict = display_bands_from_workspace(self.workspace) or {}
        tf_band_edges = {
            name: (float(spec["low"]), float(spec["high"]))
            for name, spec in bands_dict.items()
            if name != "FullRange" and "low" in spec and "high" in spec
        }

        # Transfer input series (respiration or blood pressure) — shared
        # across all epochs; the source is chosen in the workspace settings.
        tf_input_signal = str(tf_cfg["input_signal"])
        rsp_ts, _ = resolve_transfer_input(self.dataset, tf_input_signal)

        active_band = getattr(self.dataset, "active_band", None)
        rsp_series  = getattr(self.dataset, "rsp_map", {}).get(active_band)
        rsa_lag_s   = float(
            ((self.workspace or {}).get("RespirationAnalysis") or {})
            .get("rsa_lag_s", 1.0)
        )

        result: dict[str, dict] = {}

        for label, _ep in self._iter_active_epochs():
            try:
                view = hrv[label]
            except Exception:
                continue

            epoch: dict = {"scalars": {}, "psd": None, "profile": None,
                           "transfer": None, "transfer_profile": None,
                           "respiration": None}

            # ---- PSD -------------------------------------------------
            try:
                psd_res  = PSDEngine(view).compute(psd_method, with_ci=False)
                freqs    = np.asarray(psd_res.freqs)
                power    = np.asarray(psd_res.power)
                psd_unit = (psd_res.unit or "").replace("/Hz", "")
                band_psd: dict = {}
                for bname, bspec in psd_method.bands.items():
                    mask = (freqs >= bspec.low) & (freqs <= bspec.high)
                    band_psd[bname] = {
                        "freqs":      freqs[mask],
                        "power":      power[mask],
                        "integrated": float(band_power_rectangular(
                                          freqs, power, bspec.low, bspec.high)),
                        "low":  bspec.low,
                        "high": bspec.high,
                    }
                epoch["psd"] = {
                    "freqs":    freqs,
                    "power":    power,
                    "unit":     psd_res.unit or "",
                    "psd_unit": psd_unit,
                    "method":   psd_res.method or "",
                    "freq_res": float(freqs[1] - freqs[0]) if freqs.size > 1 else 0.0,
                    "bands":    band_psd,
                }
            except Exception as exc:
                logger.debug("PSD export failed for epoch %r: %s", label, exc)

            # ---- Profile ---------------------------------------------
            try:
                prof_res  = compute_band_power_profile(
                    view,
                    window_s          = prof_cfg["window_s"],
                    step_s            = prof_cfg["step_s"],
                    psd_method        = psd_method,
                    adaptive_source   = prof_cfg["adaptive_source"],
                    smooth_breath_freq= prof_cfg["smooth_breath_freq"],
                )
                ts = np.asarray(prof_res.timestamps)
                t_rel = (
                    ts - (ts[0] - prof_cfg["window_s"] / 2.0)
                    if ts.size else ts
                )
                band_prof: dict = {}
                names_in = list(prof_res.band_names)
                for bname in (emit_bands or names_in):
                    if bname not in names_in:
                        continue
                    bp = prof_res.band_power[names_in.index(bname)]
                    finite = bp[np.isfinite(bp)]
                    stats: dict = {}
                    if finite.size:
                        stats["mean"]  = float(np.mean(finite))
                        stats["std"]   = float(np.std(finite, ddof=0))
                        stats["min"]   = float(np.min(finite))
                        stats["max"]   = float(np.max(finite))
                        fi = np.where(np.isfinite(bp))[0]
                        stats["t_max"] = float(t_rel[fi[int(np.argmax(finite))]])
                    band_prof[bname] = {"power": bp, **stats}

                    # Scalar summary → CSV
                    for k, v in stats.items():
                        epoch["scalars"][f"{bname}_prof_{k}"] = v

                epoch["scalars"]["prof_method"]   = prof_res.method or ""
                epoch["scalars"]["prof_unit"]     = prof_res.unit   or ""
                epoch["scalars"]["prof_window_s"] = prof_cfg["window_s"]
                epoch["scalars"]["prof_step_s"]   = prof_cfg["step_s"]
                epoch["scalars"]["prof_n_windows"]= int(ts.size)
                if adaptive_band_name:
                    epoch["scalars"]["prof_adaptive_band"]   = adaptive_band_name
                    epoch["scalars"]["prof_adaptive_source"] = prof_cfg["adaptive_source"]

                resp_freqs = (
                    np.asarray(prof_res.resp_freqs, dtype=np.float64).ravel()
                    if prof_res.resp_freqs is not None else None
                )
                epoch["profile"] = {
                    "timestamps": ts,
                    "t_rel":      t_rel,
                    "unit":       prof_res.unit or "",
                    "method":     prof_res.method or "",
                    "window_s":   prof_cfg["window_s"],
                    "step_s":     prof_cfg["step_s"],
                    "adaptive_band":   adaptive_band_name or "",
                    "adaptive_source": prof_cfg["adaptive_source"],
                    "resp_freqs": resp_freqs,
                    "bands":      band_prof,
                }
            except Exception as exc:
                logger.debug("Profile export failed for epoch %r: %s", label, exc)

            # ---- Transfer --------------------------------------------
            if rsp_ts is not None and tf_band_edges:
                try:
                    from spectHR.analysis.transfer import compute_transfer
                    tf_res = compute_transfer(
                        view, rsp_ts,
                        input_signal   = tf_input_signal,
                        bands          = tf_band_edges,
                        min_coherence  = float(tf_cfg["min_coherence"]),
                        smooth         = bool(tf_cfg["smooth"]),
                        f_max          = float(tf_cfg["f_max"]),
                    )
                    tf_freqs   = np.asarray(tf_res.freqs)
                    tf_mod     = np.asarray(tf_res.modulus)
                    tf_pw      = np.asarray(tf_res.phase_wrapped)
                    tf_pu      = np.asarray(tf_res.phase_unwrapped)
                    tf_coh     = np.asarray(tf_res.coherence)
                    tf_freq_res= float(tf_res.freq_resolution)

                    band_tf: dict = {}
                    for bname, (blow, bhigh) in tf_band_edges.items():
                        mask = (tf_freqs >= blow) & (tf_freqs <= bhigh)
                        bt   = (tf_res.band_results or {}).get(bname)
                        band_tf[bname] = {
                            "freqs":              tf_freqs[mask],
                            "modulus_raw":        tf_mod[mask],
                            "phase_wrapped_raw":  tf_pw[mask],
                            "phase_unwrapped_raw":tf_pu[mask],
                            "coherence_raw":      tf_coh[mask],
                            "low":   blow,
                            "high":  bhigh,
                            # band-summary scalars (from BandTransfer)
                            "modulus":            float(bt.modulus)            if bt else np.nan,
                            "phase_wrapped":      float(bt.phase)              if bt else np.nan,
                            "phase_unwrapped":    float(bt.phase_unwrapped)    if bt else np.nan,
                            "weighted_coherence": float(bt.weighted_coherence) if bt else np.nan,
                            "n_points":           int(bt.n_points)             if bt else 0,
                            "n_coherent":         int(bt.n_coherent)           if bt else 0,
                        }
                        # Scalar summary → CSV
                        if bt:
                            epoch["scalars"][f"{bname}_tf_modulus"]   = float(bt.modulus)
                            epoch["scalars"][f"{bname}_tf_phase_w"]   = float(bt.phase)
                            epoch["scalars"][f"{bname}_tf_phase_u"]   = float(bt.phase_unwrapped)
                            epoch["scalars"][f"{bname}_tf_coherence"] = float(bt.weighted_coherence)
                            epoch["scalars"][f"{bname}_tf_n_points"]  = int(bt.n_points)
                            epoch["scalars"][f"{bname}_tf_n_coherent"]= int(bt.n_coherent)

                    epoch["scalars"]["tf_method"]        = tf_res.method or ""
                    epoch["scalars"]["tf_freq_resolution"]= tf_freq_res
                    epoch["scalars"]["tf_smooth"]        = int(tf_cfg["smooth"])
                    epoch["scalars"]["tf_min_coherence"] = float(tf_cfg["min_coherence"])
                    epoch["scalars"]["tf_f_max"]         = float(tf_cfg["f_max"])

                    epoch["transfer"] = {
                        "freqs":          tf_freqs,
                        "modulus":        tf_mod,
                        "phase_wrapped":  tf_pw,
                        "phase_unwrapped":tf_pu,
                        "coherence":      tf_coh,
                        "method":         tf_res.method or "",
                        "freq_resolution":tf_freq_res,
                        "smooth":         bool(tf_cfg["smooth"]),
                        "min_coherence":  float(tf_cfg["min_coherence"]),
                        "f_max":          float(tf_cfg["f_max"]),
                        "bands":          band_tf,
                    }
                except Exception as exc:
                    logger.debug("Transfer export failed for epoch %r: %s", label, exc)

            # ---- Transfer profile ------------------------------------
            if rsp_ts is not None and tf_band_edges:
                try:
                    from spectHR.analysis.transfer import compute_transfer_profile
                    tfp_res = compute_transfer_profile(
                        view, rsp_ts,
                        input_signal  = tf_input_signal,
                        bands         = tf_band_edges,
                        window_s      = float(tf_cfg["window_s"]),
                        step_s        = float(tf_cfg["step_s"]),
                        min_coherence = float(tf_cfg["min_coherence"]),
                        f_max         = float(tf_cfg["f_max"]),
                        smooth        = bool(tf_cfg["smooth"]),
                    )
                    band_tfp: dict = {}
                    for b, bname in enumerate(tfp_res.band_names):
                        band_tfp[bname] = {
                            "modulus":            np.asarray(tfp_res.modulus[b]),
                            "phase":              np.asarray(tfp_res.phase[b]),
                            "phase_unwrapped":    np.asarray(tfp_res.phase_unwrapped[b]),
                            "weighted_coherence": np.asarray(tfp_res.weighted_coherence[b]),
                            "n_coherent":         np.asarray(tfp_res.n_coherent[b], dtype=np.int32),
                        }
                    epoch["transfer_profile"] = {
                        "timestamps": np.asarray(tfp_res.timestamps),
                        "method":     tfp_res.method or "",
                        "window_s":   float(tf_cfg["window_s"]),
                        "step_s":     float(tf_cfg["step_s"]),
                        "smooth":     bool(tf_cfg["smooth"]),
                        "min_coherence": float(tf_cfg["min_coherence"]),
                        "f_max":      float(tf_cfg["f_max"]),
                        "bands":      band_tfp,
                    }
                except Exception as exc:
                    logger.debug(
                        "Transfer-profile export failed for epoch %r: %s", label, exc
                    )

            # ---- RSA per-breath ------------------------------------
            if rsp_series is not None:
                try:
                    from spectHR.analysis.bp_metrics import grossman_rsa_per_breath
                    rsp_phases = rsp_series.view(float(_ep.start), float(_ep.end))
                    if len(rsp_phases) >= 2:
                        rsa_raw = grossman_rsa_per_breath(
                            np.asarray(view.times,  dtype=float),
                            np.asarray(view.labels, dtype=object),
                            rsp_phases,
                            lag_s=rsa_lag_s,
                        )
                        if rsa_raw.size > 0:
                            p_starts = np.asarray(rsp_phases.starts, dtype=float)
                            p_ends   = np.asarray(rsp_phases.ends,   dtype=float)
                            p_labels = np.asarray(rsp_phases.labels, dtype=object)
                            x_pts, pair_idx = [], 0
                            for i in range(len(p_starts) - 1):
                                if p_labels[i] == "INH" and p_labels[i + 1] == "EXH":
                                    if pair_idx < rsa_raw.size:
                                        x_pts.append(
                                            (p_starts[i] + p_ends[i + 1]) / 2.0
                                        )
                                    pair_idx += 1
                            epoch["respiration"] = {
                                "rsa":          rsa_raw,
                                "rsa0":         np.where(
                                                    np.isfinite(rsa_raw),
                                                    rsa_raw, 0.0),
                                "breath_times": np.array(x_pts, dtype=float),
                                "lag_s":        rsa_lag_s,
                                "n_breaths":    int(rsa_raw.size),
                                "n_valid":      int(
                                                    np.sum(
                                                        np.isfinite(rsa_raw)
                                                        & (rsa_raw >= 0)
                                                    )
                                                ),
                            }
                except Exception as exc:
                    logger.debug("RSA export failed for epoch %r: %s", label, exc)

            result[label] = epoch

        return result

    # ------------------------------------------------------------------
    # CSV writer (scalars only)
    # ------------------------------------------------------------------

    def _write_csv(self, epoch_data: dict[str, dict]) -> None:
        """Write the scalar-only CSV, merging epoched_parameters_table data with
        spectral summary scalars collected in *epoch_data*."""
        if self.csvfile is None or self.data is None:
            return

        # Collect the union of extra scalar column names in epoch order.
        extra_cols: list[str] = []
        for ed in epoch_data.values():
            for k in ed.get("scalars", {}):
                if k not in extra_cols:
                    extra_cols.append(k)

        with self.csvfile.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.headers + extra_cols)
            for row in self.data:
                epoch_label = str(row[1])
                scalars     = epoch_data.get(epoch_label, {}).get("scalars", {})

                out: list[str] = []
                for v in row:
                    out.append(self._format_cell(v))
                for col in extra_cols:
                    out.append(self._format_cell(scalars.get(col)))

                w.writerow(out)

    # ------------------------------------------------------------------
    # HDF5 writer (all arrays + scalars as attributes)
    # ------------------------------------------------------------------

    def _write_hdf5(self, epoch_data: dict[str, dict]) -> None:
        """Write ``{basename}.h5`` with the full hierarchical structure.

        Layout::

            /{epoch}/
              attrs: subject
              /psd/
                attrs: method, unit, psd_unit, freq_resolution
                datasets: freqs, power
                /{band}/
                  attrs: low, high, integrated_power, unit
                  datasets: freqs, power
              /profile/
                attrs: method, unit, window_s, step_s,
                       adaptive_band, adaptive_source, n_windows
                datasets: timestamps, t_rel [, resp_freqs]
                /{band}/
                  attrs: mean, std, min, max, t_max
                  datasets: power
              /transfer/          (only when rsp channel present)
                attrs: method, freq_resolution, smooth, min_coherence, f_max
                datasets: freqs, modulus, phase_wrapped, phase_unwrapped,
                          coherence
                /{band}/
                  attrs: low, high, modulus, phase_wrapped, phase_unwrapped,
                         weighted_coherence, n_points, n_coherent
                  datasets: freqs, modulus_raw, phase_wrapped_raw,
                            phase_unwrapped_raw, coherence_raw
              /transfer_profile/  (only when rsp channel present)
                attrs: method, window_s, step_s, smooth, min_coherence,
                       f_max, n_windows
                datasets: timestamps
                /{band}/
                  datasets: modulus, phase, phase_unwrapped,
                            weighted_coherence, n_coherent
              /respiration/       (only when rsp phases detected)
                attrs: lag_s, n_breaths, n_valid
                datasets: rsa [N_breaths], rsa0 [N_breaths],
                          breath_times [N_breaths]
        """
        if self.h5file is None:
            return

        import h5py

        subject = getattr(self.dataset, "basename", "")

        with h5py.File(self.h5file, "w") as hf:
            # Root metadata
            hf.attrs["subject"]     = subject
            hf.attrs["exported_at"] = datetime.datetime.now().isoformat(
                                          timespec="seconds")
            hf.attrs["specthr_export_version"] = "2"

            for label, ed in epoch_data.items():
                eg = hf.require_group(label)
                eg.attrs["subject"] = subject

                # ---- All scalars as epoch-group attributes ----------
                # Covers time-domain metrics (RMSSD, SDNN, …), Poincaré
                # metrics (SD1, SD2, …), integrated band powers, profile
                # summaries, transfer summaries, and any future
                # @epoch_metric additions — automatically, with no extra
                # code needed here.
                for col, val in ed.get("scalars", {}).items():
                    try:
                        eg.attrs[col] = val
                    except Exception:
                        pass    # skip if h5py can't serialise the value

                # ---- PSD ----------------------------------------
                psd = ed.get("psd")
                if psd:
                    pg = eg.require_group("psd")
                    _h5str(pg, "method",         psd["method"])
                    _h5str(pg, "unit",            psd["unit"])
                    _h5str(pg, "psd_unit",        psd["psd_unit"])
                    pg.attrs["freq_resolution"]  = psd["freq_res"]
                    _h5write(pg, "freqs", psd["freqs"])
                    _h5write(pg, "power", psd["power"])
                    for bname, bd in psd["bands"].items():
                        bg = pg.require_group(bname)
                        bg.attrs["low"]              = bd["low"]
                        bg.attrs["high"]             = bd["high"]
                        bg.attrs["integrated_power"] = bd["integrated"]
                        _h5str(bg, "unit", psd["psd_unit"])
                        _h5write(bg, "freqs", bd["freqs"])
                        _h5write(bg, "power", bd["power"])

                # ---- Profile ------------------------------------
                prof = ed.get("profile")
                if prof:
                    prg = eg.require_group("profile")
                    _h5str(prg, "method",         prof["method"])
                    _h5str(prg, "unit",            prof["unit"])
                    prg.attrs["window_s"]           = prof["window_s"]
                    prg.attrs["step_s"]             = prof["step_s"]
                    prg.attrs["n_windows"]          = int(prof["timestamps"].size)
                    _h5str(prg, "adaptive_band",   prof["adaptive_band"])
                    _h5str(prg, "adaptive_source", prof["adaptive_source"])
                    _h5write(prg, "timestamps", prof["timestamps"])
                    _h5write(prg, "t_rel",       prof["t_rel"])
                    if prof["resp_freqs"] is not None:
                        _h5write(prg, "resp_freqs", prof["resp_freqs"])
                    for bname, bd in prof["bands"].items():
                        bg = prg.require_group(bname)
                        for stat in ("mean", "std", "min", "max", "t_max"):
                            if stat in bd:
                                bg.attrs[stat] = bd[stat]
                        _h5write(bg, "power", bd["power"])

                # ---- Transfer -----------------------------------
                tf = ed.get("transfer")
                if tf:
                    tfg = eg.require_group("transfer")
                    _h5str(tfg, "method",         tf["method"])
                    tfg.attrs["freq_resolution"] = tf["freq_resolution"]
                    tfg.attrs["smooth"]          = int(tf["smooth"])
                    tfg.attrs["min_coherence"]   = tf["min_coherence"]
                    tfg.attrs["f_max"]           = tf["f_max"]
                    _h5write(tfg, "freqs",           tf["freqs"])
                    _h5write(tfg, "modulus",         tf["modulus"])
                    _h5write(tfg, "phase_wrapped",   tf["phase_wrapped"])
                    _h5write(tfg, "phase_unwrapped", tf["phase_unwrapped"])
                    _h5write(tfg, "coherence",       tf["coherence"])
                    for bname, bd in tf["bands"].items():
                        bg = tfg.require_group(bname)
                        bg.attrs["low"]                = bd["low"]
                        bg.attrs["high"]               = bd["high"]
                        bg.attrs["modulus"]            = bd["modulus"]
                        bg.attrs["phase_wrapped"]      = bd["phase_wrapped"]
                        bg.attrs["phase_unwrapped"]    = bd["phase_unwrapped"]
                        bg.attrs["weighted_coherence"] = bd["weighted_coherence"]
                        bg.attrs["n_points"]           = bd["n_points"]
                        bg.attrs["n_coherent"]         = bd["n_coherent"]
                        _h5write(bg, "freqs",               bd["freqs"])
                        _h5write(bg, "modulus_raw",         bd["modulus_raw"])
                        _h5write(bg, "phase_wrapped_raw",   bd["phase_wrapped_raw"])
                        _h5write(bg, "phase_unwrapped_raw", bd["phase_unwrapped_raw"])
                        _h5write(bg, "coherence_raw",       bd["coherence_raw"])

                # ---- Respiration / RSA per breath ---------------
                rsp_h5 = ed.get("respiration")
                if rsp_h5:
                    rg = eg.require_group("respiration")
                    rg.attrs["lag_s"]     = rsp_h5["lag_s"]
                    rg.attrs["n_breaths"] = rsp_h5["n_breaths"]
                    rg.attrs["n_valid"]   = rsp_h5["n_valid"]
                    _h5write(rg, "rsa",          rsp_h5["rsa"])
                    _h5write(rg, "rsa0",         rsp_h5["rsa0"])
                    _h5write(rg, "breath_times", rsp_h5["breath_times"])

                # ---- Transfer profile ---------------------------
                tfp = ed.get("transfer_profile")
                if tfp:
                    tpg = eg.require_group("transfer_profile")
                    _h5str(tpg, "method",        tfp["method"])
                    tpg.attrs["window_s"]       = tfp["window_s"]
                    tpg.attrs["step_s"]         = tfp["step_s"]
                    tpg.attrs["smooth"]         = int(tfp["smooth"])
                    tpg.attrs["min_coherence"]  = tfp["min_coherence"]
                    tpg.attrs["f_max"]          = tfp["f_max"]
                    tpg.attrs["n_windows"]      = int(tfp["timestamps"].size)
                    _h5write(tpg, "timestamps", tfp["timestamps"])
                    for bname, bd in tfp["bands"].items():
                        bg = tpg.require_group(bname)
                        _h5write(bg, "modulus",             bd["modulus"])
                        _h5write(bg, "phase",               bd["phase"])
                        _h5write(bg, "phase_unwrapped",     bd["phase_unwrapped"])
                        _h5write(bg, "weighted_coherence",  bd["weighted_coherence"])
                        bg.create_dataset("n_coherent",
                                          data=bd["n_coherent"],
                                          compression="gzip")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tooltip_for_column(name: str) -> str:
        """Return hover help text for the column header *name*.

        Resolution order:

        1. An explicit entry in :data:`_COLUMN_HELP_STATIC` (identifier,
           BP/RESP and settings columns).
        2. The docstring of the registered ``@epoch_metric`` of the same name
           (time-domain HRV metrics).
        3. A pattern match for the generated frequency / profile / transfer
           columns (``{band}_power``, ``{band}_prof_{stat}``,
           ``{band}_tf_{field}``).
        4. The column name itself, as a last resort.
        """
        if name in _COLUMN_HELP_STATIC:
            return _COLUMN_HELP_STATIC[name]

        # Registered time-domain HRV metric → its docstring.
        metric = get_metrics().get(name)
        if metric is not None:
            doc = _doc_summary(metric.__doc__)
            if doc:
                return doc

        # Integrated band power: "{band}_power".
        if name.endswith("_power"):
            band = name[: -len("_power")]
            return (
                f"Integrated PSD power in the {band.upper()} band, per epoch."
            )

        # Spectral-profile summary: "{band}_prof_{stat}".
        if "_prof_" in name:
            band, stat = name.split("_prof_", 1)
            tmpl = _PROFILE_STAT_HELP.get(stat)
            if tmpl:
                return tmpl.format(band=band.upper())

        # Transfer-function summary: "{band}_tf_{field}".
        if "_tf_" in name:
            band, field = name.split("_tf_", 1)
            tmpl = _TRANSFER_FIELD_HELP.get(field)
            if tmpl:
                return tmpl.format(band=band.upper())

        return name

    def _table_scalars_by_epoch(self) -> dict[str, dict]:
        """Extract epoched_parameters_table scalars from self.data as a plain dict.

        Returns ``{epoch_label: {col_name: python_scalar}}`` for every
        row in self.data.  Column 0 (Subject) and column 1 (epoch) are
        skipped; every remaining value is coerced to a native Python
        float / int / str so h5py can store it as an HDF5 attribute.

        Any new metric added via ``@epoch_metric`` automatically appears
        here because it flows through ``epoched_parameters_table`` → ``self.data``
        → this method → the HDF5 epoch group attributes.
        """
        if self.data is None:
            return {}
        metric_cols = self.headers[2:]   # skip Subject, epoch
        result: dict[str, dict] = {}
        for row in self.data:
            label = str(row[1])
            scalars: dict[str, object] = {}
            for col, val in zip(metric_cols, row[2:]):
                if isinstance(val, (float, np.floating)):
                    scalars[col] = float(val)   # preserves NaN as float NaN
                elif isinstance(val, (int, np.integer)):
                    scalars[col] = int(val)
                elif val is None:
                    pass                        # skip None — no meaningful attr
                else:
                    scalars[col] = str(val)
            result[label] = scalars
        return result

    def _iter_active_epochs(self):
        """Yield ``(label, epoch)`` for every active epoch in order."""
        for label, epoch in self.dataset.epochs.items():
            if getattr(epoch, "active", False):
                yield label, epoch

    def _resolve_export_dir(self) -> Path:
        return get_export_dir(self.workspace, context="Parameters")

    def get_table_headers(self) -> list[str]:
        headers = []
        for col in range(self.table_widget.columnCount()):
            item = self.table_widget.horizontalHeaderItem(col)
            headers.append(item.text() if item is not None else f"Column {col + 1}")
        return headers

    @staticmethod
    def _format_cell(v) -> str:
        """Render *v* as a CSV cell string."""
        if v is None:
            return ""
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else f"{float(v):.5f}"
        if isinstance(v, (int, np.integer)):
            return str(int(v))
        return str(v)

    @staticmethod
    def _format_list(arr) -> str:
        """Legacy helper kept for external compatibility.
        Renders a 1-D array as a comma-separated string."""
        if arr is None:
            return ""
        a = np.asarray(arr).ravel()
        if a.size == 0:
            return ""
        parts = []
        for v in a:
            fv = float(v)
            parts.append("" if not np.isfinite(fv) else f"{fv:.6g}")
        return ",".join(parts)
