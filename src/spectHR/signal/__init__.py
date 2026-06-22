# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/signal/__init__.py
"""
spectHR.signal, low-level signal processing and feature detection.

The numeric primitives the data model and the analysis layer build on, one
module per concern:

* :mod:`spectHR.signal.filters`, Butterworth band/low/high-pass filtering.
* :mod:`spectHR.signal.decimation`, min/max decimation for fast display.
* :mod:`spectHR.signal.ecg`, ECG polarity detection.
* :mod:`spectHR.signal.rpeak`, R-peak detection.
* :mod:`spectHR.signal.ibi_classification`, rolling-window IBI artefact labels.
* :mod:`spectHR.signal.respiration`, breath-phase segmentation, accelerometer
  PCA surrogate, and mean breathing frequency.

The public functions are re-exported here so callers can ``from spectHR.signal
import detect_rpeaks`` without naming the submodule.  (Cross-cutting logging
lives in :mod:`spectHR.logger`, not here, it is not signal processing.)
"""
from spectHR.signal.decimation import decimate_minmax  # noqa: F401
from spectHR.signal.ecg import detect_ecg_polarity  # noqa: F401
from spectHR.signal.filters import butterworth_filter  # noqa: F401
from spectHR.signal.ibi_classification import classify_ibi  # noqa: F401
from spectHR.signal.respiration import (  # noqa: F401
    accel_to_respiration,
    mean_breath_frequency_hz,
    segment_respiration,
)
from spectHR.signal.rpeak import detect_rpeaks  # noqa: F401

__all__ = [
    "butterworth_filter",
    "decimate_minmax",
    "detect_ecg_polarity",
    "detect_rpeaks",
    "classify_ibi",
    "accel_to_respiration",
    "segment_respiration",
    "mean_breath_frequency_hz",
]
