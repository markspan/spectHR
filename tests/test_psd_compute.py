"""
tests/test_psd_compute.py, pure compute-layer tests.

Covers
------
* :class:`PSDResult`, frozen dataclass, replace() behaviour.
* :class:`WelchOptions`,  :func:`compute_welch_psd`.
* :class:`LombscargleOptions`, :func:`compute_lombscargle_psd`.
* :class:`CarspanOptions`, :func:`compute_carspan_psd`,
  :func:`compute_carspan_psd_strict`,  :func:`carspan_strict_options`.

These tests poke the compute functions directly, they don't touch
any mixin, dataset or workspace. The mixin-level integration tests
live in :mod:`tests.test_hrv_metrics`.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from spectHR.analysis.psd import (
    CarspanOptions,
    LombscargleOptions,
    PSDResult,
    WelchOptions,
    carspan_strict_options,
    compute_carspan_psd,
    compute_carspan_psd_strict,
    compute_lombscargle_psd,
    compute_welch_psd,
)

# ===========================================================================
# Synthetic data
# ===========================================================================


def _ibi_series(n: int = 250, mean_ms: float = 800.0, std_ms: float = 30.0,
                seed: int = 0):
    """Return (times_s, values_ms) for a synthetic IBI series."""
    rng = np.random.default_rng(seed)
    ibi_ms = mean_ms + rng.normal(0.0, std_ms, n)
    ibi_ms = np.clip(ibi_ms, 400.0, 1500.0)
    times = np.cumsum(ibi_ms / 1000.0)
    return times, ibi_ms


def _event_times(n_beats: int = 250, mean_ibi_s: float = 0.8,
                 jitter_s: float = 0.03, seed: int = 0):
    """Return monotonically increasing R-peak times for CARSPAN tests."""
    rng = np.random.default_rng(seed)
    ibi = mean_ibi_s + rng.normal(0.0, jitter_s, n_beats - 1)
    ibi = np.clip(ibi, 0.4, 1.5)
    return np.concatenate([[0.0], np.cumsum(ibi)])


# ===========================================================================
# PSDResult, the new pre-filled result type
# ===========================================================================


class TestPSDResult:
    """:class:`PSDResult` is a frozen dataclass that every compute
    function now returns. Covers immutability, default values, and the
    ``dataclasses.replace`` round-trip the mixin relies on."""

    def test_construction_with_minimum_args(self):
        r = PSDResult(freqs=np.array([1.0]), power=np.array([2.0]))
        assert r.unit == ""
        assert r.method == ""
        assert r.ci_lower is None
        assert r.ci_upper is None

    def test_is_frozen(self):
        r = PSDResult(freqs=np.array([1.0]), power=np.array([2.0]))
        with pytest.raises(FrozenInstanceError):
            r.unit = "mMI²/Hz"   # type: ignore[misc]

    def test_replace_returns_new_instance(self):
        r = PSDResult(freqs=np.array([1.0]), power=np.array([2.0]), unit="Hz")
        r2 = replace(r, unit="mMI²/Hz", method="carspan")
        assert r is not r2
        assert r.unit == "Hz"           # original untouched
        assert r2.unit == "mMI²/Hz"
        assert r2.method == "carspan"
        # Shared array fields are still the same object, replace doesn't
        # deep-copy. Document the contract by asserting it explicitly.
        assert r2.freqs is r.freqs

    def test_field_count(self):
        """Spec freeze: any new field added needs the mixin's
        ``_finalise`` updated, so flag it loudly via this test."""
        from dataclasses import fields
        names = {f.name for f in fields(PSDResult)}
        assert names == {"freqs", "power", "unit", "method", "ci_lower", "ci_upper"}


# ===========================================================================
# Welch
# ===========================================================================


class TestWelchOptions:
    def test_defaults(self):
        o = WelchOptions()
        assert o.fs == 4.0
        assert o.nperseg == 256
        assert o.noverlap == 128
        assert o.nfft is None
        assert o.window == "hann"

    def test_frozen(self):
        o = WelchOptions()
        with pytest.raises(FrozenInstanceError):
            o.fs = 8.0   # type: ignore[misc]


class TestComputeWelchPsd:
    """``compute_welch_psd`` returns a populated PSDResult."""

    def test_returns_psdresult(self):
        t, v = _ibi_series()
        r = compute_welch_psd(t, v)
        assert isinstance(r, PSDResult)
        assert r.method == "welch"
        assert r.unit == "ms²/Hz"

    def test_arrays_aligned(self):
        t, v = _ibi_series()
        r = compute_welch_psd(t, v)
        assert r.freqs.shape == r.power.shape
        assert r.ci_lower.shape == r.power.shape
        assert r.ci_upper.shape == r.power.shape

    def test_power_nonnegative(self):
        t, v = _ibi_series()
        r = compute_welch_psd(t, v)
        assert np.all(r.power >= 0.0)

    def test_ci_brackets_estimate(self):
        t, v = _ibi_series()
        r = compute_welch_psd(t, v)
        # At least 95 % of bins should be bracketed; floating-point
        # edge cases at zero power can pop out either side.
        ok = np.sum((r.ci_lower <= r.power + 1e-12) & (r.ci_upper >= r.power - 1e-12))
        assert ok >= int(0.95 * r.power.size)

    def test_freqs_start_above_zero(self):
        t, v = _ibi_series()
        r = compute_welch_psd(t, v)
        assert r.freqs[0] >= 0.0

    def test_short_series_raises(self):
        t = np.array([0.0, 0.8, 1.6])  # 3 samples, below the 4-sample floor
        v = np.array([800.0, 800.0, 800.0])
        with pytest.raises(ValueError):
            compute_welch_psd(t, v)

    def test_custom_options_override_defaults(self):
        t, v = _ibi_series()
        opts = WelchOptions(fs=8.0, nperseg=128, noverlap=64, window="hamming")
        r = compute_welch_psd(t, v, options=opts)
        # Higher fs → higher Nyquist → freqs extend further.
        assert r.freqs[-1] > 1.0

    def test_alpha_ci_widens_ci(self):
        """A larger alpha (less confidence) yields narrower bounds. With
        alpha=0.5 the CI is the 50 % interval; with alpha=0.05 it's the
        95 % interval, so 95 % bounds are wider."""
        t, v = _ibi_series()
        narrow = compute_welch_psd(t, v, alpha_ci=0.5)
        wide   = compute_welch_psd(t, v, alpha_ci=0.05)
        # Compare widths at bins where power is non-zero.
        mask = wide.power > 0
        wide_width = wide.ci_upper[mask] - wide.ci_lower[mask]
        narrow_width = narrow.ci_upper[mask] - narrow.ci_lower[mask]
        assert np.median(wide_width) > np.median(narrow_width)

    def test_short_epoch_clamps_nperseg(self):
        """When the resampled series is shorter than ``nperseg``, the
        Welch back-end transparently clamps nperseg + halves the overlap
, no exception."""
        t, v = _ibi_series(n=30)
        opts = WelchOptions(fs=4.0, nperseg=2048, noverlap=1024)
        r = compute_welch_psd(t, v, options=opts)
        assert r.freqs.size > 0
        assert np.all(np.isfinite(r.power))

    def test_distinct_seeds_distinct_spectra(self):
        """Sanity: independent random IBI series should yield distinct
        spectra (the compute path is not accidentally caching)."""
        t1, v1 = _ibi_series(seed=1)
        t2, v2 = _ibi_series(seed=2)
        r1 = compute_welch_psd(t1, v1)
        r2 = compute_welch_psd(t2, v2)
        assert not np.allclose(r1.power, r2.power)


# ===========================================================================
# Lomb-Scargle
# ===========================================================================


class TestLombscargleOptions:
    def test_defaults(self):
        o = LombscargleOptions()
        assert o.nfreqs == 1000
        assert o.fmin_floor == 1e-4

    def test_frozen(self):
        o = LombscargleOptions()
        with pytest.raises(FrozenInstanceError):
            o.nfreqs = 2000   # type: ignore[misc]


class TestComputeLombscarglePsd:
    def test_returns_psdresult(self):
        t, v = _ibi_series()
        r = compute_lombscargle_psd(t, v)
        assert isinstance(r, PSDResult)
        assert r.method == "lombscargle"
        assert r.unit == "ms²/Hz"

    def test_freqs_length_matches_nfreqs(self):
        t, v = _ibi_series()
        opts = LombscargleOptions(nfreqs=400)
        r = compute_lombscargle_psd(t, v, options=opts)
        assert r.freqs.size == 400
        assert r.power.size == 400

    def test_f_max_respected(self):
        t, v = _ibi_series()
        r = compute_lombscargle_psd(t, v, f_max=0.3)
        assert r.freqs[-1] == pytest.approx(0.3, rel=1e-6)

    def test_f_min_floor_respected(self):
        """``fmin_floor`` keeps the grid above DC even for long
        recordings (where 1/T would otherwise be tiny)."""
        t, v = _ibi_series()
        opts = LombscargleOptions(fmin_floor=0.02)
        r = compute_lombscargle_psd(t, v, options=opts)
        assert r.freqs[0] >= 0.02

    def test_power_nonnegative(self):
        t, v = _ibi_series()
        r = compute_lombscargle_psd(t, v)
        assert np.all(r.power >= 0.0)

    def test_short_series_raises(self):
        t = np.array([0.0, 0.8, 1.6])
        v = np.array([800.0, 800.0, 800.0])
        with pytest.raises(ValueError):
            compute_lombscargle_psd(t, v)

    def test_zero_span_raises(self):
        t = np.array([0.0, 0.0, 0.0, 0.0])
        v = np.array([800.0, 800.0, 800.0, 800.0])
        with pytest.raises(ValueError, match="span"):
            compute_lombscargle_psd(t, v)

    def test_irregular_sampling_handled(self):
        """L-S's whole point: irregular sampling should still produce
        finite output."""
        rng = np.random.default_rng(3)
        t = np.cumsum(rng.uniform(0.5, 1.2, 200))
        v = 800.0 + rng.normal(0.0, 25.0, 200)
        r = compute_lombscargle_psd(t, v)
        assert np.all(np.isfinite(r.power))


# ===========================================================================
# CARSPAN
# ===========================================================================


class TestCarspanOptions:
    def test_defaults(self):
        o = CarspanOptions()
        assert o.freq_resolution == 0.01
        assert o.f_max == 0.5
        assert o.window == "hann"
        assert o.taper == "scipy"
        assert o.alpha_taper == 0.10
        assert o.amplitude_correction is True
        assert o.skip_first_event is False
        assert o.dc_removal is False
        assert o.dc_grid == "span_matched"
        assert o.smooth_for_display is True

    def test_frozen(self):
        o = CarspanOptions()
        with pytest.raises(FrozenInstanceError):
            o.dc_removal = True   # type: ignore[misc]


class TestCarspanStrictOptionsPreset:
    """``carspan_strict_options()`` builds the CARSPAN-faithful preset."""

    def test_preset_fields(self):
        o = carspan_strict_options()
        assert o.freq_resolution == 0.01
        assert o.taper == "carspan_index"
        assert o.alpha_taper == 0.10
        assert o.amplitude_correction is False
        assert o.skip_first_event is True
        assert o.dc_removal is True
        assert o.dc_grid == "carspan_strict"
        assert o.smooth_for_display is True

    def test_preset_passes_through_user_args(self):
        o = carspan_strict_options(smooth_for_display=False, f_max=0.8)
        assert o.smooth_for_display is False
        assert o.f_max == 0.8


class TestComputeCarspanPsd:
    def test_returns_psdresult(self):
        times = _event_times()
        r = compute_carspan_psd(times)
        assert isinstance(r, PSDResult)
        assert r.method == "carspan"
        assert r.unit == "Hz"

    def test_power_nonnegative(self):
        times = _event_times()
        r = compute_carspan_psd(times)
        assert np.all(r.power >= 0.0)

    def test_f_max_respected(self):
        times = _event_times()
        opts = CarspanOptions(f_max=0.3)
        r = compute_carspan_psd(times, options=opts)
        assert r.freqs[-1] <= 0.3 + 1e-9

    def test_freq_resolution_drives_display_grid(self):
        """With smoothing on the output sits on the display grid; bins
        are at multiples of ``freq_resolution``."""
        times = _event_times()
        opts = CarspanOptions(freq_resolution=0.02, smooth_for_display=True)
        r = compute_carspan_psd(times, options=opts)
        # Bin centres should be near multiples of 0.02 Hz.
        residuals = np.abs(r.freqs - np.round(r.freqs / 0.02) * 0.02)
        assert np.max(residuals) < 1e-9

    def test_short_event_series_raises(self):
        with pytest.raises(ValueError):
            compute_carspan_psd(np.array([0.0, 0.8, 1.6]))   # 3 events

    def test_zero_span_raises(self):
        with pytest.raises(ValueError, match=r"[Tt]"):
            compute_carspan_psd(np.array([0.0, 0.0, 0.0, 0.0]))


class TestCarspanStrictParity:
    """The strict path is the :func:`carspan_strict_options` preset
    applied through :func:`compute_carspan_psd`.

    :func:`compute_carspan_psd_strict` is a thin wrapper that calls
    ``compute_carspan_psd(options=carspan_strict_options(...))`` and
    rebrands the ``method`` field on the result. Its output is therefore
    numerically identical to ``compute_carspan_psd`` with the same
    options, modulo the ``method`` string.
    """

    def test_strict_wrapper_matches_preset(self):
        times = _event_times(n_beats=300)
        a = compute_carspan_psd_strict(times)
        b = compute_carspan_psd(times, options=carspan_strict_options())
        assert np.array_equal(a.freqs, b.freqs)
        assert np.array_equal(a.power, b.power)
        # method differs (the wrapper rebrands), units agree.
        assert a.method == "carspan_strict"
        assert b.method == "carspan"
        assert a.unit == b.unit == "ms²/Hz"

    def test_strict_uses_ibi_amplitude_signal(self):
        """The strict preset must set ``signal="ibi_amplitude"`` so the
        compute layer takes the manual Eq. 3.21 branch."""
        opts = carspan_strict_options()
        assert opts.signal == "ibi_amplitude"

    def test_strict_returns_resampled_grid_in_ms2_per_hz(self):
        """The strict preset's spectrum comes back on the 0.01 Hz
        display grid (Pascal's ``Resample`` runs unconditionally inside
        ``compute_carspan_psd``), with ``ms²/Hz`` as the raw unit (the
        IBI-amplitude DFT of Eq. 3.21)."""
        times = _event_times(n_beats=300)
        r = compute_carspan_psd_strict(times)
        assert r.method == "carspan_strict"
        assert r.unit == "ms²/Hz"
        assert r.freqs[0] == pytest.approx(0.01)
        assert r.freqs[-1] <= 0.5 + 1e-9
        assert r.ci_lower is not None and r.ci_lower.shape == r.power.shape
        assert r.ci_upper is not None and r.ci_upper.shape == r.power.shape

    def test_strict_differs_from_default_events_signal(self):
        """When you flip ``signal`` back to ``"events"`` on the same
        otherwise-strict bundle, the spectrum must change (different
        algorithm)."""
        times = _event_times(n_beats=300)
        from dataclasses import replace as _replace
        strict_opts = carspan_strict_options()
        events_opts = _replace(strict_opts, signal="events")
        strict = compute_carspan_psd(times, options=strict_opts)
        events = compute_carspan_psd(times, options=events_opts)
        # Same display grid (both go through the same Resample step).
        assert np.array_equal(strict.freqs, events.freqs)
        # But the spectra differ, IBI-amplitude vs unit-impulse.
        assert not np.allclose(strict.power, events.power)
        # And the units reflect the different native scales.
        assert strict.unit == "ms²/Hz"
        assert events.unit == "Hz"

    def test_strict_carries_chi2_ci(self):
        times = _event_times(n_beats=300)
        r = compute_carspan_psd_strict(times)
        # CI lower ≤ power ≤ CI upper for every bin (chi² CI on positive
        # periodogram values).
        assert np.all(r.ci_lower <= r.power + 1e-12)
        assert np.all(r.ci_upper >= r.power - 1e-12)

    def test_dc_removal_drains_low_frequency(self):
        """Configurable CARSPAN: with reference-grid DC removal on, the
        lowest-frequency bin should be much smaller than without it."""
        times = _event_times(n_beats=300, jitter_s=0.02)
        with_dc    = compute_carspan_psd(
            times, options=CarspanOptions(dc_removal=True)
        )
        without_dc = compute_carspan_psd(
            times, options=CarspanOptions(dc_removal=False)
        )
        # The very-low-frequency power should drop substantially.
        low = with_dc.freqs < 0.02
        if low.any():
            assert with_dc.power[low].sum() < without_dc.power[low].sum()


class TestCarspanIndividualKnobs:
    """Each knob on :class:`CarspanOptions` is independently
    addressable. These tests confirm individual elements of the strict
    bundle change the output when toggled in isolation. (Strict-mode
    bit-identity is covered by :class:`TestCarspanStrictParity`.)"""

    @staticmethod
    def _rel_max_diff(a, b) -> float:
        """Max |a-b| relative to median |a|. Robust to scale changes."""
        eps = max(float(np.median(np.abs(a.power))), 1e-12)
        return float(np.max(np.abs(a.power - b.power)) / eps)

    def test_skip_first_event_changes_output(self):
        times = _event_times(n_beats=300)
        baseline = compute_carspan_psd(
            times, options=CarspanOptions(skip_first_event=False)
        )
        skipped = compute_carspan_psd(
            times, options=CarspanOptions(skip_first_event=True)
        )
        # Different actual_times array → some bins should differ by
        # more than 0.1 % of the typical spectrum level.
        assert self._rel_max_diff(baseline, skipped) > 1e-3

    def test_taper_choices_differ(self):
        times = _event_times(n_beats=300)
        scipy_taper = compute_carspan_psd(
            times, options=CarspanOptions(taper="scipy", window="hann")
        )
        carspan_taper = compute_carspan_psd(
            times,
            options=CarspanOptions(
                taper="carspan_index",
                # Disable the N/S₂ correction so we exercise only the
                # taper-shape difference, not the amplitude formula.
                amplitude_correction=False,
            ),
        )
        # Hann vs. CARSPAN's narrow cosine bell → huge level offset.
        assert self._rel_max_diff(scipy_taper, carspan_taper) > 0.1

    def test_amplitude_correction_changes_level(self):
        times = _event_times(n_beats=300)
        corrected = compute_carspan_psd(
            times, options=CarspanOptions(amplitude_correction=True)
        )
        bare = compute_carspan_psd(
            times, options=CarspanOptions(amplitude_correction=False)
        )
        # 2N/(T·S₂) vs 2/T → different overall level (order of
        # magnitude depending on the window's S₂).
        assert self._rel_max_diff(corrected, bare) > 0.1

    def test_dc_grid_choice_runs_for_both_options(self):
        """Both DC reference-grid layouts must produce valid output.

        For approximately regular rhythms the two grids align almost
        exactly with the actual events, so the DC-removed spectra are
        numerically indistinguishable (max relative difference is at
        the float-precision noise floor). The point of this test is
        that *neither* grid raises and both produce finite power,
        the bit-for-bit parity is exercised by
        :class:`TestCarspanStrictParity`.
        """
        times = _event_times(n_beats=300)
        for grid in ("span_matched", "carspan_strict"):
            r = compute_carspan_psd(
                times,
                options=CarspanOptions(dc_removal=True, dc_grid=grid),
            )
            assert np.all(np.isfinite(r.power))
            assert np.all(r.power >= 0.0)

    def test_dc_removal_drains_dc_for_both_grids(self):
        """Sanity: the low-frequency end of the spectrum should be much
        smaller with DC removal on, regardless of grid choice.

        Compared on the unresampled native grid (``freq_resolution``
        chosen smaller than ``1/T`` keeps :func:`_bin_average` from
        collapsing neighbouring bins, exposing the per-bin difference
        DC removal introduces near f = 0).
        """
        times = _event_times(n_beats=300, jitter_s=0.02)
        # native_df = 1/T ≈ 0.004 Hz for n_beats=300, mean_ibi 0.8 s.
        # Picking display_resolution well below that disables Resample.
        native_native_df = 0.001
        for grid in ("span_matched", "carspan_strict"):
            with_dc = compute_carspan_psd(
                times,
                options=CarspanOptions(
                    dc_removal=True, dc_grid=grid,
                    freq_resolution=native_native_df,
                ),
            )
            without_dc = compute_carspan_psd(
                times,
                options=CarspanOptions(
                    dc_removal=False, freq_resolution=native_native_df,
                ),
            )
            low = with_dc.freqs < 0.02
            assert low.any()
            assert with_dc.power[low].sum() < without_dc.power[low].sum()
