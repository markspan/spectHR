"""
tests/conftest.py, shared fixtures and Events factories.

Every test module imports the factories from here so the synthetic
series stay consistent across the suite (same RNG seeds, same ramp
construction, same artefact-label conventions).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pytest

from spectHR.session import Events
from spectHR.analysis.psd import BandSpec, PsdMethod


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
# Events factories
# ---------------------------------------------------------------------------


def make_cs(ibi_ms: Sequence[float], labels: Sequence[str] | None = None) -> Events:
    """Build an :class:`Events` from a list of IBI values in ms.

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
    if labels is not None:
        lbl_arr = np.asarray(labels, dtype=object)
        if lbl_arr.size != times.size:
            raise ValueError(
                f"labels length {lbl_arr.size} != number of beats {times.size}"
            )
        return Events(times, lbl_arr)
    return Events(times, np.full(times.shape, "N", dtype=object))


def make_spectral_cs(
    dominant_freq_hz: float,
    *,
    duration_s: float = 250.0,
    mean_ibi_s: float = 0.8,
    mod_depth: float = 0.20,
    noise_std_rel: float = 0.005,
    seed: int = 42,
) -> Events:
    """Build an :class:`Events` whose IBI series carries a sinusoidal
    modulation at *dominant_freq_hz* Hz.
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
    ibi_s = np.clip(ibi_s, 0.3, 2.0)
    beat_times = np.concatenate([[0.0], np.cumsum(ibi_s)])
    return Events(beat_times, np.full(beat_times.shape, "N", dtype=object))


def make_two_sinusoid_cs(
    freq_a_hz: float,
    freq_b_hz: float,
    *,
    duration_s: float = 300.0,
    mean_ibi_s: float = 0.8,
    mod_depth_each: float = 0.10,
    noise_std_rel: float = 0.005,
    seed: int = 42,
) -> Events:
    """Build an :class:`Events` whose IBI modulation is the *sum* of
    two sinusoids at *freq_a_hz* and *freq_b_hz*.
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
    ibi_s = np.clip(ibi_s, 0.3, 2.0)
    beat_times = np.concatenate([[0.0], np.cumsum(ibi_s)])
    return Events(beat_times, np.full(beat_times.shape, "N", dtype=object))


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
    """A realistic ~200-second series with mild broadband HRV."""
    rng = np.random.default_rng(7)
    ibi_ms = 800.0 + rng.normal(0.0, 30.0, 250)
    ibi_ms = np.clip(ibi_ms, 400.0, 1500.0)
    return make_cs(ibi_ms)


@pytest.fixture
def lf_cs():
    """LF-dominant spectral series."""
    return make_spectral_cs(0.10)


@pytest.fixture
def hf_cs():
    """HF-dominant spectral series."""
    return make_spectral_cs(0.25)
