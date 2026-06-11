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
from spectHR.session import Events, Samples, Session
from spectHR.Tools.ECGProcessing import detect_ecg_polarity
from spectHR.Tools.Logger import logger

__all__ = [
    "resolve_ecg",
    "resolve_resp",
    "filter_ecg",
    "apply_ecg_polarity",
    "apply_beat_detection",
    "apply_bp_calibration",
    "apply_rsp_source",
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


def _first_with_prefix(session: Session, prefixes: tuple[str, ...]) -> Samples | None:
    """First sample channel whose key starts (case-insensitively) with a prefix."""
    for key, sig in session.samples.items():
        if key.lower().startswith(prefixes):
            return sig
    return None


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

    Reads ``rsp_source`` from the analysis parameters and copies the
    appropriate channel to ``session.samples["resp"]``.

    * ``"icg"`` — uses the ``icg`` channel if present (thoracic impedance).
    * ``"accelerometer"`` — uses ``accel_rsp`` if present (PCA surrogate).

    When the requested source is not available the session is returned
    unchanged.
    """
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
