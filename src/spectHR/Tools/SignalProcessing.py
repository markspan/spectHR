# spectHR/Tools/SignalProcessing.py
"""
Standalone signal-processing utilities.

This module contains filter design and application routines that operate on
raw signal arrays independently of any dataset or series class, making them
testable and reusable outside the ``TimeSeries`` context.

Public surface
--------------
butterworth_filter(values, srate, *, filter_type, cutoff, order) -> np.ndarray
    Design and apply a zero-phase Butterworth filter to a 1-D signal.

``TimeSeries.filter`` is a thin wrapper that calls this function and handles
in-place vs. copy semantics; existing call sites need no changes.
"""
from __future__ import annotations

import numpy as np
import scipy.signal as signal

from spectHR.Tools.Logger import logger


__all__ = ["butterworth_filter"]


def butterworth_filter(
    values: np.ndarray,
    srate: float,
    *,
    filter_type: str = "highpass",
    cutoff: float = 0.1,
    order: int | None = None,
) -> np.ndarray:
    """Design and apply a zero-phase Butterworth filter to a 1-D signal.

    Parameters
    ----------
    values : np.ndarray
        1-D signal to filter.
    srate : float
        Sampling rate of *values* in Hz.
    filter_type : {"lowpass", "highpass"}
        Type of Butterworth filter to apply.
    cutoff : float
        Cutoff frequency in Hz.  Must be strictly between 0 and the
        Nyquist frequency (``srate / 2``).
    order : int or None
        Filter order. When ``None`` (default), the order is estimated
        automatically via :func:`scipy.signal.buttord` with 1 dB
        pass-band ripple and 5 dB stop-band attenuation.

    Returns
    -------
    filtered : np.ndarray
        Filtered signal, same shape and dtype as *values*.

    Raises
    ------
    ValueError
        If *filter_type* is not ``"lowpass"`` or ``"highpass"``, or if
        *cutoff* is not between 0 and Nyquist.
    """
    values = np.asarray(values, dtype=float)

    if filter_type not in ("lowpass", "highpass"):
        raise ValueError(
            f"filter_type must be 'lowpass' or 'highpass', got {filter_type!r}."
        )

    nyq = 0.5 * float(srate)
    norm_cutoff = cutoff / nyq

    if not 0.0 < norm_cutoff < 1.0:
        raise ValueError(
            f"Cutoff frequency {cutoff} Hz is not between 0 and Nyquist "
            f"({nyq:.2f} Hz) for srate={srate:.2f} Hz."
        )

    # Filter design
    if order is None:
        passband = norm_cutoff * 1.1
        stopband = norm_cutoff / 1.5
        N, wn = signal.buttord(passband, stopband, gpass=1, gstop=5)
    else:
        N  = int(order)
        wn = norm_cutoff

    btype = "low" if filter_type == "lowpass" else "high"
    b, a  = signal.butter(N, wn, btype=btype, analog=False)

    logger.info(
        "butterworth_filter: %s Butterworth N=%d, cutoff=%.3f Hz, srate=%.2f Hz",
        btype, N, cutoff, srate,
    )

    return signal.filtfilt(b, a, values)
