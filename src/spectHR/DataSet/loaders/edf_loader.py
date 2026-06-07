# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""EDF / EDF+C loader — primary target is VU-AMS 5fs exports."""
from __future__ import annotations

from pathlib import Path
import numpy as np

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger


# ---------------------------------------------------------------------------
# Low-level EDF / EDF+C binary parser
# ---------------------------------------------------------------------------

def _parse_edf_header(f):
    """Read global + per-signal EDF headers; return a header dict."""
    raw = f.read(256)
    if len(raw) < 256:
        raise IOError("File too short for EDF global header")

    n_header  = int(raw[184:192].decode("ascii").strip())
    reserved  = raw[192:236].decode("ascii").strip()
    n_records = int(raw[236:244].decode("ascii").strip())
    rec_dur   = float(raw[244:252].decode("ascii").strip())
    ns        = int(raw[252:256].decode("ascii").strip())

    FIELDS = [
        ("label",             16),
        ("transducer",        80),
        ("unit",               8),
        ("phys_min",           8),
        ("phys_max",           8),
        ("dig_min",            8),
        ("dig_max",            8),
        ("prefiltering",      80),
        ("n_samples_per_rec",  8),
        ("reserved",          32),
    ]
    sig_raw = f.read(ns * 256)
    sigs = [{} for _ in range(ns)]
    off = 0
    for fname, size in FIELDS:
        for i in range(ns):
            sigs[i][fname] = sig_raw[off:off+size].decode("ascii").strip()
            off += size

    for s in sigs:
        s["n_samples_per_rec"] = int(s["n_samples_per_rec"])
        s["phys_min"] = float(s["phys_min"])
        s["phys_max"] = float(s["phys_max"])
        s["dig_min"]  = float(s["dig_min"])
        s["dig_max"]  = float(s["dig_max"])
        dr = s["dig_max"] - s["dig_min"]
        pr = s["phys_max"] - s["phys_min"]
        s["gain"] = pr / dr if dr else 1.0
        # physical = gain * (digital - dig_min) + phys_min
        s["dc"]   = s["phys_min"] - s["gain"] * s["dig_min"]

    return {
        "n_header":  n_header,
        "reserved":  reserved,
        "n_records": n_records,
        "rec_dur":   rec_dur,
        "ns":        ns,
        "signals":   sigs,
    }


def _read_edf_data(filename: str):
    """
    Parse an EDF / EDF+C file.

    Returns
    -------
    hdr       : dict  (global header fields from _parse_edf_header)
    sigs      : list[dict]  per channel; each has label, unit, gain, dc,
                n_samples_per_rec, data (ndarray or None for ann channel)
    annotations : list[tuple(onset_s, duration_s, text)]
    """
    with open(filename, "rb") as f:
        hdr = _parse_edf_header(f)
        raw_data = f.read()  # all data records, starting at byte n_header

    sigs      = hdr["signals"]
    n_records = hdr["n_records"]
    ns        = hdr["ns"]

    spr          = [s["n_samples_per_rec"] for s in sigs]
    total_spr    = sum(spr)

    is_edf_plus  = hdr["reserved"].startswith("EDF+")
    ann_indices  = set()
    if is_edf_plus:
        for i, s in enumerate(sigs):
            if "EDF Annotations" in s["label"]:
                ann_indices.add(i)

    # Pre-allocate output buffers
    bufs     = [np.empty(n_records * n, dtype=np.float64) for n in spr]
    ann_recs = {i: [] for i in ann_indices}

    for rec in range(n_records):
        rec_byte = rec * total_spr * 2
        ch_byte  = 0
        for i, s in enumerate(sigs):
            n     = spr[i]
            start = rec_byte + ch_byte
            chunk = raw_data[start:start + n * 2]
            if i in ann_indices:
                ann_recs[i].append(chunk)
            else:
                dig = np.frombuffer(chunk, dtype="<i2").astype(np.float64)
                bufs[i][rec * n: rec * n + n] = s["gain"] * dig + s["dc"]
            ch_byte += n * 2

    for i, s in enumerate(sigs):
        s["data"] = None if i in ann_indices else bufs[i]

    annotations: list[tuple[float, float, str]] = []
    for i, recs in ann_recs.items():
        for chunk in recs:
            _parse_tals(chunk, annotations)

    return hdr, sigs, annotations


def _parse_tals(raw: bytes, out: list) -> None:
    """
    Parse EDF+C TAL records from one annotation-channel data block.

    Each TAL: ``+onset[\\x15duration]\\x14[text\\x14]*\\x00``
    Timekeeping TALs (no text) are silently skipped.
    """
    pos, n = 0, len(raw)
    while pos < n:
        end = raw.find(b"\x00", pos)
        if end == -1:
            end = n
        tal = raw[pos:end]
        pos = end + 1
        if not tal:
            continue
        parts = tal.split(b"\x14")
        if not parts:
            continue
        onset_dur = parts[0].decode("ascii", errors="replace")
        if "\x15" in onset_dur:
            onset_str, dur_str = onset_dur.split("\x15", 1)
        else:
            onset_str, dur_str = onset_dur, ""
        try:
            onset = float(onset_str)
        except ValueError:
            continue
        try:
            duration = float(dur_str) if dur_str else 0.0
        except ValueError:
            duration = 0.0
        for p in parts[1:]:
            text = p.decode("ascii", errors="replace").strip()
            if text:
                out.append((onset, duration, text))


# ---------------------------------------------------------------------------
# Channel identification
# ---------------------------------------------------------------------------

_LABEL_ECG  = {"ecg"}
_LABEL_DZ   = {"dz"}
_LABEL_DZDT = {"dzdt", "dz/dt"}
_LABEL_Z0   = {"z0"}
_LABEL_MXR  = {"mxr"}
_LABEL_MYR  = {"myr"}
_LABEL_MZR  = {"mzr"}
_LABEL_ANN  = {"edf annotations"}


# ---------------------------------------------------------------------------
# RSP surrogate from 3-axis accelerometers via PCA
# ---------------------------------------------------------------------------

def _acc_to_rsp(acc: np.ndarray, fs: float) -> np.ndarray:
    """Return a 1-D z-scored respiration surrogate from Nx3 accelerometer data."""
    from scipy.signal import butter, sosfiltfilt
    from numpy.linalg import eigh

    acc = np.asarray(acc, dtype=float)
    nyq = 0.5 * fs

    # gravity removal
    wn_g = min(0.04 / nyq, 0.999)
    sos_g = butter(2, wn_g, btype="low", output="sos")
    gravity = np.column_stack([sosfiltfilt(sos_g, acc[:, k]) for k in range(3)])
    lin = acc - gravity

    # respiration bandpass
    lo = max(0.10 / nyq, 0.001)
    hi = min(0.70 / nyq, 0.999)
    if lo < hi:
        sos_b = butter(4, [lo, hi], btype="band", output="sos")
        band = np.column_stack([sosfiltfilt(sos_b, lin[:, k]) for k in range(3)])
    else:
        band = lin

    # PCA: first principal component (largest eigenvector)
    X = band - band.mean(0)
    C = (X.T @ X) / max(X.shape[0] - 1, 1)
    _, evecs = eigh(C)  # ascending eigenvalues
    rsp = X @ evecs[:, -1]
    s = rsp.std()
    return (rsp - rsp.mean()) / (s if s > 0 else 1.0)


# ---------------------------------------------------------------------------
# VU-AMS EDF / EDF+C loader
# ---------------------------------------------------------------------------
# VU-AMS .cfg condition-label parser
# ---------------------------------------------------------------------------

def _load_vuams_cfg(edf_path: str) -> dict[str, str]:
    """
    Look for a VU-AMS condition-label file (.cfg) alongside the EDF file and
    return a mapping from condition number string to human-readable label.

    Search order
    ------------
    1. ``<same_stem>.cfg`` in the same directory (exact name match)
    2. Any single ``*.cfg`` file in the same directory (fallback for the
       common case where VU-AMS exports the cfg under a different base name)
    3. Nothing found → return empty dict (labels stay as raw codes)

    Format expected
    ---------------
    Lines are ``<number> <label>``; lines starting with ``#`` are comments.
    """
    edf_path_obj = Path(edf_path)
    candidates: list[Path] = []

    # 1. exact stem match
    exact = edf_path_obj.with_suffix(".cfg")
    if exact.exists():
        candidates = [exact]
    else:
        # 2. any .cfg in the same directory
        candidates = list(edf_path_obj.parent.glob("*.cfg"))

    if not candidates:
        return {}
    if len(candidates) > 1:
        logger.warning(
            "EDF loader: multiple .cfg files found; skipping condition-label "
            "lookup. Place a single .cfg next to the .edf to enable labeling."
        )
        return {}

    cfg_path = candidates[0]
    mapping: dict[str, str] = {}
    try:
        with open(cfg_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    mapping[parts[0]] = parts[1]
        logger.info(
            f"EDF loader: loaded {len(mapping)} condition labels from {cfg_path.name}"
        )
    except OSError as exc:
        logger.warning(f"EDF loader: could not read {cfg_path}: {exc}")

    return mapping


def _vuams_label(code: str, cfg: dict[str, str]) -> str:
    """Resolve a VU-AMS annotation code (e.g. '10_') to a human label."""
    key = code.rstrip("_")
    return cfg.get(key, code)


# ---------------------------------------------------------------------------

@register_loader(".edf")
def load_edf(physiodata, filename: str, **kwargs) -> None:
    """
    Load a VU-AMS EDF / EDF+C export.

    Channel mapping
    ---------------
    ECG               → ``ecg-[vuams]``  (primary ECG for HRV)
    DZ                → ``rsp-[vuams]``  (thoracic impedance; preferred — the
                                          channel VU-AMS itself scores RSA from)
    MXR + MYR + MZR   → ``rsp-[vuams]``  (PCA respiration surrogate; fallback if
                                          no impedance channel)
    DZDT              → ``rsp-[vuams]``  (second fallback)
    DZ, DZDT, Z0      → also stored as ``dz-[vuams]`` etc. for inspection
    MXR, MYR, MZR     → also stored as ``mxr-[vuams]`` etc.
    SCL, BAT, MYA     → auxiliary time series

    EDF+C annotations with duration ``onset\x15dur\x14label`` are converted
    to ``"start <label>"`` / ``"stop <label>"`` events so spectHR's epoch
    builder can derive epochs automatically.
    """
    logger.info(f"Loading EDF: {filename}")

    hdr, sigs, annotations = _read_edf_data(filename)
    rec_dur = hdr["rec_dur"]

    def _timestamps(n_per_rec: int, total_samples: int) -> np.ndarray:
        fs = n_per_rec / rec_dur if rec_dur > 0 else float(n_per_rec)
        return np.arange(total_samples, dtype=float) / fs

    # ------------------------------------------------------------------
    # Classify channels by label
    # ------------------------------------------------------------------
    ecg_sig = dz_sig = dzdt_sig = z0_sig = None
    acc_sigs: dict[str, dict] = {}
    aux_sigs: list[dict] = []

    for s in sigs:
        if s["data"] is None:
            continue
        lc = s["label"].lower()
        if lc in _LABEL_ECG:
            ecg_sig = s
        elif lc in _LABEL_DZ:
            dz_sig = s
        elif lc in _LABEL_DZDT:
            dzdt_sig = s
        elif lc in _LABEL_Z0:
            z0_sig = s
        elif lc in _LABEL_MXR:
            acc_sigs["mxr"] = s
        elif lc in _LABEL_MYR:
            acc_sigs["myr"] = s
        elif lc in _LABEL_MZR:
            acc_sigs["mzr"] = s
        elif lc not in _LABEL_ANN:
            aux_sigs.append(s)

    band_id  = "vuams"
    ecg_name = f"ecg-[{band_id}]"
    rsp_name = f"rsp-[{band_id}]"

    # ------------------------------------------------------------------
    # ECG
    # ------------------------------------------------------------------
    if ecg_sig is not None:
        n = len(ecg_sig["data"])
        times = _timestamps(ecg_sig["n_samples_per_rec"], n)
        physiodata.timeseries[ecg_name] = TimeSeries(times, ecg_sig["data"].copy())
        physiodata.has_ecg = True
        fs_ecg = ecg_sig["n_samples_per_rec"] / rec_dur if rec_dur > 0 else 1000.0
        logger.info(f"Loaded ECG → {ecg_name}  ({n} samples @ {fs_ecg:.0f} Hz)")

    # ------------------------------------------------------------------
    # Respiration: DZ (thoracic impedance) → accelerometer PCA → DZDT
    #
    # VU-AMS / VU-DAMS scores respiration and RSA from the thoracic
    # impedance (dZ): it is the physiological respiration signal and is
    # posture-independent.  The accelerometer-PCA surrogate (chest-wall
    # motion) is only a fallback for devices without an impedance channel —
    # its quality varies strongly with posture (the gravity vector and the
    # axis capturing chest expansion change between supine / standing /
    # sitting) and it can lock onto non-respiratory body-motion components,
    # detecting breaths at the wrong rate and roughly halving RSA relative
    # to VU-AMS.  Preferring dZ makes spectHR's RSA match VU-AMS scoring.
    # ------------------------------------------------------------------
    rsp_done = False

    if dz_sig is not None:
        n = len(dz_sig["data"])
        times = _timestamps(dz_sig["n_samples_per_rec"], n)
        physiodata.timeseries[rsp_name] = TimeSeries(times, dz_sig["data"].copy())
        fs_dz = dz_sig["n_samples_per_rec"] / rec_dur if rec_dur > 0 else 1000.0
        logger.info(f"Loaded RSP (DZ thoracic impedance) → {rsp_name}  ({n} samples @ {fs_dz:.0f} Hz)")
        rsp_done = True

    if not rsp_done and all(k in acc_sigs for k in ("mxr", "myr", "mzr")):
        try:
            xs, ys, zs = (acc_sigs[k]["data"] for k in ("mxr", "myr", "mzr"))
            n_common = min(len(xs), len(ys), len(zs))
            acc_mat  = np.column_stack([xs[:n_common], ys[:n_common], zs[:n_common]])
            n_per_rec = acc_sigs["mxr"]["n_samples_per_rec"]
            fs = n_per_rec / rec_dur if rec_dur > 0 else 1000.0
            rsp_signal = _acc_to_rsp(acc_mat, fs)
            times = _timestamps(n_per_rec, n_common)
            physiodata.timeseries[rsp_name] = TimeSeries(times, rsp_signal)
            logger.info(f"Loaded RSP (acc-PCA fallback) → {rsp_name}  ({n_common} samples @ {fs:.0f} Hz)")
            rsp_done = True
        except Exception as exc:
            logger.warning(f"ACC→RSP failed: {exc}; falling back to DZDT")

    if not rsp_done and dzdt_sig is not None:
        n = len(dzdt_sig["data"])
        times = _timestamps(dzdt_sig["n_samples_per_rec"], n)
        physiodata.timeseries[rsp_name] = TimeSeries(times, dzdt_sig["data"].copy())
        fs_dzdt = dzdt_sig["n_samples_per_rec"] / rec_dur if rec_dur > 0 else 1000.0
        logger.info(f"Loaded RSP (DZDT) → {rsp_name}  ({n} samples @ {fs_dzdt:.0f} Hz)")
        rsp_done = True

    # ------------------------------------------------------------------
    # Store raw physiological channels as named auxiliary time series
    # ------------------------------------------------------------------
    _raw_map = [
        (dz_sig,   f"dz-[{band_id}]"),
        (dzdt_sig, f"dzdt-[{band_id}]"),
        (z0_sig,   f"z0-[{band_id}]"),
    ]
    for sig, ts_name in _raw_map:
        if sig is not None and ts_name not in physiodata.timeseries:
            n = len(sig["data"])
            times = _timestamps(sig["n_samples_per_rec"], n)
            physiodata.timeseries[ts_name] = TimeSeries(times, sig["data"].copy())
            logger.debug(f"Stored auxiliary → {ts_name}")

    for key, sig in acc_sigs.items():
        ts_name = f"{key}-[{band_id}]"
        if ts_name not in physiodata.timeseries:
            n = len(sig["data"])
            times = _timestamps(sig["n_samples_per_rec"], n)
            physiodata.timeseries[ts_name] = TimeSeries(times, sig["data"].copy())
            logger.debug(f"Stored auxiliary → {ts_name}")

    for sig in aux_sigs:
        ts_name = f"{sig['label'].lower()}-[{band_id}]"
        n = len(sig["data"])
        times = _timestamps(sig["n_samples_per_rec"], n)
        physiodata.timeseries[ts_name] = TimeSeries(times, sig["data"].copy())
        logger.debug(f"Stored auxiliary → {ts_name}")

    # ------------------------------------------------------------------
    # EDF+C annotations → EventSeries
    # Duration-based annotations become start/stop epoch pairs so that
    # spectHR's epoch builder can derive epochs automatically.
    # A VU-AMS .cfg file (same dir) maps numeric codes to readable labels.
    # ------------------------------------------------------------------
    cfg = _load_vuams_cfg(filename)

    if annotations:
        ev_times:  list[float] = []
        ev_labels: list[str]   = []

        for onset, duration, text in annotations:
            label = _vuams_label(text, cfg)
            if duration > 0:
                ev_times.append(onset)
                ev_labels.append(f"start {label}")
                ev_times.append(onset + duration)
                ev_labels.append(f"stop {label}")
            else:
                ev_times.append(onset)
                ev_labels.append(label)

        sort_order = np.argsort(ev_times)
        ev_times_arr  = np.array(ev_times, dtype=float)[sort_order]
        ev_labels_arr = [ev_labels[i] for i in sort_order]
        physiodata.events["annotations"] = EventSeries(ev_times_arr, ev_labels_arr)
        logger.info(f"Loaded {len(annotations)} EDF annotations → {len(ev_times_arr)} events")

    # Fallback global start/stop so there is always at least one epoch
    if "annotations" not in physiodata.events and physiodata.timeseries:
        ref_ts = next(iter(physiodata.timeseries.values()))
        t0 = float(ref_ts.times[0])
        t1 = float(ref_ts.times[-1])
        physiodata.events["markers"] = EventSeries(
            times=np.array([t0, t1], dtype=float),
            labels=["start experiment", "stop experiment"],
        )

    # ------------------------------------------------------------------
    # Band map
    # ------------------------------------------------------------------
    band: dict[str, str] = {}
    if ecg_name in physiodata.timeseries:
        band["ecg"] = ecg_name
    if rsp_name in physiodata.timeseries:
        band["rsp"] = rsp_name

    if band:
        physiodata.band_map    = {band_id: band}
        physiodata.active_band = band_id
        logger.info(f"Band map: {physiodata.band_map}")
    else:
        logger.warning("EDF loader: no ECG or RSP channel found; band_map is empty")
