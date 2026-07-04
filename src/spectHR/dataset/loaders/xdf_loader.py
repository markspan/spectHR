# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pyxdf

from spectHR.dataset.loaders.registry import register_loader
from spectHR.logger import logger

if TYPE_CHECKING:
    from spectHR.session import Session

# ------------------------------------------------------------
# INTERNAL: 3-axis Respiration signal computation
# ------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers for _compute_RSP_signal
# ---------------------------------------------------------------------------

def _interp_nans(x: np.ndarray) -> np.ndarray:
    """Linearly interpolate NaN gaps in a 1-D array; returns zeros if < 2 valid."""
    if not np.isnan(x).any():
        return x
    idx = np.arange(x.size)
    good = ~np.isnan(x)
    if good.sum() < 2:
        return np.zeros_like(x)
    return np.interp(idx, idx[good], x[good])


def _robust_winsorize(x: np.ndarray, z: float) -> np.ndarray:
    """Clip *x* to median ± z * (1.4826 * MAD); robust to outliers."""
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    sigma = 1.4826 * mad if mad > 0 else np.std(x)
    if sigma <= 0:
        return x
    return np.clip(x, med - z * sigma, med + z * sigma)


def _butter_sos(kind: str, cutoff, order: int, fs: float):
    """Build a SOS Butterworth filter.  *kind* is ``"low"`` or ``"band"``."""
    from scipy.signal import butter
    nyq = 0.5 * fs
    if kind == "low":
        wn = float(cutoff) / nyq
        if not (0 < wn < 1):
            raise ValueError("gravity_cutoff_hz must be between 0 and Nyquist.")
        return butter(order, wn, btype="low", output="sos")
    elif kind == "band":
        lo, hi = float(cutoff[0]) / nyq, float(cutoff[1]) / nyq
        if not (0 < lo < hi < 1):
            raise ValueError("rsp_band_hz must be within (0, Nyquist) and low < high.")
        return butter(order, [lo, hi], btype="bandpass", output="sos")
    raise ValueError(f"Unsupported filter kind: {kind!r}.")


def _sos_filtfilt(sos, x: np.ndarray) -> np.ndarray:
    """Zero-phase SOS filter; falls back to unfiltered if *x* is too short."""
    from scipy.signal import sosfiltfilt
    if x.size < max(3 * (sos.shape[0] * 2 + 1), 15):
        return x.copy()
    return sosfiltfilt(sos, x)


def _compute_RSP_signal(
    acc: np.ndarray,
    fs: float,
    *,
    # Gravity / orientation tracking (very low frequency)
    gravity_cutoff_hz: float = 0.04,
    gravity_order: int = 2,
    # Respiration band (typical adult: ~0.1–0.7 Hz; tune to your paradigm)
    rsp_band_hz: tuple[float, float] = (0.10, 0.70),
    rsp_order: int = 4,
    # Robustness
    winsorize_z: float | None = 8.0,
    nan_policy: str = "interp",
    # Output scaling
    zscore: bool = True,
) -> np.ndarray:
    """
    Extract a respiration surrogate signal from Nx3 chest-belt accelerometer data.

    Pipeline
    --------
    1) Robust cleanup (NaNs, extreme spikes)
    2) Estimate gravity via low-pass and subtract (linear acceleration)
    3) Bandpass linear acceleration to respiration band
    4) PCA (first principal component) on bandpassed 3D signal to obtain a 1D respiration surrogate
    5) Optional z-score normalization

    Parameters
    ----------
    acc:
        Array shaped (N, 3). Units do not matter (g or m/s^2) as long as consistent.
    fs:
        Sampling rate in Hz.
    gravity_cutoff_hz:
        Low-pass cutoff for gravity/orientation estimate. Lower => smoother orientation tracking.
        0.02–0.08 Hz are typical for chest belts.
    rsp_band_hz:
        Bandpass (low, high) in Hz for respiration motion.
    gravity_order, rsp_order:
        Butterworth filter orders. We use SOS + filtfilt for stability/zero-phase.
    winsorize_z:
        If not None: clip each axis to median ± winsorize_z * MAD-based sigma (robust).
        Helps with bumps/impacts.
    nan_policy:
        "interp" to linearly interpolate NaNs per axis; "raise" to error; "omit" to fill with 0.
    zscore:
        If True, return a standardized signal (mean 0, std 1).
    Returns
    -------
    rsp : np.ndarray, shape (N,)
        Respiration surrogate signal.

    Notes
    -----
    - If the belt orientation changes slowly, gravity removal + PCA is generally robust.
    - If there are large posture changes, consider segment-wise PCA (e.g., per
      epoch) using the same code.
    """
    acc = np.asarray(acc, dtype=float)
    if acc.ndim != 2 or acc.shape[1] != 3:
        raise ValueError(f"`acc` must have shape (N, 3). Got {acc.shape}.")
    if fs <= 0:
        raise ValueError("`fs` must be > 0.")

    # ---------- 1) NaNs + winsorize ----------
    acc2 = acc.copy()
    for k in range(3):
        if nan_policy == "interp":
            acc2[:, k] = _interp_nans(acc2[:, k])
        elif nan_policy == "omit":
            acc2[:, k] = np.nan_to_num(acc2[:, k], nan=0.0)
        elif nan_policy == "raise":
            if np.isnan(acc2[:, k]).any():
                raise ValueError(
                    "NaNs present in acc; set nan_policy='interp' or 'omit'."
                )
        else:
            raise ValueError("nan_policy must be 'interp', 'omit', or 'raise'.")

    if winsorize_z is not None:
        z = float(winsorize_z)
        for k in range(3):
            acc2[:, k] = _robust_winsorize(acc2[:, k], z)

    # ---------- 2) gravity estimate + removal ----------
    sos_g = _butter_sos("low", gravity_cutoff_hz, gravity_order, fs)
    gravity = np.column_stack([_sos_filtfilt(sos_g, acc2[:, k]) for k in range(3)])
    lin_acc = acc2 - gravity

    # ---------- 3) bandpass to respiration band ----------
    sos_rsp = _butter_sos("band", rsp_band_hz, rsp_order, fs)
    band3 = np.column_stack([_sos_filtfilt(sos_rsp, lin_acc[:, k]) for k in range(3)])

    # ---------- 4) PCA on bandpassed 3D signal ----------
    # Center
    X = band3 - band3.mean(axis=0, keepdims=True)

    # Covariance + eigendecomposition (3x3 => cheap, stable)
    C = (X.T @ X) / max(X.shape[0] - 1, 1)
    evals, evecs = np.linalg.eigh(C)  # ascending
    order = np.argsort(evals)[::-1]
    evals = evals[order]
    evecs = evecs[:, order]
    pc1 = evecs[:, 0]

    rsp = X @ pc1

    # Optional: enforce consistent sign (purely cosmetic)
    # Make rsp positively correlated with the axis that has largest loading magnitude
    main_axis = int(np.argmax(np.abs(pc1)))
    if np.corrcoef(rsp, X[:, main_axis])[0, 1] < 0:
        rsp = -rsp
        pc1 = -pc1

    # ---------- 5) scale ----------
    if zscore:
        s = np.std(rsp)
        rsp = (rsp - np.mean(rsp)) / (s if s > 0 else 1.0)

    return rsp


# ------------------------------------------------------------
# XDF LOADER
# ------------------------------------------------------------


@register_loader(".xdf")
def load_xdf(path: Path, **kwargs) -> "Session":
    """Load a Polar/LSL .xdf file as a Session."""
    from spectHR.dataset.loaders._epochs import build_epochs
    from spectHR.session import Samples, Session

    logger.info(f"Loading XDF: {path}")
    streams, _ = pyxdf.load_xdf(str(path))

    samples: dict[str, Samples] = {}
    marker_times: list[float]  = []
    marker_labels: list[str]   = []
    keyboard_events: list[tuple[float, str]] = []

    for stream in streams:
        info      = stream.get("info", {})
        name      = str(info.get("name", [""])[0])
        stype     = str(info.get("type", [""])[0])
        name_lower = name.lower()
        try:
            srate = float(info.get("nominal_srate", [0])[0])
        except Exception:
            srate = 0.0

        is_polar = stype.upper() in ("ECG", "ACCELEROMETER")

        # ---- MARKER STREAMS ------------------------------------------------
        if (("event" in stype.lower() or "marker" in stype.lower())
                and not name_lower.startswith("cam")):
            raw_times = np.asarray(stream["time_stamps"], dtype=float)
            for t, row in zip(raw_times, stream["time_series"]):
                label = str(row[0])
                if label.lower().startswith("end "):
                    label = "stop " + label[4:]
                if name_lower == "keyboard":
                    keyboard_events.append((float(t), label))
                marker_times.append(float(t))
                marker_labels.append(label)
            continue

        if not is_polar or srate <= 0:
            continue

        # ---- POLAR STREAMS -------------------------------------------------
        times = np.asarray(stream["time_stamps"], dtype=float)
        data  = np.asarray(stream["time_series"], dtype=float)
        if data.ndim == 1:
            data = data[:, None]

        device_prefix = name.rsplit("_", 1)[0]
        suffix        = f"-[{device_prefix[-8:]}]"

        if not name_lower.endswith("_acc"):
            values   = data[:, 0] if data.ndim == 2 else data
            ecg_name = f"ecg{suffix}"
            samples[ecg_name] = Samples(times, values, name=ecg_name)
            logger.info(f"Loaded ECG → {ecg_name}")
        else:
            if data.shape[1] != 3:
                logger.warning(f"ACC stream {name} does not have 3 channels. Skipped.")
                continue
            diffs = np.diff(times)
            diffs = diffs[diffs > 0]
            if len(diffs) == 0:
                logger.warning(f"ACC stream {name} has invalid timestamps.")
                continue
            fs  = 1.0 / np.mean(diffs)
            rsp = _compute_RSP_signal(data, fs)
            rsp_name = f"RSP{suffix}"
            samples[rsp_name] = Samples(times, rsp, name=rsp_name)
            logger.info(f"Loaded RSP → {rsp_name}")

    if not samples:
        logger.warning("No usable Polar time series found.")

    # Normalize timestamps so the earliest sample starts at t=0
    if samples:
        t_min = min(float(s.times[0]) for s in samples.values() if s.times.size)
        if t_min != 0.0:
            samples = {k: Samples(s.times - t_min, s.values, s.name) for k, s in samples.items()}
            marker_times = [t - t_min for t in marker_times]
            keyboard_events = [(t - t_min, lbl) for t, lbl in keyboard_events]

    # ---- Keyboard fallback ------------------------------------------------
    has_epoch_markers = any(
        lbl.lower().startswith(("start ", "stop "))
        for lbl in marker_labels
    )
    if not has_epoch_markers and keyboard_events:
        pressed = [(t, lbl) for t, lbl in keyboard_events if lbl.lower().endswith(" pressed")]
        if pressed:
            t_rec_end = max(
                (float(s.times[-1]) for s in samples.values() if s.times.size),
                default=pressed[-1][0],
            )
            base_names = [lbl[:lbl.lower().rfind(" pressed")].strip() for _, lbl in pressed]
            counts = Counter(base_names)
            seen: dict[str, int] = {}
            for i, (t_press, _) in enumerate(pressed):
                base = base_names[i]
                t_stop = pressed[i+1][0] if i + 1 < len(pressed) else t_rec_end
                if counts[base] == 1:
                    name = base
                else:
                    seen[base] = seen.get(base, 0) + 1
                    name = f"{base}#{seen[base]}"
                marker_times.extend([t_press, t_stop])
                marker_labels.extend([f"start {name}", f"stop {name}"])

    t_start = 0.0
    t_end = max(
        (float(s.times[-1]) for s in samples.values() if s.times.size),
        default=0.0,
    )
    epochs = build_epochs(marker_times, marker_labels, t_start=t_start, t_end=t_end)

    return Session(name=Path(path).stem, samples=samples, epochs=epochs)
