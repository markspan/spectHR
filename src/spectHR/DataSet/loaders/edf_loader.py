# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""EDF / EDF+C loader, primary target is VU-AMS 5fs exports."""
from __future__ import annotations

from pathlib import Path
import numpy as np

from spectHR.session import Session, Samples
from spectHR.DataSet.loaders._epochs import build_epochs
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

# The accelerometer→respiration PCA lives in the headless Tools layer so it can
# be re-run per epoch (posture-adaptive); imported here under the old name.
from spectHR.Tools.RespirationSegmentation import accel_to_respiration as _acc_to_rsp


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
def load_edf(path: Path, **kwargs) -> Session:
    """
    Load a VU-AMS EDF / EDF+C export.

    Channel mapping
    ---------------
    ECG               → ``ecg-[vuams]``      (primary ECG for HRV)
    DZ                → ``rsp_icg-[vuams]``   (ICG / thoracic-impedance
                                              respiration candidate, what
                                              VU-AMS scores RSA from)
    MXR + MYR + MZR   → ``rsp_acc-[vuams]``   (PCA respiration-surrogate candidate)
    one of the above  → ``rsp-[vuams]``       (the *active* respiration channel)
    DZ, DZDT, Z0      → also stored as ``dz-[vuams]`` etc. for inspection
    MXR, MYR, MZR     → also stored as ``mxr-[vuams]`` etc.
    SCL, BAT, MYA     → auxiliary time series

    Both respiration candidates are stored so the active ``rsp-[vuams]``
    channel can be switched after load (workspace
    ``RespirationAnalysis.rsp_source`` = ``"icg"`` | ``"accelerometer"``,
    applied by ``spectHR.DataSet.preprocessing.apply_rsp_source``).  The
    ``rsp_source`` keyword argument overrides the default at load time for
    headless use.  The default is ICG / thoracic impedance (matches VU-AMS).

    EDF+C annotations with duration ``onset\x15dur\x14label`` are converted
    to ``"start <label>"`` / ``"stop <label>"`` events so spectHR's epoch
    builder can derive epochs automatically.
    """
    logger.info(f"Loading EDF: {path}")

    hdr, sigs, annotations = _read_edf_data(str(path))
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

    samples: dict[str, Samples] = {}

    # ------------------------------------------------------------------
    # ECG
    # ------------------------------------------------------------------
    if ecg_sig is not None:
        n = len(ecg_sig["data"])
        times = _timestamps(ecg_sig["n_samples_per_rec"], n)
        samples[ecg_name] = Samples(times, ecg_sig["data"].copy(), name=ecg_name)
        fs_ecg = ecg_sig["n_samples_per_rec"] / rec_dur if rec_dur > 0 else 1000.0
        logger.info(f"Loaded ECG → {ecg_name}  ({n} samples @ {fs_ecg:.0f} Hz)")

    # ------------------------------------------------------------------
    # Respiration: store BOTH candidate sources, then pick one for the
    # active rsp-[vuams] channel.
    #
    # VU-AMS / VU-DAMS scores respiration and RSA from the thoracic
    # impedance (dZ): it is the physiological respiration signal and is
    # posture-independent.  The accelerometer-PCA surrogate (chest-wall
    # motion) varies strongly with posture (the gravity vector and the axis
    # capturing chest expansion change between supine / standing / sitting)
    # and can lock onto non-respiratory body-motion components, detecting
    # breaths at the wrong rate and roughly halving RSA relative to VU-AMS,
    # but it is useful for ambulatory/movement recordings or devices without
    # an impedance channel.
    #
    # Both candidates are stored so the choice is reconfigurable after load
    # (workspace ``RespirationAnalysis.rsp_source``, applied by the UI via
    # ``spectHR.DataSet.preprocessing.apply_rsp_source``).  The active rsp-[vuams] defaults to the ICG
    # (impedance) signal → accelerometer → DZDT.  The ``rsp_source`` kwarg,
    # when given, overrides the default at load time without the UI.
    # ------------------------------------------------------------------
    rsp_acc_name = f"rsp_acc-[{band_id}]"   # accelerometer-PCA candidate
    rsp_icg_name = f"rsp_icg-[{band_id}]"   # thoracic-impedance (ICG) candidate

    # ICG candidate (dZ thoracic impedance, or dZ/dt as a fallback).
    icg_sig = dz_sig if dz_sig is not None else dzdt_sig
    if icg_sig is not None:
        n = len(icg_sig["data"])
        times = _timestamps(icg_sig["n_samples_per_rec"], n)
        samples[rsp_icg_name] = Samples(times, icg_sig["data"].copy(), name=rsp_icg_name)

    # Accelerometer-PCA candidate.
    if all(k in acc_sigs for k in ("mxr", "myr", "mzr")):
        try:
            xs, ys, zs = (acc_sigs[k]["data"] for k in ("mxr", "myr", "mzr"))
            n_common = min(len(xs), len(ys), len(zs))
            acc_mat  = np.column_stack([xs[:n_common], ys[:n_common], zs[:n_common]])
            n_per_rec = acc_sigs["mxr"]["n_samples_per_rec"]
            fs = n_per_rec / rec_dur if rec_dur > 0 else 1000.0
            rsp_signal = _acc_to_rsp(acc_mat, fs)
            times = _timestamps(n_per_rec, n_common)
            samples[rsp_acc_name] = Samples(times, rsp_signal, name=rsp_acc_name)
        except Exception as exc:
            logger.warning(f"ACC→RSP failed: {exc}")

    # Pick the active respiration channel.  The kwarg overrides the default;
    # "accelerometer" only wins when that candidate was actually built.
    requested = str(kwargs.get("rsp_source", "icg")).lower()
    icg_ts = samples.get(rsp_icg_name)
    acc_ts = samples.get(rsp_acc_name)

    chosen, chosen_lbl = None, ""
    if requested == "accelerometer" and acc_ts is not None:
        chosen, chosen_lbl = acc_ts, "accelerometer-PCA"
    elif icg_ts is not None:
        chosen, chosen_lbl = icg_ts, "ICG (DZ thoracic impedance)"
    elif acc_ts is not None:
        chosen, chosen_lbl = acc_ts, "accelerometer-PCA (no ICG channel)"

    if chosen is not None:
        samples[rsp_name] = Samples(
            chosen.times.copy(), chosen.values.copy(), name=rsp_name
        )
        logger.info(
            f"Loaded RSP ({chosen_lbl}) → {rsp_name}  ({chosen.times.size} samples)"
        )

    # ------------------------------------------------------------------
    # Store raw physiological channels as named auxiliary time series
    # ------------------------------------------------------------------
    _raw_map = [
        (dz_sig,   f"dz-[{band_id}]"),
        (dzdt_sig, f"dzdt-[{band_id}]"),
        (z0_sig,   f"z0-[{band_id}]"),
    ]
    for sig, ts_name in _raw_map:
        if sig is not None and ts_name not in samples:
            n = len(sig["data"])
            times = _timestamps(sig["n_samples_per_rec"], n)
            samples[ts_name] = Samples(times, sig["data"].copy(), name=ts_name)
            logger.debug(f"Stored auxiliary → {ts_name}")

    for key, sig in acc_sigs.items():
        ts_name = f"{key}-[{band_id}]"
        if ts_name not in samples:
            n = len(sig["data"])
            times = _timestamps(sig["n_samples_per_rec"], n)
            samples[ts_name] = Samples(times, sig["data"].copy(), name=ts_name)
            logger.debug(f"Stored auxiliary → {ts_name}")

    for sig in aux_sigs:
        ts_name = f"{sig['label'].lower()}-[{band_id}]"
        n = len(sig["data"])
        times = _timestamps(sig["n_samples_per_rec"], n)
        samples[ts_name] = Samples(times, sig["data"].copy(), name=ts_name)
        logger.debug(f"Stored auxiliary → {ts_name}")

    # ------------------------------------------------------------------
    # EDF+C annotations → marker lists for epoch building
    # Duration-based annotations become start/stop epoch pairs so that
    # spectHR's epoch builder can derive epochs automatically.
    # A VU-AMS .cfg file (same dir) maps numeric codes to readable labels.
    # ------------------------------------------------------------------
    cfg = _load_vuams_cfg(str(path))

    marker_times: list[float] = []
    marker_labels: list[str] = []

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
        marker_times  = [ev_times[i] for i in sort_order]
        marker_labels = [ev_labels[i] for i in sort_order]
        logger.info(f"Loaded {len(annotations)} EDF annotations → {len(marker_times)} events")

    # Fallback global start/stop so there is always at least one epoch
    if not annotations and samples:
        ref_s = next(iter(samples.values()))
        if ref_s.times.size:
            marker_times  = [float(ref_s.times[0]), float(ref_s.times[-1])]
            marker_labels = ["start experiment", "stop experiment"]

    # ------------------------------------------------------------------
    # Normalize so t=0 is the start of the earliest channel
    # ------------------------------------------------------------------
    if samples:
        t_min = min(float(s.times[0]) for s in samples.values() if s.times.size)
        if t_min != 0.0:
            samples = {k: Samples(s.times - t_min, s.values, s.name) for k, s in samples.items()}
            marker_times = [t - t_min for t in marker_times]

    t_start = 0.0
    t_end = max((float(s.times[-1]) for s in samples.values() if s.times.size), default=0.0)
    epochs = build_epochs(marker_times, marker_labels, t_start=t_start, t_end=t_end)
    return Session(name=Path(path).stem, samples=samples, epochs=epochs)
