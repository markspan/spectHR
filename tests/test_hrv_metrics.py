"""
tests/test_hrv_metrics.py — mixin-level HRV metrics.

Covers the merged :class:`CardioMetricsMixin` (time- and
frequency-domain) on a real :class:`CardioSeries`. Pure compute-layer
tests live in :mod:`tests.test_psd_compute`; configuration plumbing
lives in :mod:`tests.test_psd_config`.

Sections
--------
- Magnitude statistics (count, mean, min, max, median)
- Variability (sdnn, rmssd, sdsd) — gap-safe
- Poincaré (sd1, sd2, sd_ratio, ellipse_area) + Brennan identity
- Artefact handling (TL, T, mixed labels, non-bad labels)
- Edge cases (empty / single / two-beat / all-artefact series)
- Frequency-domain via PsdMethod (welch, lombscargle, carspan,
  carspan_strict): basic shape, band-power direction, override vs.
  instance attribute, ``band_powers()`` consistency.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Series.CardioMetricsMixin import (
    BandSpec,
    PsdMethod,
    PSDResult,
)

from conftest import (   # imported via pytest rootdir/conftest.py
    WORKSPACE_BANDS,
    make_cs,
    make_spectral_cs,
    make_two_sinusoid_cs,
)


# ===========================================================================
# Magnitude statistics
# ===========================================================================


class TestCount:
    """``count()`` returns the number of valid (non-NaN, non-artefact) IBIs."""

    def test_basic(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert cs.count() == 4

    def test_single_ibi(self):
        cs = make_cs([800.0])
        assert cs.count() == 1

    def test_empty_series(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert cs.count() == 0

    def test_one_beat_no_ibi(self):
        cs = CardioSeries(np.array([0.0]))
        assert cs.count() == 0

    def test_tl_excluded(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "TL", "N", "N", "N"])
        assert cs.count() == 3

    def test_t_excluded(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "N", "T", "N", "N"])
        assert cs.count() == 3

    def test_non_bad_labels_kept(self):
        """Labels other than TL/T (e.g. ``"L"``, ``"S"``) are not treated
        as artefacts by ``_BAD_LABELS``."""
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "L", "S", "N", "N"])
        # All four IBIs valid (L and S are not in _BAD_LABELS).
        assert cs.count() == 4


class TestMagnitudeStats:
    IBI = [800.0, 900.0, 1000.0, 850.0]

    def test_mean(self):
        cs = make_cs(self.IBI)
        assert cs.mean() == pytest.approx(np.mean(self.IBI))

    def test_min(self):
        cs = make_cs(self.IBI)
        assert cs.min() == pytest.approx(min(self.IBI))

    def test_max(self):
        cs = make_cs(self.IBI)
        assert cs.max() == pytest.approx(max(self.IBI))

    def test_median(self):
        cs = make_cs(self.IBI)
        assert cs.median() == pytest.approx(np.median(self.IBI))

    def test_uniform_series(self):
        cs = make_cs([800.0, 800.0, 800.0])
        for fn in (cs.mean, cs.min, cs.max, cs.median):
            assert fn() == pytest.approx(800.0)

    def test_empty_series_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        for fn in (cs.mean, cs.min, cs.max, cs.median):
            assert np.isnan(fn())

    def test_mean_excludes_artefacts(self):
        # IBIs [800, 900, 800, 900]; idx 1 labelled TL → kept [800, 800, 900]
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "TL", "N", "N", "N"])
        assert cs.mean() == pytest.approx(np.mean([800.0, 800.0, 900.0]))


# ===========================================================================
# Variability
# ===========================================================================


class TestSdnn:
    def test_uniform_zero(self):
        cs = make_cs([800.0] * 5)
        assert cs.sdnn() == pytest.approx(0.0)

    def test_known_value(self):
        ibi = [800.0, 900.0, 800.0, 900.0]
        cs = make_cs(ibi)
        assert cs.sdnn() == pytest.approx(float(np.std(ibi)))

    def test_single_ibi(self):
        """std of one value is 0."""
        cs = make_cs([850.0])
        assert cs.sdnn() == pytest.approx(0.0)

    def test_empty_returns_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(cs.sdnn())


class TestRmssd:
    def test_uniform_zero(self):
        cs = make_cs([800.0] * 5)
        assert cs.rmssd() == pytest.approx(0.0)

    def test_alternating_known(self):
        # IBIs [800,900,800,900] → diffs [100,-100,100] → rmssd = 100
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert cs.rmssd() == pytest.approx(100.0)

    def test_single_diff(self):
        """Two IBIs → one diff."""
        cs = make_cs([800.0, 1000.0])
        assert cs.rmssd() == pytest.approx(200.0)

    def test_one_ibi_nan(self):
        cs = make_cs([800.0])
        assert np.isnan(cs.rmssd())

    def test_empty_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(cs.rmssd())

    def test_gap_safety_tl_breaks_chain(self):
        """An excluded IBI severs successive-diff chains on both sides.

        IBIs [800, 900, 800, 900] with idx-1 labelled TL:
        valid mask [T,F,T,T,F] → pair-ok [F,F,T,F]
        → only one diff: ibi[3] − ibi[2] = 900 − 800 = 100
        → rmssd = 100.
        """
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "TL", "N", "N", "N"])
        assert cs.rmssd() == pytest.approx(100.0)

    def test_tl_and_t_equivalent(self):
        ibi = [800.0, 900.0, 800.0, 900.0]
        cs_tl = make_cs(ibi, labels=["N", "TL", "N", "N", "N"])
        cs_t  = make_cs(ibi, labels=["N",  "T", "N", "N", "N"])
        assert cs_tl.rmssd() == pytest.approx(cs_t.rmssd())


class TestSdsd:
    def test_uniform_zero(self):
        assert make_cs([800.0] * 5).sdsd() == pytest.approx(0.0)

    def test_known(self):
        diffs = [100.0, -100.0, 100.0]
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert cs.sdsd() == pytest.approx(float(np.std(diffs)))

    def test_single_diff_std_zero(self):
        cs = make_cs([800.0, 900.0])
        assert cs.sdsd() == pytest.approx(0.0)

    def test_one_ibi_nan(self):
        assert np.isnan(make_cs([800.0]).sdsd())


# ===========================================================================
# Poincaré
# ===========================================================================


class TestPoincare:
    """SD1, SD2, sd_ratio, ellipse_area."""

    def test_sd1_uniform_zero(self):
        assert make_cs([800.0] * 6).sd1() == pytest.approx(0.0)

    def test_sd1_formula(self):
        diffs = [100.0, -100.0, 100.0]
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert cs.sd1() == pytest.approx(float(np.std(diffs)) / np.sqrt(2.0))

    def test_sd_ratio_uniform_nan(self):
        """SD2 = 0 → ratio is NaN."""
        assert np.isnan(make_cs([800.0] * 6).sd_ratio())

    def test_ellipse_area_formula(self):
        cs = make_cs([800.0, 850.0, 900.0, 820.0, 780.0, 860.0])
        s1, s2 = cs.sd1(), cs.sd2()
        if np.isnan(s1) or np.isnan(s2):
            assert np.isnan(cs.ellipse_area())
        else:
            assert cs.ellipse_area() == pytest.approx(np.pi * s1 * s2)

    def test_all_poincare_nan_on_empty(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(cs.sd1())
        assert np.isnan(cs.sd2())
        assert np.isnan(cs.sd_ratio())
        assert np.isnan(cs.ellipse_area())

    def test_sd_ratio_two_beats_nan(self):
        """One IBI, no diffs → sd1 is NaN → ratio NaN."""
        assert np.isnan(make_cs([800.0]).sd_ratio())


class TestBrennanIdentity:
    """SD1² + SD2² = 2·SDNN² (algebraic identity)."""

    @pytest.mark.parametrize("ibi", [
        [800.0, 850.0, 900.0, 820.0, 780.0, 860.0],
        [600.0, 700.0, 800.0, 900.0, 1000.0],
        [950.0, 930.0, 960.0, 910.0, 940.0, 920.0, 950.0],
    ])
    def test_identity_holds(self, ibi):
        cs = make_cs(ibi)
        s1, s2 = cs.sd1(), cs.sd2()
        if np.isnan(s1) or np.isnan(s2):
            pytest.skip("Degenerate case — SD2 not defined.")
        assert s1 ** 2 + s2 ** 2 == pytest.approx(2.0 * cs.sdnn() ** 2, rel=1e-6)


# ===========================================================================
# Artefact + edge cases
# ===========================================================================


class TestArtefacts:
    """Both TL and T must be excluded everywhere."""

    def test_all_tl_count_zero(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["TL"] * 5)
        assert cs.count() == 0

    def test_all_tl_scalar_metrics_nan(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["TL"] * 5)
        for fn in (cs.mean, cs.min, cs.max, cs.median,
                   cs.rmssd, cs.sdnn, cs.sdsd,
                   cs.sd1, cs.sd2, cs.sd_ratio, cs.ellipse_area):
            assert np.isnan(fn()), f"{fn.__name__} should be NaN"

    def test_mixed_labels_partial_exclusion(self):
        """Mix of TL, T, N — both bad labels excluded, others kept."""
        cs = make_cs([800.0, 900.0, 800.0, 900.0, 850.0],
                     labels=["N", "TL", "N", "T", "N", "N"])
        # Bad labels at idx 1 (TL) and idx 3 (T); rest are N.
        # IBIs 0,2,4 valid → count = 3.
        assert cs.count() == 3


class TestEdgeCases:
    """No metric should raise on degenerate inputs."""

    def test_empty_returns_nan_everywhere(self):
        cs = CardioSeries(np.array([], dtype=float))
        for fn in (cs.mean, cs.min, cs.max, cs.median,
                   cs.rmssd, cs.sdnn, cs.sdsd,
                   cs.sd1, cs.sd2, cs.sd_ratio, cs.ellipse_area):
            assert np.isnan(fn())

    def test_one_beat_no_ibi(self):
        cs = CardioSeries(np.array([0.0]))
        assert cs.count() == 0
        assert np.isnan(cs.mean())
        assert np.isnan(cs.rmssd())

    def test_two_beats_one_ibi(self):
        cs = make_cs([800.0])
        assert cs.count() == 1
        assert cs.mean() == pytest.approx(800.0)
        assert np.isnan(cs.rmssd())
        assert np.isnan(cs.sdsd())
        assert np.isnan(cs.sd1())

    def test_three_beats_two_ibis(self):
        cs = make_cs([800.0, 900.0])
        assert cs.count() == 2
        assert cs.rmssd() == pytest.approx(100.0)
        assert cs.sdsd() == pytest.approx(0.0)   # std of single diff


# ===========================================================================
# Frequency-domain via the new PsdMethod API
# ===========================================================================


def _attach(cs: CardioSeries, *, algorithm="carspan", bands=None) -> CardioSeries:
    """Helper: assign a workspace-style PsdMethod to *cs* and return it."""
    cs.psd_method = PsdMethod(
        algorithm=algorithm,
        bands=dict(bands or WORKSPACE_BANDS),
    )
    return cs


class TestPsdReturnType:
    """``series.psd()`` returns a fully-populated PSDResult."""

    def test_psdresult_type_and_fields(self, typical_cs):
        r = typical_cs.psd(with_ci=True)
        assert isinstance(r, PSDResult)
        assert r.method == "carspan"
        assert "Hz" in r.unit         # mMI²/Hz or ms²/Hz
        assert r.freqs.shape == r.power.shape
        assert r.ci_lower is not None
        assert r.ci_upper is not None

    def test_with_ci_false_drops_bounds(self, typical_cs):
        r = typical_cs.psd(with_ci=False)
        assert r.ci_lower is None
        assert r.ci_upper is None


class TestPsdMethodResolution:
    """The mixin picks an active method in the right order:
    override > instance attribute > module default."""

    def test_explicit_override_wins(self, typical_cs):
        # Instance attribute says carspan; override to welch.
        r = typical_cs.psd(psd_method=PsdMethod(
            algorithm="welch", bands=dict(WORKSPACE_BANDS)
        ))
        assert r.method == "welch"

    def test_instance_attribute_used_when_no_override(self, typical_cs):
        # Instance attribute = carspan (set by the fixture).
        assert typical_cs.psd_method is not None
        r = typical_cs.psd()
        assert r.method == "carspan"

    def test_module_default_used_when_attribute_unset(self):
        """A bare CardioSeries (no psd_method assigned) still works —
        falls through to the module-level default ``PsdMethod()``."""
        rng = np.random.default_rng(11)
        ibi_ms = 800.0 + rng.normal(0.0, 30.0, 250)
        cs = make_cs(ibi_ms)
        assert cs.psd_method is None
        r = typical_cs_with_default_method = cs.psd()
        # Default algorithm is "carspan".
        assert r.method == "carspan"


class TestBandPower:
    """``band_power`` returns one float per named band."""

    def test_named_bands(self, typical_cs):
        for name in ("FullRange", "VLF", "LF", "HF"):
            val = typical_cs.band_power(name)
            assert np.isfinite(val)
            assert val >= 0.0

    def test_unknown_band_raises_key_error(self, typical_cs):
        with pytest.raises(KeyError):
            typical_cs.band_power("not_a_band")

    def test_band_powers_dict_keys_match_method_bands(self, typical_cs):
        bp = typical_cs.band_powers()
        assert set(bp) == set(typical_cs.psd_method.bands)

    def test_fullrange_dominates(self, typical_cs):
        """FullRange spans VLF + LF + HF, so its integral must be at
        least as large as any single sub-band's (allow 5 % slack for
        edge-bin rounding)."""
        bp = typical_cs.band_powers()
        biggest_sub = max(bp["VLF"], bp["LF"], bp["HF"])
        assert bp["FullRange"] >= biggest_sub * 0.95


class TestSpectralDirection:
    """A sinusoidal IBI modulation must put its peak in the right band."""

    @pytest.mark.parametrize("freq_hz, dominant_band, others", [
        (0.04, "VLF", ["LF", "HF"]),
        (0.10, "LF",  ["VLF", "HF"]),
        (0.25, "HF",  ["VLF", "LF"]),
    ])
    def test_dominant_band(self, freq_hz, dominant_band, others):
        cs = make_spectral_cs(freq_hz)
        _attach(cs)
        bp = cs.band_powers()
        if not all(np.isfinite(bp[b]) for b in (dominant_band, *others)):
            pytest.skip("Non-finite band powers.")
        dom = bp[dominant_band]
        for o in others:
            assert dom > bp[o], (
                f"{dominant_band} ({dom:.4f}) should exceed {o} ({bp[o]:.4f}) "
                f"at {freq_hz} Hz"
            )

    def test_lf_dominant_ratio_above_one(self):
        cs = make_spectral_cs(0.10)
        _attach(cs)
        ratio = cs.lf_hf_ratio()
        if np.isfinite(ratio):
            assert ratio > 1.0

    def test_hf_dominant_ratio_below_one(self):
        cs = make_spectral_cs(0.25)
        _attach(cs)
        ratio = cs.lf_hf_ratio()
        if np.isfinite(ratio):
            assert ratio < 1.0


class TestAllAlgorithms:
    """Every algorithm should produce non-negative, directionally
    consistent band powers on the same input."""

    @pytest.fixture
    def lf_series(self):
        cs = make_spectral_cs(0.10)
        return cs

    @pytest.fixture
    def hf_series(self):
        cs = make_spectral_cs(0.25)
        return cs

    @pytest.mark.parametrize(
        "algorithm", ["welch", "lombscargle", "carspan", "carspan_strict"]
    )
    def test_returns_psdresult(self, lf_series, algorithm):
        method = PsdMethod(
            algorithm=algorithm,
            bands=dict(WORKSPACE_BANDS),
            mean_convention=("arithmetic" if algorithm == "carspan_strict" else "harmonic"),
        )
        lf_series.psd_method = method
        r = lf_series.psd(with_ci=True)
        assert isinstance(r, PSDResult)
        assert r.method == algorithm

    @pytest.mark.parametrize(
        "algorithm", ["welch", "lombscargle", "carspan", "carspan_strict"]
    )
    def test_lf_dominant(self, lf_series, algorithm):
        method = PsdMethod(
            algorithm=algorithm,
            bands=dict(WORKSPACE_BANDS),
            mean_convention=("arithmetic" if algorithm == "carspan_strict" else "harmonic"),
        )
        lf_series.psd_method = method
        lf = lf_series.band_power("LF")
        hf = lf_series.band_power("HF")
        if not (np.isfinite(lf) and np.isfinite(hf)):
            pytest.skip(f"{algorithm}: non-finite output.")
        assert lf > hf, f"{algorithm}: LF ({lf:.4f}) should exceed HF ({hf:.4f})"

    @pytest.mark.parametrize(
        "algorithm", ["welch", "lombscargle", "carspan", "carspan_strict"]
    )
    def test_hf_dominant(self, hf_series, algorithm):
        method = PsdMethod(
            algorithm=algorithm,
            bands=dict(WORKSPACE_BANDS),
            mean_convention=("arithmetic" if algorithm == "carspan_strict" else "harmonic"),
        )
        hf_series.psd_method = method
        lf = hf_series.band_power("LF")
        hf = hf_series.band_power("HF")
        if not (np.isfinite(lf) and np.isfinite(hf)):
            pytest.skip(f"{algorithm}: non-finite output.")
        assert hf > lf, f"{algorithm}: HF ({hf:.4f}) should exceed LF ({lf:.4f})"


class TestSumOfTwoSinusoids:
    """Feed sin(2π·f_a·t) + sin(2π·f_b·t) into every PSD method and check
    that *both* injected tones produce peaks in the right bands.

    The reference signal uses ``f_a = 0.10 Hz`` (LF) and ``f_b = 0.25 Hz``
    (HF). VLF receives no injected tone — it should stay quiet.
    """

    LF_HZ = 0.10
    HF_HZ = 0.25
    ALGORITHMS = ("welch", "lombscargle", "carspan", "carspan_strict")

    @pytest.fixture
    def lf_hf_series(self):
        return make_two_sinusoid_cs(self.LF_HZ, self.HF_HZ)

    @pytest.fixture
    def baseline_series(self):
        """Zero-modulation reference with the same RNG seed/length —
        used to verify the injected peaks rise *above* a no-signal floor."""
        return make_two_sinusoid_cs(self.LF_HZ, self.HF_HZ, mod_depth_each=0.0)

    @staticmethod
    def _method_for(algorithm):
        return PsdMethod(
            algorithm=algorithm,
            bands=dict(WORKSPACE_BANDS),
            mean_convention=("arithmetic" if algorithm == "carspan_strict" else "harmonic"),
        )

    @pytest.mark.parametrize("algorithm", ALGORITHMS)
    def test_both_target_bands_exceed_vlf(self, lf_hf_series, algorithm):
        """Both LF and HF must carry more power than VLF (which has no
        injected tone)."""
        lf_hf_series.psd_method = self._method_for(algorithm)
        bp = lf_hf_series.band_powers()
        for name in ("VLF", "LF", "HF"):
            if not np.isfinite(bp[name]):
                pytest.skip(f"{algorithm}: non-finite band power for {name}.")
        assert bp["LF"] > bp["VLF"], (
            f"{algorithm}: LF ({bp['LF']:.4g}) should exceed VLF ({bp['VLF']:.4g})"
        )
        assert bp["HF"] > bp["VLF"], (
            f"{algorithm}: HF ({bp['HF']:.4g}) should exceed VLF ({bp['VLF']:.4g})"
        )

    @pytest.mark.parametrize("algorithm", ALGORITHMS)
    def test_injected_peaks_above_baseline(
        self, lf_hf_series, baseline_series, algorithm
    ):
        """LF and HF band power must rise above the no-modulation
        baseline by at least a 3× factor."""
        method = self._method_for(algorithm)
        lf_hf_series.psd_method = method
        baseline_series.psd_method = method

        signal = lf_hf_series.band_powers()
        base = baseline_series.band_powers()
        for name in ("LF", "HF"):
            if not (np.isfinite(signal[name]) and np.isfinite(base[name])):
                pytest.skip(f"{algorithm}: non-finite band power for {name}.")
            if base[name] <= 0.0:
                pytest.skip(f"{algorithm}: baseline {name} non-positive.")
            ratio = signal[name] / base[name]
            assert ratio > 3.0, (
                f"{algorithm}: {name} should be ≥3× baseline "
                f"(got {ratio:.2f}: signal={signal[name]:.4g}, "
                f"baseline={base[name]:.4g})"
            )

    @pytest.mark.parametrize("algorithm", ALGORITHMS)
    def test_peak_frequencies_recovered(self, lf_hf_series, algorithm):
        """The argmax inside each band must land within ±0.02 Hz of the
        injected tone."""
        lf_hf_series.psd_method = self._method_for(algorithm)
        r = lf_hf_series.psd(with_ci=False)
        if not np.all(np.isfinite(r.power)):
            pytest.skip(f"{algorithm}: non-finite spectrum.")

        bands = lf_hf_series.psd_method.bands
        for target_hz, name in ((self.LF_HZ, "LF"), (self.HF_HZ, "HF")):
            lo, hi = bands[name].low, bands[name].high
            in_band = (r.freqs >= lo) & (r.freqs <= hi)
            if not in_band.any():
                pytest.skip(f"{algorithm}: no bins inside {name} band.")
            band_freqs = r.freqs[in_band]
            band_power = r.power[in_band]
            peak_hz = band_freqs[int(np.argmax(band_power))]
            assert abs(peak_hz - target_hz) <= 0.02, (
                f"{algorithm}: {name} peak at {peak_hz:.3f} Hz, "
                f"expected near {target_hz:.3f} Hz"
            )

    @pytest.mark.parametrize("algorithm", ALGORITHMS)
    def test_both_lf_and_hf_metrics_finite_and_positive(
        self, lf_hf_series, algorithm
    ):
        """The legacy convenience metrics ``lf_power()`` and ``hf_power()``
        should both return finite positive values."""
        lf_hf_series.psd_method = self._method_for(algorithm)
        lf = lf_hf_series.lf_power()
        hf = lf_hf_series.hf_power()
        if not (np.isfinite(lf) and np.isfinite(hf)):
            pytest.skip(f"{algorithm}: non-finite output.")
        assert lf > 0.0 and hf > 0.0


class TestUnknownAlgorithmRaises:
    """An invalid algorithm string must surface as a ValueError."""

    def test_unknown_algorithm(self):
        rng = np.random.default_rng(13)
        cs = make_cs(800.0 + rng.normal(0.0, 30.0, 250))
        cs.psd_method = PsdMethod(algorithm="not_a_method")   # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unknown PSD algorithm"):
            cs.psd()


class TestFrequencyArtefactRobustness:
    """Frequency metrics return NaN (not raise) when the cleaned series
    is too short to compute a PSD."""

    def test_too_few_ibis_for_psd(self):
        cs = make_cs([800.0, 900.0])   # 2 IBIs, below the 4-sample floor
        _attach(cs)
        for fn in (cs.vlf_power, cs.lf_power, cs.hf_power,
                   cs.fullrange_power, cs.lf_hf_ratio):
            assert np.isnan(fn())

    def test_all_tl_frequency_metrics_nan(self):
        cs = make_cs([800.0] * 20)
        cs.labels[:] = "TL"
        _attach(cs)
        assert np.isnan(cs.lf_power())
        assert np.isnan(cs.hf_power())
        assert np.isnan(cs.lf_hf_ratio())

    def test_sparse_tl_does_not_break_psd(self):
        rng = np.random.default_rng(3)
        ibi_ms = 800.0 + rng.normal(0.0, 25.0, 200)
        ibi_ms = np.clip(ibi_ms, 400.0, 1500.0)
        cs = make_cs(ibi_ms)
        for i in range(0, len(cs.labels), 15):
            cs.labels[i] = "TL"
        _attach(cs)
        lf = cs.lf_power()
        assert np.isfinite(lf) and lf >= 0.0


class TestUnitConsistency:
    """The legend-side ``unit`` string survives the conversion pipeline."""

    def test_carspan_default_unit_mMI2(self, lf_cs):
        # Default plot_units = "mMI²/Hz"
        r = lf_cs.psd()
        assert "mMI" in r.unit

    def test_welch_default_unit_mMI2(self, lf_cs):
        lf_cs.psd_method = PsdMethod(algorithm="welch", bands=dict(WORKSPACE_BANDS))
        r = lf_cs.psd()
        assert "mMI" in r.unit

    def test_welch_ms2_units_when_requested(self, lf_cs):
        from spectHR.Tools.PSD.WelchPSD import WelchOptions
        lf_cs.psd_method = PsdMethod(
            algorithm="welch",
            bands=dict(WORKSPACE_BANDS),
            welch=WelchOptions(units="ms²"),
        )
        r = lf_cs.psd()
        assert "ms" in r.unit
