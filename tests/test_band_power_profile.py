"""
tests/test_band_power_profile.py, sliding-window spectral profiles.

Covers :func:`compute_band_power_profile`, the faithful port
of CARSPAN's ``RunProfileSommation`` (``T_AnaFunctions.pas`` 2888-3056).
The profile recomputes band power inside a window that slides along the
recording, so these tests check four things the README's "Profiles"
section promises:

1. Result structure and the window-enumeration arithmetic
   (``N = floor((T - W) / S) + 1`` and window-centre timestamps).
2. The static (non-adaptive) regression path, finite, non-negative
   band powers that still respect the band the signal sits in, for
   every PSD algorithm.
3. The NaN-sentinel contract, a window with fewer than four R-peaks
   leaves its whole output column NaN rather than dropping it.
4. The adaptive (respiration-tracked) band: tracking a known breathing
   frequency through a real respiration channel, the per-window
   ``psd_peak`` fallback when no channel is present, and the optional
   two-pass breath-frequency smoothing.

Pure compute-layer tests live in :mod:`tests.test_psd_compute`; the
whole-epoch band-power tests live in :mod:`tests.test_hrv_metrics`.
"""
from __future__ import annotations

import logging
import math
import types

import numpy as np
import pytest

from spectHR.session import Events, Intervals
from spectHR.analysis.psd import BandSpec, PsdMethod, ProfileResult
from spectHR.analysis.profile import compute_band_power_profile

from conftest import (   # imported via pytest rootdir/conftest.py
    WORKSPACE_BANDS,
    make_cs,
    make_spectral_cs,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _static_method(algorithm: str = "carspan") -> PsdMethod:
    """A :class:`PsdMethod` with the workspace bands, all static."""
    return PsdMethod(algorithm=algorithm, bands=dict(WORKSPACE_BANDS))


def _adaptive_hf_method(
    algorithm: str = "carspan",
    *,
    resp_low: float = 0.04,
    resp_high: float = 0.04,
) -> PsdMethod:
    """Workspace bands but with HF flagged ``respiration_band=True``.

    The HF band keeps its absolute ``[0.15, 0.40]`` edges (used for the
    whole-epoch band power and to bound the ``psd_peak`` search) and
    additionally carries the half-widths that position the adaptive
    window around the per-window breathing frequency.
    """
    bands = dict(WORKSPACE_BANDS)
    bands["HF"] = BandSpec(
        low=0.15,
        high=0.40,
        respiration_band=True,
        resp_low=resp_low,
        resp_high=resp_high,
    )
    return PsdMethod(algorithm=algorithm, bands=bands)


def _make_respiration(freq_hz: float, duration_s: float) -> Intervals:
    """Build an Intervals breathing at a constant *freq_hz*."""
    half_period = 1.0 / (2.0 * freq_hz)
    n_phases = int(duration_s / half_period) + 1
    edges = np.arange(n_phases + 1) * half_period
    starts = edges[:-1]
    ends = edges[1:]
    labels = np.array(
        ["INH" if i % 2 == 0 else "EXH" for i in range(n_phases)],
        dtype=object,
    )
    return Intervals(starts, ends, labels)


def _attach_respiration(cs: Events, freq_hz: float) -> Intervals:
    """Return a constant-frequency respiration Intervals for *cs*.

    Returns the Intervals; callers pass it as ``rsp_phases=`` to
    ``compute_band_power_profile`` rather than mutating the Events object.
    """
    duration_s = float(cs.times[-1] - cs.times[0])
    return _make_respiration(freq_hz, duration_s)


# ===========================================================================
# Result structure + window enumeration
# ===========================================================================


class TestProfileResultStructure:
    """``band_power_profile`` returns a well-formed :class:`ProfileResult`."""

    def test_returns_profileresult(self):
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=_static_method()
        )
        assert isinstance(res, ProfileResult)

    def test_array_shapes_consistent(self):
        method = _static_method()
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,window_s=40.0, step_s=10.0, psd_method=method)
        n_bands = len(method.bands)
        n_windows = res.timestamps.size
        assert res.band_power.shape == (n_bands, n_windows)
        assert res.band_names == list(method.bands.keys())

    def test_method_and_params_recorded(self):
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=_static_method("welch")
        )
        assert res.method == "welch"
        assert res.window_s == 40.0
        assert res.step_s == 10.0

    def test_unit_has_no_per_hz_suffix(self):
        """Profile values are band powers, so the unit must not carry the
        spectral-density ``/Hz`` suffix."""
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=_static_method()
        )
        assert "/Hz" not in res.unit and "/hz" not in res.unit

    def test_resp_freqs_none_without_adaptive_band(self):
        """No adaptive band configured → ``resp_freqs`` stays ``None``."""
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=_static_method()
        )
        assert res.resp_freqs is None


class TestProfileWindowEnumeration:
    """The sliding-window grid mirrors Delphi ``GetNrOfProfiles`` /
    ``GetProfileData``."""

    def test_window_count_matches_formula(self):
        window_s, step_s = 40.0, 10.0
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=window_s, step_s=step_s, psd_method=_static_method()
        )
        duration = float(cs.times[-1] - cs.times[0])
        expected = int((duration - window_s) / step_s) + 1
        assert res.timestamps.size == expected

    def test_timestamps_are_window_centres(self):
        window_s, step_s = 40.0, 10.0
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=window_s, step_s=step_s, psd_method=_static_method()
        )
        t0 = float(cs.times[0])
        expected = np.array(
            [t0 + i * step_s + window_s / 2.0 for i in range(res.timestamps.size)]
        )
        assert np.allclose(res.timestamps, expected)

    def test_consecutive_centres_step_apart(self):
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=_static_method()
        )
        diffs = np.diff(res.timestamps)
        assert np.allclose(diffs, 10.0)


# ===========================================================================
# Validation / error handling
# ===========================================================================


class TestProfileValidation:
    """Bad window/step parameters raise before any compute happens."""

    def test_nonpositive_window_raises(self):
        cs = make_spectral_cs(0.25)
        with pytest.raises(ValueError):
            compute_band_power_profile(cs,window_s=0.0, step_s=5.0)

    def test_nonpositive_step_raises(self):
        cs = make_spectral_cs(0.25)
        with pytest.raises(ValueError):
            compute_band_power_profile(cs,window_s=30.0, step_s=0.0)

    def test_step_not_smaller_than_window_raises(self):
        """Step >= window means no overlap → no profile."""
        cs = make_spectral_cs(0.25)
        with pytest.raises(ValueError):
            compute_band_power_profile(cs,window_s=30.0, step_s=30.0)

    def test_view_shorter_than_window_raises(self):
        """A recording shorter than one window cannot produce a profile."""
        # ~16 s of beats, asking for a 60 s window.
        cs = make_cs([800.0] * 20)
        with pytest.raises(ValueError):
            compute_band_power_profile(cs,window_s=60.0, step_s=5.0)

    def test_single_rpeak_raises(self):
        cs = Events(np.array([0.0]), np.full(1, "N", dtype=object))
        with pytest.raises(ValueError):
            compute_band_power_profile(cs,window_s=30.0, step_s=5.0)


# ===========================================================================
# Static (non-adaptive) regression path
# ===========================================================================


class TestProfileStaticBandPower:
    """The static path is the non-breaking regression baseline."""

    @pytest.mark.parametrize(
        "algorithm", ["carspan", "carspan_strict", "welch", "lombscargle"]
    )
    def test_band_power_finite_and_nonnegative(self, algorithm):
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=_static_method(algorithm)
        )
        finite = res.band_power[np.isfinite(res.band_power)]
        # Most windows of a clean 250 s series must produce a value.
        assert finite.size > 0
        assert np.all(finite >= 0.0)

    @pytest.mark.parametrize(
        "algorithm", ["carspan", "carspan_strict", "welch", "lombscargle"]
    )
    def test_hf_series_hf_dominates_lf(self, algorithm):
        """A 0.25 Hz (HF-dominant) series must show HF > LF power in the
        profile, for every PSD algorithm, confirming the per-window
        integration is reading real spectral content, not noise."""
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=_static_method(algorithm)
        )
        hf = res.band_power[res.band_names.index("HF")]
        lf = res.band_power[res.band_names.index("LF")]
        assert np.nanmedian(hf) > np.nanmedian(lf)

    def test_explicit_psd_method_is_used(self):
        """An explicit ``psd_method`` argument determines the algorithm."""
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=_static_method("welch")
        )
        assert res.method == "welch"


# ===========================================================================
# NaN-sentinel contract
# ===========================================================================


class TestProfileNaNWindow:
    """A window with fewer than four R-peaks leaves its column NaN so the
    output array stays rectangular and aligned with ``timestamps``."""

    def test_gap_window_is_all_nan(self):
        # Dense beats, then a 70 s stretch with no beats (one huge IBI),
        # then dense beats again. A 30 s window landing fully inside the
        # gap sees zero R-peaks → its whole column must be NaN, while
        # windows over the dense stretches stay finite.
        ibi_ms = [800.0] * 74 + [70000.0] + [800.0] * 74
        cs = make_cs(ibi_ms)
        res = compute_band_power_profile(cs,
            window_s=30.0, step_s=10.0, psd_method=_static_method()
        )

        col_all_nan = np.all(np.isnan(res.band_power), axis=0)
        col_all_finite = np.all(np.isfinite(res.band_power), axis=0)

        assert col_all_nan.any(), "expected at least one fully-NaN gap window"
        assert col_all_finite.any(), "expected at least one finite window"
        # timestamps are always populated, even for NaN windows.
        assert np.all(np.isfinite(res.timestamps))


# ===========================================================================
# Adaptive band, fallback when no respiration channel is present
# ===========================================================================


class TestProfileAdaptiveFallback:
    """With an adaptive band but no respiration channel, the profile
    falls back to the per-window ``psd_peak`` source (not straight to
    static edges)."""

    def test_respiration_channel_falls_back_to_psd_peak(self):
        """``respiration_channel`` with no channel loaded must produce the
        same result as asking for ``psd_peak`` directly."""
        method = _adaptive_hf_method(resp_low=0.05, resp_high=0.05)
        cs = make_spectral_cs(0.25)  # bare series, no _pd

        as_channel = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=method,
            adaptive_source="respiration_channel",
        )
        as_peak = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=method,
            adaptive_source="psd_peak",
        )
        assert np.allclose(as_channel.resp_freqs, as_peak.resp_freqs, equal_nan=True)
        assert np.allclose(as_channel.band_power, as_peak.band_power, equal_nan=True)

    def test_warning_logged_when_no_channel(self, caplog):
        method = _adaptive_hf_method()
        cs = make_spectral_cs(0.25)
        with caplog.at_level(logging.WARNING, logger="spectHR"):
            compute_band_power_profile(cs,
                window_s=40.0, step_s=10.0, psd_method=method,
                adaptive_source="respiration_channel",
            )
        assert "respiration" in caplog.text.lower()

    def test_psd_peak_resp_freqs_within_band(self):
        """The ``psd_peak`` source must report per-window frequencies that
        sit inside the HF search range it scanned."""
        method = _adaptive_hf_method(resp_low=0.05, resp_high=0.05)
        cs = make_spectral_cs(0.25)
        res = compute_band_power_profile(cs,
            window_s=40.0, step_s=10.0, psd_method=method,
            adaptive_source="psd_peak",
        )
        assert res.resp_freqs is not None
        finite = res.resp_freqs[np.isfinite(res.resp_freqs)]
        assert finite.size > 0
        hf = method.bands["HF"]
        assert np.all(finite >= hf.low - 1e-9)
        assert np.all(finite <= hf.high + 1e-9)


# ===========================================================================
# Adaptive band, tracking a real respiration channel
# ===========================================================================


class TestProfileAdaptiveRespiration:
    """With a respiration channel present, the adaptive band re-centres on
    the measured breathing frequency."""

    def test_tracks_known_breath_frequency(self):
        """A constant 0.25 Hz breathing channel must be recovered, window
        by window, to high precision (the construction makes the mean
        adjacent-phase cycle period exactly ``1 / 0.25`` s)."""
        method = _adaptive_hf_method()
        cs = make_spectral_cs(0.25)
        rsp = _attach_respiration(cs, freq_hz=0.25)

        res = compute_band_power_profile(cs,
            window_s=30.0, step_s=10.0, psd_method=method,
            rsp_phases=rsp,
            adaptive_source="respiration_channel",
        )
        assert res.resp_freqs is not None
        finite = res.resp_freqs[np.isfinite(res.resp_freqs)]
        assert finite.size > 0
        assert np.allclose(finite, 0.25, atol=1e-6)

    def test_adaptive_band_power_finite(self):
        """The HF band power must stay finite when the band tracks
        breathing, i.e. the shifted edges always land on grid."""
        method = _adaptive_hf_method()
        cs = make_spectral_cs(0.25)
        rsp = _attach_respiration(cs, freq_hz=0.25)

        res = compute_band_power_profile(cs,
            window_s=30.0, step_s=10.0, psd_method=method,
            rsp_phases=rsp,
            adaptive_source="respiration_channel",
        )
        hf = res.band_power[res.band_names.index("HF")]
        assert np.isfinite(hf).all()
        assert np.all(hf >= 0.0)

    def test_smooth_breath_freq_two_pass(self):
        """``smooth_breath_freq=True`` runs the two-pass path; smoothing a
        constant 0.25 Hz sequence leaves it at 0.25 Hz, and band power
        stays finite."""
        method = _adaptive_hf_method()
        cs = make_spectral_cs(0.25)
        rsp = _attach_respiration(cs, freq_hz=0.25)

        res = compute_band_power_profile(cs,
            window_s=30.0, step_s=10.0, psd_method=method,
            rsp_phases=rsp,
            adaptive_source="respiration_channel",
            smooth_breath_freq=True,
        )
        finite = res.resp_freqs[np.isfinite(res.resp_freqs)]
        assert finite.size > 0
        assert np.allclose(finite, 0.25, atol=1e-6)
        hf = res.band_power[res.band_names.index("HF")]
        assert np.isfinite(hf).all()

    def test_adaptive_differs_from_static(self):
        """Tracking breathing should give a different HF profile than the
        fixed-edge HF band (the adaptive window is narrower and moves)."""
        cs = make_spectral_cs(0.25)
        rsp = _attach_respiration(cs, freq_hz=0.25)

        adaptive = compute_band_power_profile(cs,
            window_s=30.0, step_s=10.0, psd_method=_adaptive_hf_method(),
            rsp_phases=rsp,
            adaptive_source="respiration_channel",
        )
        static = compute_band_power_profile(cs,
            window_s=30.0, step_s=10.0, psd_method=_static_method(),
        )
        hf_a = adaptive.band_power[adaptive.band_names.index("HF")]
        hf_s = static.band_power[static.band_names.index("HF")]
        assert not np.allclose(hf_a, hf_s, equal_nan=True)
