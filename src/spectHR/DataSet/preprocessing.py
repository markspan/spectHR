# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/preprocessing.py
"""
Loader-agnostic pre-processing transforms: ``Session`` → ``Session``.

These are the steps that turn a freshly *parsed* recording into one ready
for analysis: ECG polarity correction, R-peak detection, blood-pressure
calibration and respiration-source selection.  They are pure, headless
(no Qt), and generic across every loader — the loaders only *parse*; this
module *conditions*.  The Qt UI calls these; it does not own them.

Each transform returns a **new** ``Session`` when it changes anything and
the *same* object when it does not, so chaining them is cheap and free of
surprises::

    session = load(path)
    session = apply_ecg_polarity(session)        # flip inverted ECG first
    session = apply_rsp_source(session, params)
    session = apply_bp_calibration(session, params)
    session = apply_beat_detection(session, params)

Channel resolution is shared from here too: loaders disagree on keys
(canonical ``"ecg"`` vs device-suffixed ``"ecg-[8554112A]"``), so
:func:`resolve_ecg` / :func:`resolve_resp` give every consumer one answer.

Parameters are taken as a :class:`~spectHR.config.WorkspaceView` (typed),
a raw workspace ``dict``, or ``None`` (defaults) — so headless scripts and
the UI share one entry point.
"""
from __future__ import annotations

import numpy as np

from spectHR.config import CardioParams, WorkspaceView
from spectHR.session import Events, Intervals, Samples, Session
from spectHR.Tools.ECGProcessing import detect_ecg_polarity
from spectHR.Tools.Logger import logger
from spectHR.Tools.RespirationSegmentation import (
    accel_to_respiration,
    segment_respiration,
)

__all__ = [
    "resolve_ecg",
    "resolve_resp",
    "resolve_bp",
    "resolve_icg",
    "resolve_accel_axes",
    "apply_canonical_channels",
    "filter_ecg",
    "apply_ecg_polarity",
    "apply_beat_detection",
    "apply_bp_calibration",
    "apply_rsp_source",
    "apply_breath_phases",
    "recompute_breath_phases",
    "retrigger_beats",
    "retrigger_beats_per_epoch",
    "invert_ecg",
]

# Accept either a WorkspaceView, a raw dict, or None.
_ParamsLike = "WorkspaceView | dict | None"


def _as_view(params: _ParamsLike) -> WorkspaceView:
    """Return a :class:`WorkspaceView` whatever form *params* arrives in."""
    if isinstance(params, WorkspaceView):
        return params
    return WorkspaceView(params)


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------
#
# Loaders disagree on sample-channel keys: NFF/EVT use canonical ``"ecg"`` /
# ``"resp"``, while XDF/EDF suffix them with the device id
# (``"ecg-[8554112A]"``, ``"RSP-[8554112A]"``).  These resolvers prefer the
# canonical accessor and fall back to a case-insensitive prefix scan, so every
# downstream consumer finds the same channel regardless of source.


def resolve_ecg(session: Session) -> Samples | None:
    """Return the ECG channel: canonical ``"ecg"`` or first ``ecg*`` channel."""
    return session.ecg or _first_with_prefix(session, ("ecg",))


def resolve_resp(session: Session) -> Samples | None:
    """Return the respiration channel: canonical, or first ``resp*`` / ``rsp*``."""
    return session.resp or _first_with_prefix(session, ("resp", "rsp"))


def resolve_bp(session: Session) -> Samples | None:
    """Return the blood-pressure channel: canonical, or first ``bp*`` variant."""
    return session.bp or _first_with_prefix(session, ("bp", "fbp", "abp", "finap", "nibp"))


def resolve_icg(session: Session) -> Samples | None:
    """Return the ICG (dZ/dt) channel: canonical ``"icg"`` or a ``dzdt*`` variant.

    VU-AMS EDF recordings carry the impedance-cardiogram derivative under
    ``dzdt-[device]`` rather than ``icg`` — that derivative *is* the ICG signal
    PEP detection needs, so it resolves here.
    """
    return session.icg or _first_with_prefix(session, ("icg", "dzdt", "dz/dt"))


def _first_with_prefix(session: Session, prefixes: tuple[str, ...]) -> Samples | None:
    """First sample channel whose key starts (case-insensitively) with a prefix."""
    for key, sig in session.samples.items():
        if key.lower().startswith(prefixes):
            return sig
    return None


def apply_canonical_channels(session: Session, params: _ParamsLike = None) -> Session:  # noqa: ARG001
    """Alias device-suffixed channels to their canonical keys.

    Loaders keep raw keys (``ecg-[vuams]``, ``dzdt-[vuams]``, ``rsp-[…]``), but
    the per-epoch metrics and docks read the canonical accessors
    (``session.ecg`` / ``resp`` / ``bp`` / ``icg``), which only match the
    canonical key.  This early step resolves each canonical channel once and
    stores the *same* ``Samples`` object under the canonical key (no copy), so
    BP / respiration / RSA / PEP metrics light up for suffixed recordings.
    Returns the same session when every canonical channel already exists.
    """
    resolvers = {"ecg": resolve_ecg, "resp": resolve_resp,
                 "bp": resolve_bp, "icg": resolve_icg}
    additions = {
        canon: ch
        for canon, resolve in resolvers.items()
        if session.samples.get(canon) is None and (ch := resolve(session)) is not None
    }
    if not additions:
        return session
    logger.info("Canonicalised channels: %s", ", ".join(sorted(additions)))
    return Session(
        name=session.name,
        samples={**session.samples, **additions},
        events=session.events,
        intervals=session.intervals,
        epochs=session.epochs,
    )


# ---------------------------------------------------------------------------
# ECG polarity correction
# ---------------------------------------------------------------------------


def _polarity_segment(session: Session):
    """Pick the analysis segment for polarity detection.

    Prefers the first non-``"experiment"`` active epoch — a task block is a
    cleaner stretch of beats than the whole recording — and falls back to
    ``None`` so :func:`detect_ecg_polarity` uses the recording's middle third.
    """
    for name, ep in session.epochs.items():
        if name != "experiment" and getattr(ep, "active", False):
            return ep
    return None


def apply_ecg_polarity(session: Session, params: _ParamsLike = None) -> Session:
    """Return a new ``Session`` with every inverted ECG channel flipped upright.

    A loader-agnostic, early pre-processing step: it inspects each channel
    whose key starts with ``"ecg"`` (canonical ``"ecg"`` and device-suffixed
    ``"ecg-[…]"`` alike), decides its polarity with
    :func:`~spectHR.Tools.ECGProcessing.detect_ecg_polarity` (skewness of the
    band-passed QRS, with a peak-prominence tiebreaker), and negates the
    values of any channel detected as ``"inverted"`` so downstream R-peak
    detection sees upright R-waves.

    Should run before beat detection.  Sessions with no ECG — or whose ECG
    already reads upright — are returned unchanged (same object), so it is
    cheap and side-effect-free in the common case.

    *params* is accepted for pipeline symmetry and currently unused.
    """
    ecg_keys = [k for k in session.samples if k.lower().startswith("ecg")]
    if not ecg_keys:
        return session

    segment = _polarity_segment(session)
    seg_desc = "middle third" if segment is None else getattr(segment, "label", segment)

    new_samples = dict(session.samples)
    flipped_any = False
    for key in ecg_keys:
        ecg = session.samples[key]
        if ecg.times.size < 2:
            continue
        try:
            polarity = detect_ecg_polarity(ecg.times, ecg.values, segment=segment)
        except Exception as exc:  # noqa: BLE001 — never abort a load over polarity
            logger.warning("ECG polarity detection failed for %s: %s", key, exc)
            continue

        if polarity == "inverted":
            new_samples[key] = Samples(ecg.times, -np.asarray(ecg.values), ecg.name)
            flipped_any = True
            logger.info(
                "ECG polarity: %s detected inverted → flipped (segment: %s)",
                key, seg_desc,
            )
        else:
            logger.info("ECG polarity: %s detected normal (segment: %s)", key, seg_desc)

    if not flipped_any:
        return session

    return Session(
        name=session.name,
        samples=new_samples,
        events=session.events,
        intervals=session.intervals,
        epochs=session.epochs,
    )


# ---------------------------------------------------------------------------
# ECG prefilter + R-peak detection
# ---------------------------------------------------------------------------


def filter_ecg(ecg: Samples | None, cardio: CardioParams) -> Samples | None:
    """Apply the configured ECG prefilter, falling back to the raw signal.

    Honours :attr:`CardioParams.ecg_filter_type` / ``ecg_filter_cutoff``
    (e.g. a 0.5 Hz high-pass to strip baseline wander).  Returns the input
    unchanged when no filter is configured, the signal is too short, or the
    cutoff is invalid for the channel's sampling rate.
    """
    if ecg is None or ecg.times.size < 2 or not cardio.ecg_filter_type:
        return ecg
    try:
        return ecg.filtered(
            filter_type=cardio.ecg_filter_type, cutoff=cardio.ecg_filter_cutoff
        )
    except Exception as exc:  # noqa: BLE001 — bad cutoff / too-short signal
        logger.warning("ECG prefilter skipped (%s).", exc)
        return ecg


def _without_hrv(session: Session) -> Session:
    """Return a copy of *session* with the ``"hrv"`` channel removed."""
    return Session(
        name=session.name,
        samples=session.samples,
        events={k: v for k, v in session.events.items() if k != "hrv"},
        intervals=session.intervals,
        epochs=session.epochs,
    )


def retrigger_beats(session: Session, params: _ParamsLike = None) -> Session:
    """Re-detect R-peaks from the ECG, discarding any existing ``"hrv"``.

    Unlike :func:`apply_beat_detection` (which leaves an already-detected
    session untouched), this forces a fresh detection — the "retrigger
    R-tops" action that throws away manual edits and redetects from scratch.
    """
    return apply_beat_detection(_without_hrv(session), params)


def retrigger_beats_per_epoch(session: Session, params: _ParamsLike = None) -> Session:
    """Re-detect R-peaks within each active epoch, leaving beats outside epochs intact.

    Unlike :func:`retrigger_beats` (which discards all R-peaks and redetects
    over the whole recording), this function only replaces beats that fall
    inside active epoch windows.  Manually edited beats outside any epoch are
    preserved.  When no epochs are defined, falls back to a full retrigger.
    """
    active_epochs = [ep for ep in session.epochs.values() if ep.active]
    if not active_epochs:
        return retrigger_beats(session, params)

    ecg = resolve_ecg(session)
    if ecg is None or ecg.times.size < 2:
        return session

    cardio = _as_view(params).cardio_params
    filtered = filter_ecg(ecg, cardio)

    existing_hrv = session.events.get("hrv")
    if existing_hrv is None:
        existing_hrv = Events(
            np.empty(0, dtype=np.float64), np.empty(0, dtype=object)
        )

    hrv = existing_hrv
    for epoch in active_epochs:
        epoch_ecg = filtered.window(epoch.start, epoch.end)
        if epoch_ecg.times.size < 2:
            continue
        try:
            new_beats = Events.detect(
                epoch_ecg,
                min_peak_distance_ms=cardio.min_peak_distance_ms,
                window_length=cardio.window_length,
                n_std=cardio.n_std,
                max_ibi_sec=cardio.max_ibi_sec,
            )
        except Exception:  # noqa: BLE001
            logger.exception("R-peak detection failed for epoch %s", epoch.label)
            continue
        hrv = hrv.replace_window(epoch.start, epoch.end, new_beats)
        logger.info(
            "Detected %d R-peaks in epoch '%s'", new_beats.times.size, epoch.label
        )

    return Session(
        name=session.name,
        samples=session.samples,
        events={**session.events, "hrv": hrv},
        intervals=session.intervals,
        epochs=session.epochs,
    )


def invert_ecg(session: Session, params: _ParamsLike = None) -> Session:
    """Flip every ECG channel and re-detect R-peaks.

    The manual-override counterpart to :func:`apply_ecg_polarity`: when the
    automatic polarity decision was wrong, this inverts the ECG and triggers
    a fresh detection on the corrected signal.
    """
    new_samples = dict(session.samples)
    for key, sig in session.samples.items():
        if key.lower().startswith("ecg"):
            new_samples[key] = Samples(sig.times, -np.asarray(sig.values), sig.name)
    flipped = Session(
        name=session.name,
        samples=new_samples,
        events={k: v for k, v in session.events.items() if k != "hrv"},
        intervals=session.intervals,
        epochs=session.epochs,
    )
    return apply_beat_detection(flipped, params)


def apply_beat_detection(session: Session, params: _ParamsLike = None) -> Session:
    """Return a new ``Session`` with R-peaks detected when none are present.

    The ECG is resolved (canonical or device-suffixed key), prefiltered per
    ``CardioParameters.EcgPreprocessing``, and passed to :meth:`Events.detect`
    with the workspace ``CardioParameters.IbiClassification`` thresholds.
    Sessions that already carry an ``"hrv"`` channel (e.g. CARSPAN ``.evt``
    recordings) — or that have no usable ECG — are returned unchanged.

    The work is O(n) over the recording; callers that must not block a UI
    thread (e.g. ``MainWindow._LoadWorker``) run it on a background thread.
    """
    if session.events.get("hrv") is not None:
        return session

    ecg = resolve_ecg(session)
    if ecg is None or ecg.times.size < 2:
        return session

    cardio = _as_view(params).cardio_params
    filtered = filter_ecg(ecg, cardio)
    try:
        hrv = Events.detect(
            filtered,
            min_peak_distance_ms=cardio.min_peak_distance_ms,
            window_length=cardio.window_length,
            n_std=cardio.n_std,
            max_ibi_sec=cardio.max_ibi_sec,
        )
    except Exception:  # noqa: BLE001 — detection must never abort a load
        logger.exception("R-peak detection failed; loading without beats.")
        return session

    logger.info("Detected %d R-peaks from %s", hrv.times.size, ecg.name or "ecg")
    return Session(
        name=session.name,
        samples=session.samples,
        events={**session.events, "hrv": hrv},
        intervals=session.intervals,
        epochs=session.epochs,
    )


# ---------------------------------------------------------------------------
# BP calibration
# ---------------------------------------------------------------------------


def apply_bp_calibration(session: Session, params: _ParamsLike = None) -> Session:
    """Return a new ``Session`` with the ``bp`` channel scaled to mmHg.

    Reads ``bp_scale`` and ``bp_zero`` from the analysis parameters and
    applies ``mmHg = scale * raw + zero``.  When scale is zero (no
    calibration available) the channel is left unchanged.
    """
    bp = session.bp
    if bp is None:
        return session

    scale, zero = _as_view(params).bp_calibration
    if scale == 0.0:
        return session

    calibrated = Samples(times=bp.times, values=bp.values * scale + zero, name=bp.name)
    return Session(
        name=session.name,
        samples={**session.samples, "bp": calibrated},
        events=session.events,
        intervals=session.intervals,
        epochs=session.epochs,
    )


# ---------------------------------------------------------------------------
# Respiration source selection
# ---------------------------------------------------------------------------


def apply_rsp_source(session: Session, params: _ParamsLike = None) -> Session:
    """Return a new ``Session`` with the canonical ``resp`` channel set.

    A *native* respiration channel always wins: it is the actual breathing
    trace, so it must not be replaced by a surrogate.  Only when the recording
    carries no respiration channel of its own does this derive ``resp`` from
    the configured ``rsp_source``:

    * ``"icg"`` — uses the ``icg`` channel if present (thoracic impedance).
    * ``"accelerometer"`` — uses ``accel_rsp`` if present (PCA surrogate).

    This guard matters once :func:`apply_canonical_channels` has aliased a
    device-suffixed impedance channel to ``icg`` (e.g. VU-AMS ``dzdt-[…]``):
    without it, ``rsp_source="icg"`` would overwrite a perfectly good
    respiration channel with the ICG derivative, which oscillates at the
    heart rate rather than the breathing rate.  When the requested source is
    unavailable the session is returned unchanged.
    """
    if resolve_resp(session) is not None:
        return session   # native respiration present — keep it

    source = _as_view(params).rsp_source
    key = "icg" if source == "icg" else "accel_rsp"

    sig = session.samples.get(key)
    if sig is None:
        return session

    rsp = Samples(times=sig.times, values=sig.values, name="resp")
    return Session(
        name=session.name,
        samples={**session.samples, "resp": rsp},
        events=session.events,
        intervals=session.intervals,
        epochs=session.epochs,
    )


# ---------------------------------------------------------------------------
# Breath-phase segmentation
# ---------------------------------------------------------------------------


# Accelerometer-axis key triples recognised when rebuilding the respiration
# surrogate (VU-AMS ``mxr/myr/mzr`` first, then generic spellings).
_ACCEL_AXIS_TRIPLES: tuple[tuple[str, str, str], ...] = (
    ("mxr", "myr", "mzr"),
    ("acc_x", "acc_y", "acc_z"),
    ("accx", "accy", "accz"),
)


def resolve_accel_axes(session: Session):
    """Return the ``(x, y, z)`` accelerometer-axis :class:`Samples`, or ``None``.

    Matches the loader's raw 3-axis channels (e.g. VU-AMS ``mxr-[…]`` /
    ``myr-[…]`` / ``mzr-[…]``) so the respiration PCA can be rebuilt per epoch.
    """
    lower = {k.lower(): k for k in session.samples}
    for ax, ay, az in _ACCEL_AXIS_TRIPLES:
        kx = next((lower[k] for k in lower if k.startswith(ax)), None)
        ky = next((lower[k] for k in lower if k.startswith(ay)), None)
        kz = next((lower[k] for k in lower if k.startswith(az)), None)
        if kx and ky and kz:
            return session.samples[kx], session.samples[ky], session.samples[kz]
    return None


def _respiration_window(
    session: Session,
    view: WorkspaceView,
    t0: float | None,
    t1: float | None,
) -> Samples | None:
    """Build the respiration signal for a window (whole recording when *t0* is None).

    For the accelerometer source the surrogate is recomputed from the raw
    3-axis accelerometer over exactly this window (posture-adaptive PCA);
    otherwise the native respiration channel is sliced.
    """
    if view.rsp_source == "accelerometer":
        axes = resolve_accel_axes(session)
        if axes is not None:
            xs, ys, zs = axes
            if t0 is not None:
                xs, ys, zs = xs.window(t0, t1), ys.window(t0, t1), zs.window(t0, t1)
            n = min(xs.times.size, ys.times.size, zs.times.size)
            if n < 8:
                return None
            acc = np.column_stack([xs.values[:n], ys.values[:n], zs.values[:n]])
            times = np.asarray(xs.times[:n], dtype=float)
            fs = 1.0 / float(np.median(np.diff(times))) if times.size > 1 else 0.0
            return Samples(times, accel_to_respiration(acc, fs), name="resp")
        # No raw axes — fall back to a native respiration channel if present.
    resp = resolve_resp(session)
    if resp is None:
        return None
    return resp.window(t0, t1) if t0 is not None else resp


def _segment(sig: Samples | None):
    """Segment a respiration signal into ``(starts, ends, labels)`` arrays."""
    if sig is None or sig.times.size < 8:
        return None
    starts, ends, labels = segment_respiration(sig)
    return (starts, ends, labels) if starts.size else None


def apply_breath_phases(session: Session, params: _ParamsLike = None) -> Session:
    """Return a new ``Session`` with INH/EXH breath phases detected.

    The respiration signal is segmented into inhalation / exhalation intervals
    (stored as the ``breath`` :class:`~spectHR.session.Intervals`), which the
    per-epoch RSA, ``resp_freq`` and ``hf_resp_in_band`` metrics and the
    HR-series breathing overlay all read.  Requires R-peaks (``hrv``) and a
    respiration source; returns the session unchanged when either is missing or
    phases already exist.  Must run *after* :func:`apply_beat_detection`.

    With ``RespirationAnalysis.per_epoch`` enabled the respiration surrogate is
    rebuilt and segmented **within each analysis epoch** (the whole-recording
    ``"experiment"`` epoch is skipped).  For the accelerometer source this
    re-runs the PCA per epoch, so a posture change between epochs no longer
    corrupts a single global principal axis.
    """
    if session.breath is not None or session.hrv is None:
        return session
    view = _as_view(params)

    try:
        if view.rsp_per_epoch:
            phases = _detect_per_epoch(session, view)
        else:
            seg = _segment(_respiration_window(session, view, None, None))
            phases = (
                Intervals(starts=seg[0], ends=seg[1], labels=seg[2])
                if seg is not None else None
            )
    except Exception as exc:  # noqa: BLE001 — never abort a load
        logger.warning("Breath-phase detection failed: %s", exc)
        return session

    if phases is None:
        return session
    return Session(
        name=session.name,
        samples=session.samples,
        events=session.events,
        intervals={**session.intervals, "breath": phases},
        epochs=session.epochs,
    )


def recompute_breath_phases(session: Session, params: _ParamsLike = None) -> Session:
    """Drop any existing breath phases and re-detect with the current *params*.

    :func:`apply_breath_phases` is a no-op once a ``breath`` Intervals exists,
    so this is the entry point the UI uses when a respiration setting changes
    (``rsp_source`` / ``per_epoch``): it removes the stale phases and re-runs
    detection — e.g. switching to the accelerometer source rebuilds the INH/EXH
    phases from the (optionally per-epoch) accelerometer PCA.
    """
    if session.hrv is None:
        return session
    base = Session(
        name=session.name,
        samples=session.samples,
        events=session.events,
        intervals={k: v for k, v in session.intervals.items() if k != "breath"},
        epochs=session.epochs,
    )
    return apply_breath_phases(base, params)


def _detect_per_epoch(session: Session, view: WorkspaceView) -> "Intervals | None":
    """Segment respiration per analysis epoch and merge into one Intervals.

    Each active epoch other than the whole-recording ``"experiment"`` epoch is
    segmented on its own respiration window; the phases are concatenated and
    time-sorted.  Falls back to whole-recording detection when no such epoch
    exists (e.g. only ``"experiment"`` is present).
    """
    starts_l, ends_l, labels_l = [], [], []
    for name, ep in session.epochs.items():
        if name == "experiment" or not getattr(ep, "active", True):
            continue
        seg = _segment(_respiration_window(session, view, float(ep.start), float(ep.end)))
        if seg is not None:
            starts_l.append(seg[0]); ends_l.append(seg[1]); labels_l.append(seg[2])

    if not starts_l:
        seg = _segment(_respiration_window(session, view, None, None))
        return Intervals(starts=seg[0], ends=seg[1], labels=seg[2]) if seg else None

    starts = np.concatenate(starts_l)
    ends = np.concatenate(ends_l)
    labels = np.concatenate(labels_l)
    order = np.argsort(starts, kind="stable")
    return Intervals(starts=starts[order], ends=ends[order], labels=labels[order])
