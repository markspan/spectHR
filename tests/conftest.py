"""
tests/conftest.py — shared fixtures and CardioSeries factories.

Every test module imports the factories from here so the synthetic
series stay consistent across the suite (same RNG seeds, same ramp
construction, same artefact-label conventions).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pytest

from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Series.CardioMetricsMixin import (
    BandSpec,
    PsdMethod,
)


# ---------------------------------------------------------------------------
# Bands that match the spectUI workspace defaults
# ---------------------------------------------------------------------------

WORKSPACE_BANDS = {
    "FullRange": BandSpec(low=0.02, high=0.50),
    "VLF":       BandSpec(low=0.02, high=0.06),
    "LF":        BandSpec(low=0.07, high=0.14),
    "HF":        BandSpec(low=0.15, high=0.40),
}


# ---------------------------------------------------------------------------
# CardioSeries factories
# ---------------------------------------------------------------------------


def make_cs(ibi_ms: Sequence[float], labels: Sequence[str] | None = None) -> CardioSeries:
    """Build a :class:`CardioSeries` from a list of IBI values in ms.

    Parameters
    ----------
    ibi_ms : sequence of float
        Inter-beat intervals in milliseconds. ``N`` intervals produce
        ``N + 1`` R-peak timestamps starting at ``t = 0``.
    labels : sequence of str, optional
        Per-beat label array, length ``N + 1``. Defaults to all ``"N"``.
    """
    ibi_ms_arr = np.asarray(ibi_ms, dtype=float)
    times = np.concatenate([[0.0], np.cumsum(ibi_ms_arr / 1000.0)])
    cs = CardioSeries(times)
    if labels is not None:
        if len(labels) != cs.labels.size:
            raise ValueError(
                f"labels length {len(labels)} != number of beats {cs.labels.size}"
            )
        cs.labels[:] = np.asarray(labels, dtype=object)
    return cs


def make_spectral_cs(
    dominant_freq_hz: float,
    *,
    duration_s: float = 250.0,
    mean_ibi_s: float = 0.8,
    mod_depth: float = 0.20,
    noise_std_rel: float = 0.005,
    seed: int = 42,
) -> CardioSeries:
    """Build a :class:`CardioSeries` whose IBI series carries a sinusoidal
    modulation at *dominant_freq_hz* Hz.

    The recording is approximately ``duration_s / mean_ibi_s`` beats — long
    enough for reliable spectral estimation in the standard HRV bands.

    Parameters
    ----------
    dominant_freq_hz : float
        Target frequency (Hz) of the sinusoidal IBI modulation.
    duration_s : float
        Approximate total recording length, in seconds.
    mean_ibi_s : float
        Mean IBI in seconds (default 0.8 s ≈ 75 bpm).
    mod_depth : float
        Fractional modulation amplitude relative to ``mean_ibi_s``.
    noise_std_rel : float
        Additive white-noise floor as a fraction of ``mean_ibi_s``.
    seed : int
        Random-number seed for reproducibility.
    """
    rng = np.random.default_rng(seed)
    n_beats = int(duration_s / mean_ibi_s) + 1
    approx_times = np.arange(n_beats) * mean_ibi_s
    noise = rng.normal(0.0, noise_std_rel * mean_ibi_s, n_beats - 1)
    ibi_s = (
        mean_ibi_s
        + mod_depth * mean_ibi_s
        * np.sin(2.0 * np.pi * dominant_freq_hz * approx_times[:-1])
        + noise
    )
    ibi_s = np.clip(ibi_s, 0.3, 2.0)  # physiological bounds
    beat_times = np.concatenate([[0.0], np.cumsum(ibi_s)])
    return CardioSeries(beat_times)


def make_two_sinusoid_cs(
    freq_a_hz: float,
    freq_b_hz: float,
    *,
    duration_s: float = 300.0,
    mean_ibi_s: float = 0.8,
    mod_depth_each: float = 0.10,
    noise_std_rel: float = 0.005,
    seed: int = 42,
) -> CardioSeries:
    """Build a :class:`CardioSeries` whose IBI modulation is the *sum* of
    two sinusoids at *freq_a_hz* and *freq_b_hz*.

    The IBI series is

        ``ibi(t) = mean + mod_depth · mean · [sin(2π·f_a·t) + sin(2π·f_b·t)] + noise``

    so each tone contributes a fractional amplitude ``mod_depth_each``
    of the mean IBI. Use it to verify that PSD estimators recover
    *both* peaks simultaneously (e.g. LF + HF).

    Parameters
    ----------
    freq_a_hz, freq_b_hz : float
        Target frequencies (Hz) of the two sinusoidal IBI modulations.
    duration_s : float
        Approximate total recording length, in seconds. Defaults to
        300 s — long enough to resolve the LF band cleanly.
    mean_ibi_s : float
        Mean IBI in seconds (default 0.8 s ≈ 75 bpm).
    mod_depth_each : float
        Fractional modulation amplitude per tone, relative to ``mean_ibi_s``.
    noise_std_rel : float
        Additive white-noise floor as a fraction of ``mean_ibi_s``.
    seed : int
        Random-number seed for reproducibility.
    """
    rng = np.random.default_rng(seed)
    n_beats = int(duration_s / mean_ibi_s) + 1
    approx_times = np.arange(n_beats) * mean_ibi_s
    noise = rng.normal(0.0, noise_std_rel * mean_ibi_s, n_beats - 1)
    ibi_s = (
        mean_ibi_s
        + mod_depth_each * mean_ibi_s * np.sin(2.0 * np.pi * freq_a_hz * approx_times[:-1])
        + mod_depth_each * mean_ibi_s * np.sin(2.0 * np.pi * freq_b_hz * approx_times[:-1])
        + noise
    )
    ibi_s = np.clip(ibi_s, 0.3, 2.0)  # physiological bounds
    beat_times = np.concatenate([[0.0], np.cumsum(ibi_s)])
    return CardioSeries(beat_times)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_bands():
    """Workspace-default band table (as ``Dict[str, BandSpec]``)."""
    return dict(WORKSPACE_BANDS)


@pytest.fixture
def default_method(workspace_bands):
    """A default :class:`PsdMethod` using the workspace bands and CARSPAN
    as algorithm. The frozen dataclass is safe to share."""
    return PsdMethod(algorithm="carspan", bands=workspace_bands)


@pytest.fixture
def typical_cs():
    """A realistic ~200-second series with mild broadband HRV.

    Pre-configured with the default ``PsdMethod`` so all frequency
    metrics work out of the box.
    """
    rng = np.random.default_rng(7)
    ibi_ms = 800.0 + rng.normal(0.0, 30.0, 250)
    ibi_ms = np.clip(ibi_ms, 400.0, 1500.0)
    cs = make_cs(ibi_ms)
    cs.psd_method = PsdMethod(algorithm="carspan", bands=dict(WORKSPACE_BANDS))
    return cs


@pytest.fixture
def lf_cs():
    """LF-dominant spectral series, pre-configured for PSD."""
    cs = make_spectral_cs(0.10)
    cs.psd_method = PsdMethod(algorithm="carspan", bands=dict(WORKSPACE_BANDS))
    return cs


@pytest.fixture
def hf_cs():
    """HF-dominant spectral series, pre-configured for PSD."""
    cs = make_spectral_cs(0.25)
    cs.psd_method = PsdMethod(algorithm="carspan", bands=dict(WORKSPACE_BANDS))
    return cs
