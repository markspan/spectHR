"""
tests/test_transfer.py - transfer-function (CARSPAN ``RunTransfer``) port.

The transfer module is a Python port of CARSPAN's transfer-function
pipeline. These tests pin down three things:

1. The bit-correctness of the Pascal-faithful 3-point spectral smoother
   ``_smooth3`` (the WindowSize=3 branch of ``T_AnaFunctions.pas``
   ``AutoSpectrum`` / ``CrossSpectrum``). The Pascal right-edge policy
   is unusual - it replicates the rolling-buffer centre into the tail
   slot, which causes the last two input bins to drop out of the
   smoothed output. We hand-traced this and reproduce it here.
2. That ``_compute_dft`` (transfer.py) is wired to ``_dft`` in
   ``analysis.psd._carspan`` rather than duplicating the math.
3. End-to-end smoke tests for ``compute_transfer`` and
   ``compute_transfer_profile`` on synthetic respiration / IBI data so
   any future refactor that breaks the pipeline plumbing trips an
   alarm.

Pure-compute PSD tests live in :mod:`tests.test_psd_compute`; the
sliding-window band-power profile is covered by
:mod:`tests.test_band_power_profile`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pytest

from spectHR.analysis.transfer import (
    BandTransfer,
    TransferProfileResult,
    TransferResult,
    _compute_dft,
    _smooth3,
    compute_transfer,
    compute_transfer_profile,
)
from spectHR.analysis.psd._carspan import _dft
from spectHR.analysis.profile import _setup_profile_grid

from conftest import make_spectral_cs, make_cs


# ===========================================================================
# Pascal-faithful _smooth3 (T_AnaFunctions.pas:443-487, WindowSize=3)
# ===========================================================================


class TestSmooth3PascalFaithful:
    """Hand-traced from the Pascal source - these vectors are the
    ground truth the CARSPAN implementation produces, including the
    quirky right-edge replicate-centre policy that drops the last
    ``MaxPnt + 1 = 2`` input bins."""

    def test_hand_trace_n5(self):
        """Five-bin input - the canonical trace used while reviewing
        the Pascal source. Right-edge ``out[N-2..N-1]`` saturate at the
        third-from-last input value."""
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        expected = np.array([
            (1 + 2) / 2,            # out[0] left mirror
            (1 + 2 * 2 + 3) / 4,    # out[1] interior
            (2 + 3 * 3) / 4,        # out[2] first right-edge bin
            3.0,                    # out[3] right-edge replicate
            3.0,                    # out[4] right-edge replicate (last 2 x dropped)
        ])
        got = _smooth3(x)
        assert np.allclose(got, expected)

    def test_hand_trace_n4(self):
        """Four-bin input. With N <= 4 the interior range is empty so
        out[1] is the first right-edge bin (``(x[0] + 3*x[1]) / 4``)."""
        x = np.array([1.0, 2.0, 3.0, 4.0])
        expected = np.array([
            (1 + 2) / 2,
            (1 + 3 * 2) / 4,
            2.0,
            2.0,
        ])
        assert np.allclose(_smooth3(x), expected)

    def test_hand_trace_n3(self):
        """Three-bin input - the smallest size the smoother handles
        without the < 3 shortcut. The last input bin is dropped."""
        x = np.array([1.0, 2.0, 3.0])
        expected = np.array([
            (1 + 2) / 2,
            (1 + 3 * 2) / 4,
            2.0,
        ])
        assert np.allclose(_smooth3(x), expected)

    def test_hand_trace_n6(self):
        """Six-bin input - two interior bins survive (``out[1]`` and
        ``out[2]``), with the right-edge starting at ``out[3]``."""
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        expected = np.array([
            (1 + 2) / 2,
            (1 + 2 * 2 + 3) / 4,
            (2 + 2 * 3 + 4) / 4,
            (3 + 3 * 4) / 4,
            4.0,
            4.0,
        ])
        assert np.allclose(_smooth3(x), expected)

    def test_short_input_returned_as_copy(self):
        """A signal shorter than the kernel length is returned
        unchanged - the smoother is a no-op there."""
        for x in (np.array([]), np.array([1.0]), np.array([1.0, 2.0])):
            out = _smooth3(x)
            assert np.array_equal(out, x)
            # And a copy, not the same object - so callers can safely
            # mutate the result.
            if x.size > 0:
                assert out is not x

    def test_complex_input_handled(self):
        """The cross-spectrum is complex; ``_smooth3`` smooths real and
        imaginary parts simultaneously (a single Pascal-faithful kernel,
        not the two functions the previous implementation carried)."""
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0]) + 1j * np.array([10.0, 11.0, 12.0, 13.0, 14.0])
        got = _smooth3(x)
        assert got.dtype == np.complex128
        # The real and imaginary projections must match the Pascal trace
        # applied independently to each component.
        assert np.allclose(got.real, _smooth3(x.real))
        assert np.allclose(got.imag, _smooth3(x.imag))

    def test_returns_dtype_matches_input(self):
        """Real input -> float64 output. Complex input -> complex128.
        Keeps the auto-spectrum branch from being silently promoted to
        complex (which would slow it down)."""
        assert _smooth3(np.array([1.0, 2.0, 3.0])).dtype == np.float64
        assert _smooth3(np.array([1.0, 2.0, 3.0]) + 0j).dtype == np.complex128

    def test_constant_signal_is_fixed_point(self):
        """A constant signal must come out constant - any boundary policy
        that preserves the kernel sum (which Pascal's normalisation does)
        gets this for free, but verify explicitly."""
        x = np.full(10, 3.5)
        assert np.allclose(_smooth3(x), x)


# ===========================================================================
# _compute_dft consolidated against analysis.psd._carspan._dft
# ===========================================================================


class TestComputeDftDelegatesToCarspan:
    """``_compute_dft`` is now a thin ``re + 1j * im`` wrapper around
    ``_dft`` - so the two must agree bit-exactly on every call."""

    def test_matches_dft_real_imag(self):
        rng = np.random.default_rng(0)
        freqs = np.linspace(0.01, 0.5, 64)
        times = np.cumsum(rng.uniform(0.7, 0.9, 200))
        weights = rng.normal(0.0, 1.0, 200)

        complex_dft = _compute_dft(freqs, times, weights)
        re, im = _dft(freqs, times, weights)

        assert np.array_equal(complex_dft.real, re)
        assert np.array_equal(complex_dft.imag, im)

    def test_returns_complex_dtype(self):
        freqs = np.array([0.1, 0.2])
        times = np.array([0.0, 1.0, 2.0])
        weights = np.array([1.0, 2.0, 3.0])
        out = _compute_dft(freqs, times, weights)
        assert np.iscomplexobj(out)


# ===========================================================================
# _setup_profile_grid validation contract (shared with profile.py)
# ===========================================================================


class TestSetupProfileGrid:
    """The validation helper used by both ``compute_band_power_profile``
    and ``compute_transfer_profile``. The error messages are surfaced
    to end users, so we pin the failure modes."""

    @staticmethod
    def _series(n_beats=100, mean_ibi_s=0.8):
        # A bare object with a ``.times`` ndarray is the minimum the
        # helper looks at.
        @dataclass
        class _S:
            times: np.ndarray
        return _S(times=np.arange(n_beats, dtype=float) * mean_ibi_s)

    def test_returns_n_windows_timestamps_t0(self):
        s = self._series(n_beats=200)        # ~159 s of beats
        n, ts, t0 = _setup_profile_grid(s, window_s=40.0, step_s=10.0)
        # n_windows = floor((duration - W) / S) + 1
        duration = float(s.times[-1] - s.times[0])
        assert n == int((duration - 40.0) / 10.0) + 1
        assert ts.shape == (n,)
        # window centres
        assert np.allclose(ts, t0 + np.arange(n) * 10.0 + 20.0)
        assert t0 == float(s.times[0])

    def test_step_not_smaller_than_window_raises(self):
        s = self._series()
        with pytest.raises(ValueError, match="strictly smaller"):
            _setup_profile_grid(s, window_s=30.0, step_s=30.0)

    def test_nonpositive_raises(self):
        s = self._series()
        with pytest.raises(ValueError, match="must both be > 0"):
            _setup_profile_grid(s, window_s=0.0, step_s=5.0)
        with pytest.raises(ValueError, match="must both be > 0"):
            _setup_profile_grid(s, window_s=30.0, step_s=-1.0)

    def test_too_few_rpeaks_raises_with_context_label(self):
        # Pass a context label so the error message points the user at
        # the right pipeline.
        s = self._series(n_beats=1)
        with pytest.raises(ValueError, match="transfer profile"):
            _setup_profile_grid(
                s, window_s=30.0, step_s=5.0, context="transfer profile",
            )

    def test_view_shorter_than_window_raises(self):
        s = self._series(n_beats=10)         # ~7 s of beats
        with pytest.raises(ValueError, match="too short"):
            _setup_profile_grid(s, window_s=60.0, step_s=5.0)


# ===========================================================================
# Helpers for the end-to-end smoke tests
# ===========================================================================


@dataclass
class _RespTimeSeries:
    """Minimal stand-in for a continuous respiration TimeSeries.

    ``compute_transfer`` only reads ``.times`` and ``.values`` to feed
    ``np.interp``, so this is enough.
    """
    times: np.ndarray
    values: np.ndarray


def _coupled_respiration(
    rp_times: np.ndarray,
    *,
    freq_hz: float = 0.25,
    fs: float = 20.0,
    phase_offset: float = 0.0,
) -> _RespTimeSeries:
    """Build a continuous sinusoidal 'respiration' channel that lives over
    the same time range as the cardiac series.

    The IBI series fed in to :func:`compute_transfer` carries an HF
    modulation at the same frequency, so the transfer function is
    expected to show coherent coupling around that frequency.
    """
    t_start, t_end = float(rp_times[0]), float(rp_times[-1])
    times  = np.arange(t_start, t_end + 1.0 / fs, 1.0 / fs)
    values = np.sin(2.0 * np.pi * freq_hz * times + phase_offset)
    return _RespTimeSeries(times=times, values=values)


# ===========================================================================
# compute_transfer - single-epoch
# ===========================================================================


class TestComputeTransferSingleEpoch:
    """End-to-end shape / dtype contract for the single-epoch path."""

    def test_returns_transferresult(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        res = compute_transfer(cs, rsp)
        assert isinstance(res, TransferResult)
        assert res.method == "carspan_transfer"

    def test_arrays_aligned(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        res = compute_transfer(cs, rsp)
        n = res.freqs.size
        assert res.modulus.shape         == (n,)
        assert res.phase_wrapped.shape   == (n,)
        assert res.phase_unwrapped.shape == (n,)
        assert res.coherence.shape       == (n,)

    def test_coherence_is_unity_unsmoothed(self):
        """Without spectral smoothing each frequency bin has one
        realisation of the cross- and auto-spectra, so |C|^2 = 1 by
        construction. This catches accidental amplitude regressions."""
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        res = compute_transfer(cs, rsp, smooth=False)
        # Allow a few ULPs from the divisions.
        assert np.all(np.isfinite(res.coherence))
        assert np.allclose(res.coherence, 1.0, atol=1e-9)

    def test_smoothing_drops_coherence_below_one(self):
        """The 3-point smoother averages neighbouring spectra, which
        breaks the per-bin "one realisation" property and yields
        sub-unity coherence at most bins."""
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        res = compute_transfer(cs, rsp, smooth=True)
        assert np.median(res.coherence) < 1.0

    def test_phase_wrapped_within_pi(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        res = compute_transfer(cs, rsp)
        assert np.all(res.phase_wrapped >= -np.pi - 1e-9)
        assert np.all(res.phase_wrapped <=  np.pi + 1e-9)

    def test_band_results_returned_when_bands_passed(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        bands = {"LF": (0.04, 0.15), "HF": (0.15, 0.40)}
        res = compute_transfer(cs, rsp, bands=bands)
        assert res.band_results is not None
        assert set(res.band_results.keys()) == {"LF", "HF"}
        for bt in res.band_results.values():
            assert isinstance(bt, BandTransfer)
            assert bt.n_points > 0

    def test_band_results_none_when_no_bands(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        res = compute_transfer(cs, rsp)        # no bands kwarg
        assert res.band_results is None

    def test_too_few_rpeaks_raises(self):
        cs = make_cs([800.0, 800.0])           # 3 R-peaks -> need >= 4
        rsp = _coupled_respiration(cs.times)
        with pytest.raises(ValueError, match="at least 4 clean"):
            compute_transfer(cs, rsp)


# ===========================================================================
# compute_transfer_profile - sliding-window
# ===========================================================================


class TestComputeTransferProfile:
    """End-to-end shape + plumbing for the sliding-window path."""

    def test_returns_transferprofileresult(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        bands = {"LF": (0.04, 0.15), "HF": (0.15, 0.40)}
        res = compute_transfer_profile(
            cs, rsp, bands=bands, window_s=40.0, step_s=10.0,
        )
        assert isinstance(res, TransferProfileResult)
        assert res.method == "carspan_transfer"

    def test_array_shapes(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        bands = {"LF": (0.04, 0.15), "HF": (0.15, 0.40)}
        res = compute_transfer_profile(
            cs, rsp, bands=bands, window_s=40.0, step_s=10.0,
        )
        n_windows = res.timestamps.size
        for arr in (res.modulus, res.phase, res.phase_unwrapped,
                    res.weighted_coherence):
            assert arr.shape == (len(bands), n_windows)
        assert res.n_coherent.shape == (len(bands), n_windows)
        assert res.n_coherent.dtype.kind == "i"

    def test_timestamps_are_window_centres(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        bands = {"HF": (0.15, 0.40)}
        res = compute_transfer_profile(
            cs, rsp, bands=bands, window_s=30.0, step_s=10.0,
        )
        t0 = float(cs.times[0])
        expected = t0 + np.arange(res.timestamps.size) * 10.0 + 15.0
        assert np.allclose(res.timestamps, expected)

    def test_weighted_coherence_within_unit_interval(self):
        cs = make_spectral_cs(0.25, duration_s=300.0)
        rsp = _coupled_respiration(cs.times)
        bands = {"HF": (0.15, 0.40)}
        res = compute_transfer_profile(
            cs, rsp, bands=bands, window_s=40.0, step_s=10.0,
        )
        coh = res.weighted_coherence[res.band_names.index("HF")]
        finite = coh[np.isfinite(coh)]
        assert finite.size > 0
        assert np.all(finite >= -1e-9)
        assert np.all(finite <=  1.0 + 1e-9)

    def test_empty_bands_raises(self):
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        with pytest.raises(ValueError, match="bands must not be empty"):
            compute_transfer_profile(
                cs, rsp, bands={}, window_s=40.0, step_s=10.0,
            )

    def test_validation_delegated_to_setup_helper(self):
        """Step / window validation now flows through
        ``_setup_profile_grid`` - confirm the same error messages reach
        the user from this entry point."""
        cs = make_spectral_cs(0.25, duration_s=200.0)
        rsp = _coupled_respiration(cs.times)
        bands = {"HF": (0.15, 0.40)}
        with pytest.raises(ValueError, match="strictly smaller"):
            compute_transfer_profile(
                cs, rsp, bands=bands, window_s=30.0, step_s=30.0,
            )

    def test_sparse_window_yields_nan_column(self):
        """A window with fewer than 4 R-peaks should leave its column
        as NaN (modulus / phase / coherence) and 0 for n_coherent -
        same NaN-sentinel contract as the band-power profile."""
        # Long gap in the middle (one huge "IBI" of 70 s) - a 30 s
        # window landing inside that gap sees zero R-peaks.
        ibi_ms = [800.0] * 74 + [70000.0] + [800.0] * 74
        cs = make_cs(ibi_ms)
        rsp = _coupled_respiration(cs.times)
        bands = {"HF": (0.15, 0.40)}
        res = compute_transfer_profile(
            cs, rsp, bands=bands, window_s=30.0, step_s=10.0,
        )
        mod_nan_cols  = np.all(np.isnan(res.modulus), axis=0)
        mod_finite    = np.all(np.isfinite(res.modulus), axis=0)
        assert mod_nan_cols.any(),    "expected at least one all-NaN gap column"
        assert mod_finite.any(),      "expected at least one finite column"
        # And timestamps stay populated regardless.
        assert np.all(np.isfinite(res.timestamps))
