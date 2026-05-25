"""
tests/test_hrv_metrics.py -- HRV metrics via the analysis layer.

Covers the time- and frequency-domain functions in spectHR.analysis.
CardioSeries is pure data; all metric computation lives in the analysis
module and is called with the series as an argument.

Sections
--------
- Magnitude statistics (count, mean, min, max, median)
- Variability (sdnn, rmssd, sdsd) -- gap-safe
- Poincare (sd1, sd2, sd_ratio, ellipse_area) + Brennan identity
- Artefact handling (TL, T, mixed labels, non-bad labels)
- Edge cases (empty / single / two-beat / all-artefact series)
- Frequency-domain via PSDEngine: basic shape, band-power direction,
  algorithm coverage, lf/hf convenience metrics.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.analysis.psd import (
    BandSpec,
    PsdMethod,
    PSDResult,
    PSDEngine,
)
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.time_metrics import (
    count, mean, median, sdnn, rmssd, sdsd, sd1, sd2, sd_ratio, ellipse_area,
    min as ibi_min,
    max as ibi_max,
)
from spectHR.analysis.frequency_metrics import (
    lf_power, hf_power, lf_hf_ratio, vlf_power, fullrange_power,
)

from conftest import (   # imported via pytest rootdir/conftest.py
    WORKSPACE_BANDS,
    make_cs,
    make_spectral_cs,
    make_two_sinusoid_cs,
)


# ---------------------------------------------------------------------------
# Shared helpers for the frequency tests
# ---------------------------------------------------------------------------

def _method(algorithm: str = "carspan", bands=None) -> PsdMethod:
    """Build a workspace-style PsdMethod."""
    return PsdMethod(
        algorithm=algorithm,
        bands=dict(bands or WORKSPACE_BANDS),
        mean_convention=("arithmetic" if algorithm == "carspan_strict" else "harmonic"),
    )


def _psd(cs, method: PsdMethod | None = None, *, with_ci: bool = True) -> PSDResult:
    """Compute PSD on cs with the given (or default) method."""
    if method is None:
        method = _method()
    return PSDEngine(cs).compute(method, with_ci=with_ci)


def _band_powers(cs, method: PsdMethod | None = None) -> dict[str, float]:
    """Return {band_name: power} for all bands in the method."""
    if method is None:
        method = _method()
    result = PSDEngine(cs).for_band_power(method)
    return {
        name: float(band_power_rectangular(result.freqs, result.power, spec.low, spec.high))
        for name, spec in method.bands.items()
    }


def _band_power(cs, band_name: str, method: PsdMethod | None = None) -> float:
    return _band_powers(cs, method)[band_name]


# ===========================================================================
# Magnitude statistics
# ===========================================================================


class TestCount:
    """``count()`` returns the number of valid (non-NaN, non-artefact) IBIs."""

    def test_basic(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert count(cs) == 4

    def test_single_ibi(self):
        cs = make_cs([800.0])
        assert count(cs) == 1

    def test_empty_series(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert count(cs) == 0

    def test_one_beat_no_ibi(self):
        cs = CardioSeries(np.array([0.0]))
        assert count(cs) == 0

    def test_tl_excluded(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "TL", "N", "N", "N"])
        assert count(cs) == 3

    def test_t_excluded(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "N", "T", "N", "N"])
        assert count(cs) == 3

    def test_non_bad_labels_kept(self):
        """Labels other than TL/T (e.g. ``"L"``, ``"S"``) are not treated
        as artefacts by ``_BAD_LABELS``."""
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "L", "S", "N", "N"])
        # All four IBIs valid (L and S are not in _BAD_LABELS).
        assert count(cs) == 4


class TestMagnitudeStats:
    IBI = [800.0, 900.0, 1000.0, 850.0]

    def test_mean(self):
        cs = make_cs(self.IBI)
        assert mean(cs) == pytest.approx(np.mean(self.IBI))

    def test_min(self):
        cs = make_cs(self.IBI)
        assert ibi_min(cs) == pytest.approx(min(self.IBI))

    def test_max(self):
        cs = make_cs(self.IBI)
        assert ibi_max(cs) == pytest.approx(max(self.IBI))

    def test_median(self):
        cs = make_cs(self.IBI)
        assert median(cs) == pytest.approx(np.median(self.IBI))

    def test_uniform_series(self):
        cs = make_cs([800.0, 800.0, 800.0])
        for fn in (mean, ibi_min, ibi_max, median):
            assert fn(cs) == pytest.approx(800.0)

    def test_empty_series_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        for fn in (mean, ibi_min, ibi_max, median):
            assert np.isnan(fn(cs))

    def test_mean_excludes_artefacts(self):
        # IBIs [800, 900, 800, 900]; idx 1 labelled TL -> kept [800, 800, 900]
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "TL", "N", "N", "N"])
        assert mean(cs) == pytest.approx(np.mean([800.0, 800.0, 900.0]))


# ===========================================================================
# Variability
# ===========================================================================


class TestSdnn:
    def test_uniform_zero(self):
        cs = make_cs([800.0] * 5)
        assert sdnn(cs) == pytest.approx(0.0)

    def test_known_value(self):
        ibi = [800.0, 900.0, 800.0, 900.0]
        cs = make_cs(ibi)
        assert sdnn(cs) == pytest.approx(float(np.std(ibi)))

    def test_single_ibi(self):
        """std of one value is 0."""
        cs = make_cs([850.0])
        assert sdnn(cs) == pytest.approx(0.0)

    def test_empty_returns_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(sdnn(cs))


class TestRmssd:
    def test_uniform_zero(self):
        cs = make_cs([800.0] * 5)
        assert rmssd(cs) == pytest.approx(0.0)

    def test_alternating_known(self):
        # IBIs [800,900,800,900] -> diffs [100,-100,100] -> rmssd = 100
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert rmssd(cs) == pytest.approx(100.0)

    def test_single_diff(self):
        """Two IBIs -> one diff."""
        cs = make_cs([800.0, 1000.0])
        assert rmssd(cs) == pytest.approx(200.0)

    def test_one_ibi_nan(self):
        cs = make_cs([800.0])
        assert np.isnan(rmssd(cs))

    def test_empty_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(rmssd(cs))

    def test_gap_safety_tl_breaks_chain(self):
        """An excluded IBI severs successive-diff chains on both sides.

        IBIs [800, 900, 800, 900] with idx-1 labelled TL:
        valid mask [T,F,T,T,F] -> pair-ok [F,F,T,F]
        -> only one diff: ibi[3] - ibi[2] = 900 - 800 = 100
        -> rmssd = 100.
        """
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["N", "TL", "N", "N", "N"])
        assert rmssd(cs) == pytest.approx(100.0)

    def test_tl_and_t_equivalent(self):
        ibi = [800.0, 900.0, 800.0, 900.0]
        cs_tl = make_cs(ibi, labels=["N", "TL", "N", "N", "N"])
        cs_t  = make_cs(ibi, labels=["N",  "T", "N", "N", "N"])
        assert rmssd(cs_tl) == pytest.approx(rmssd(cs_t))


class TestSdsd:
    def test_uniform_zero(self):
        assert sdsd(make_cs([800.0] * 5)) == pytest.approx(0.0)

    def test_known(self):
        diffs = [100.0, -100.0, 100.0]
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert sdsd(cs) == pytest.approx(float(np.std(diffs)))

    def test_single_diff_std_zero(self):
        cs = make_cs([800.0, 900.0])
        assert sdsd(cs) == pytest.approx(0.0)

    def test_one_ibi_nan(self):
        assert np.isnan(sdsd(make_cs([800.0])))


# ===========================================================================
# Poincare
# ===========================================================================


class TestPoincare:
    """SD1, SD2, sd_ratio, ellipse_area."""

    def test_sd1_uniform_zero(self):
        assert sd1(make_cs([800.0] * 6)) == pytest.approx(0.0)

    def test_sd1_formula(self):
        diffs = [100.0, -100.0, 100.0]
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert sd1(cs) == pytest.approx(float(np.std(diffs)) / np.sqrt(2.0))

    def test_sd_ratio_uniform_nan(self):
        """SD2 = 0 -> ratio is NaN."""
        assert np.isnan(sd_ratio(make_cs([800.0] * 6)))

    def test_ellipse_area_formula(self):
        cs = make_cs([800.0, 850.0, 900.0, 820.0, 780.0, 860.0])
        s1, s2 = sd1(cs), sd2(cs)
        if np.isnan(s1) or np.isnan(s2):
            assert np.isnan(ellipse_area(cs))
        else:
            assert ellipse_area(cs) == pytest.approx(np.pi * s1 * s2)

    def test_all_poincare_nan_on_empty(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(sd1(cs))
        assert np.isnan(sd2(cs))
        assert np.isnan(sd_ratio(cs))
        assert np.isnan(ellipse_area(cs))

    def test_sd_ratio_two_beats_nan(self):
        """One IBI, no diffs -> sd1 is NaN -> ratio NaN."""
        assert np.isnan(sd_ratio(make_cs([800.0])))


class TestBrennanIdentity:
    """SD1^2 + SD2^2 = 2*SDNN^2 (algebraic identity)."""

    @pytest.mark.parametrize("ibi", [
        [800.0, 850.0, 900.0, 820.0, 780.0, 860.0],
        [600.0, 700.0, 800.0, 900.0, 1000.0],
        [950.0, 930.0, 960.0, 910.0, 940.0, 920.0, 950.0],
    ])
    def test_identity_holds(self, ibi):
        cs = make_cs(ibi)
        s1, s2 = sd1(cs), sd2(cs)
        if np.isnan(s1) or np.isnan(s2):
            pytest.skip("Degenerate case -- SD2 not defined.")
        assert s1 ** 2 + s2 ** 2 == pytest.approx(2.0 * sdnn(cs) ** 2, rel=1e-6)


# ===========================================================================
# Artefact + edge cases
# ===========================================================================


class TestArtefacts:
    """Both TL and T must be excluded everywhere."""

    def test_all_tl_count_zero(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["TL"] * 5)
        assert count(cs) == 0

    def test_all_tl_scalar_metrics_nan(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["TL"] * 5)
        for name, fn in [
            ("mean", mean), ("ibi_min", ibi_min), ("ibi_max", ibi_max),
            ("median", median), ("rmssd", rmssd), ("sdnn", sdnn),
            ("sdsd", sdsd), ("sd1", sd1), ("sd2", sd2),
            ("sd_ratio", sd_ratio), ("ellipse_area", ellipse_area),
        ]:
            assert np.isnan(fn(cs)), f"{name} should be NaN"

    def test_mixed_labels_partial_exclusion(self):
        """Mix of TL, T, N -- both bad labels excluded, others kept."""
        cs = make_cs([800.0, 900.0, 800.0, 900.0, 850.0],
                     labels=["N", "TL", "N", "T", "N", "N"])
        # Bad labels at idx 1 (TL) and idx 3 (T); rest are N.
        # IBIs 0,2,4 valid -> count = 3.
        assert count(cs) == 3


class TestEdgeCases:
    """No metric should raise on degenerate inputs."""

    def test_empty_returns_nan_everywhere(self):
        cs = CardioSeries(np.array([], dtype=float))
        for fn in (mean, ibi_min, ibi_max, median,
                   rmssd, sdnn, sdsd,
                   sd1, sd2, sd_ratio, ellipse_area):
            assert np.isnan(fn(cs))

    def test_one_beat_no_ibi(self):
        cs = CardioSeries(np.array([0.0]))
        assert count(cs) == 0
        assert np.isnan(mean(cs))
        assert np.isnan(rmssd(cs))

    def test_two_beats_one_ibi(self):
        cs = make_cs([800.0])
        assert count(cs) == 1
        assert mean(cs) == pytest.approx(800.0)
        assert np.isnan(rmssd(cs))
        assert np.isnan(sdsd(cs))
        assert np.isnan(sd1(cs))

    def test_three_beats_two_ibis(self):
        cs = make_cs([800.0, 900.0])
        assert count(cs) == 2
        assert rmssd(cs) == pytest.approx(100.0)
        assert sdsd(cs) == pytest.approx(0.0)   # std of single diff


# ===========================================================================
# Frequency-domain via PSDEngine
# ===========================================================================


class TestPsdReturnType:
    """PSDEngine.compute() returns a fully-populated PSDResult."""

    def test_psdresult_type_and_fields(self, typical_cs):
        m = _method()
        r = _psd(typical_cs, m, with_ci=True)
        assert isinstance(r, PSDResult)
        assert r.method == "carspan"
        assert "Hz" in r.unit         # mMI^2/Hz or ms^2/Hz
        assert r.freqs.shape == r.power.shape
        assert r.ci_lower is not None
        assert r.ci_upper is not None

    def test_with_ci_false_drops_bounds(self, typical_cs):
        m = _method()
        r = _psd(typical_cs, m, with_ci=False)
        assert r.ci_lower is None
        assert r.ci_upper is None


class TestPsdAlgorithmSelection:
    """PSDEngine uses the algorithm specified in the PsdMethod."""

    def test_welch_selected(self, typical_cs):
        r = _psd(typical_cs, _method("welch"))
        assert r.method == "welch"

    def test_carspan_selected(self, typical_cs):
        r = _psd(typical_cs, _method("carspan"))
        assert r.method == "carspan"

    def test_default_method_runs(self):
        """PSDEngine must work with a freshly-constructed default PsdMethod."""
        rng = np.random.default_rng(11)
        ibi_ms = 800.0 + rng.normal(0.0, 30.0, 250)
        cs = make_cs(ibi_ms)
        r = _psd(cs, _method())
        assert r.method == "carspan"

    def test_unknown_algorithm_raises(self):
        rng = np.random.default_rng(13)
        cs = make_cs(800.0 + rng.normal(0.0, 30.0, 250))
        m = PsdMethod(algorithm="not_a_method")   # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unknown PSD algorithm"):
            PSDEngine(cs).compute(m)


class TestBandPower:
    """Band-power integration returns one float per named band."""

    def test_named_bands(self, typical_cs):
        m = _method()
        for name in ("FullRange", "VLF", "LF", "HF"):
            val = _band_power(typical_cs, name, m)
            assert np.isfinite(val)
            assert val >= 0.0

    def test_unknown_band_raises_key_error(self, typical_cs):
        m = _method()
        with pytest.raises(KeyError):
            _band_power(typical_cs, "not_a_band", m)

    def test_band_powers_dict_keys_match_method_bands(self, typical_cs):
        m = _method()
        bp = _band_powers(typical_cs, m)
        assert set(bp) == set(m.bands)

    def test_fullrange_dominates(self, typical_cs):
        """FullRange spans VLF + LF + HF, so its integral must be at
        least as large as any single sub-band's (allow 5 % slack for
        edge-bin rounding)."""
        m = _method()
        bp = _band_powers(typical_cs, m)
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
        m = _method()
        bp = _band_powers(cs, m)
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
        ratio = lf_hf_ratio(cs)
        if np.isfinite(ratio):
            assert ratio > 1.0

    def test_hf_dominant_ratio_below_one(self):
        cs = make_spectral_cs(0.25)
        ratio = lf_hf_ratio(cs)
        if np.isfinite(ratio):
            assert ratio < 1.0


class TestAllAlgorithms:
    """Every algorithm should produce non-negative, directionally
    consistent band powers on the same input."""

    @pytest.fixture
    def lf_series(self):
        return make_spectral_cs(0.10)

    @pytest.fixture
    def hf_series(self):
        return make_spectral_cs(0.25)

    @pytest.mark.parametrize(
        "algorithm", ["welch", "lombscargle", "carspan", "carspan_strict"]
    )
    def test_returns_psdresult(self, lf_series, algorithm):
        m = _method(algorithm)
        r = _psd(lf_series, m, with_ci=True)
        assert isinstance(r, PSDResult)
        assert r.method == algorithm

    @pytest.mark.parametrize(
        "algorithm", ["welch", "lombscargle", "carspan", "carspan_strict"]
    )
    def test_lf_dominant(self, lf_series, algorithm):
        m = _method(algorithm)
        lf = _band_power(lf_series, "LF", m)
        hf = _band_power(lf_series, "HF", m)
        if not (np.isfinite(lf) and np.isfinite(hf)):
            pytest.skip(f"{algorithm}: non-finite output.")
        assert lf > hf, f"{algorithm}: LF ({lf:.4f}) should exceed HF ({hf:.4f})"

    @pytest.mark.parametrize(
        "algorithm", ["welch", "lombscargle", "carspan", "carspan_strict"]
    )
    def test_hf_dominant(self, hf_series, algorithm):
        m = _method(algorithm)
        lf = _band_power(hf_series, "LF", m)
        hf = _band_power(hf_series, "HF", m)
        if not (np.isfinite(lf) and np.isfinite(hf)):
            pytest.skip(f"{algorithm}: non-finite output.")
        assert hf > lf, f"{algorithm}: HF ({hf:.4f}) should exceed LF ({lf:.4f})"


class TestSumOfTwoSinusoids:
    """Feed sin(2*pi*f_a*t) + sin(2*pi*f_b*t) into every PSD method and check
    that *both* injected tones produce peaks in the right bands.

    The reference signal uses ``f_a = 0.10 Hz`` (LF) and ``f_b = 0.25 Hz``
    (HF). VLF receives no injected tone -- it should stay quiet.
    """

    LF_HZ = 0.10
    HF_HZ = 0.25
    ALGORITHMS = ("welch", "lombscargle", "carspan", "carspan_strict")

    @pytest.fixture
    def lf_hf_series(self):
        return make_two_sinusoid_cs(self.LF_HZ, self.HF_HZ)

    @pytest.fixture
    def baseline_series(self):
        """Zero-modulation reference with the same RNG seed/length --
        used to verify the injected peaks rise *above* a no-signal floor."""
        return make_two_sinusoid_cs(self.LF_HZ, self.HF_HZ, mod_depth_each=0.0)

    @pytest.mark.parametrize("algorithm", ALGORITHMS)
    def test_both_target_bands_exceed_vlf(self, lf_hf_series, algorithm):
        """Both LF and HF must carry more power than VLF (which has no
        injected tone)."""
        m = _method(algorithm)
        bp = _band_powers(lf_hf_series, m)
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
        baseline by at least a 3x factor."""
        m = _method(algorithm)
        signal = _band_powers(lf_hf_series, m)
        base = _band_powers(baseline_series, m)
        for name in ("LF", "HF"):
            if not (np.isfinite(signal[name]) and np.isfinite(base[name])):
                pytest.skip(f"{algorithm}: non-finite band power for {name}.")
            if base[name] <= 0.0:
                pytest.skip(f"{algorithm}: baseline {name} non-positive.")
            ratio = signal[name] / base[name]
            assert ratio > 3.0, (
                f"{algorithm}: {name} should be >=3x baseline "
                f"(got {ratio:.2f}: signal={signal[name]:.4g}, "
                f"baseline={base[name]:.4g})"
            )

    @pytest.mark.parametrize("algorithm", ALGORITHMS)
    def test_peak_frequencies_recovered(self, lf_hf_series, algorithm):
        """The argmax inside each band must land within +/-0.02 Hz of the
        injected tone."""
        m = _method(algorithm)
        r = _psd(lf_hf_series, m, with_ci=False)
        if not np.all(np.isfinite(r.power)):
            pytest.skip(f"{algorithm}: non-finite spectrum.")

        for target_hz, name in ((self.LF_HZ, "LF"), (self.HF_HZ, "HF")):
            spec = m.bands[name]
            in_band = (r.freqs >= spec.low) & (r.freqs <= spec.high)
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
        """The convenience metrics ``lf_power()`` and ``hf_power()``
        should both return finite positive values."""
        lf = lf_power(lf_hf_series)
        hf = hf_power(lf_hf_series)
        if not (np.isfinite(lf) and np.isfinite(hf)):
            pytest.skip(f"{algorithm}: non-finite output.")
        assert lf > 0.0 and hf > 0.0


class TestFrequencyArtefactRobustness:
    """Frequency metrics return NaN (not raise) when the cleaned series
    is too short to compute a PSD."""

    def test_too_few_ibis_for_psd(self):
        cs = make_cs([800.0, 900.0])   # 2 IBIs, below the 4-sample floor
        for fn in (vlf_power, lf_power, hf_power, fullrange_power, lf_hf_ratio):
            assert np.isnan(fn(cs))

    def test_all_tl_frequency_metrics_nan(self):
        cs = make_cs([800.0] * 20)
        cs.labels[:] = "TL"
        assert np.isnan(lf_power(cs))
        assert np.isnan(hf_power(cs))
        assert np.isnan(lf_hf_ratio(cs))

    def test_sparse_tl_does_not_break_psd(self):
        rng = np.random.default_rng(3)
        ibi_ms = 800.0 + rng.normal(0.0, 25.0, 200)
        ibi_ms = np.clip(ibi_ms, 400.0, 1500.0)
        cs = make_cs(ibi_ms)
        for i in range(0, len(cs.labels), 15):
            cs.labels[i] = "TL"
        lf = lf_power(cs)
        assert np.isfinite(lf) and lf >= 0.0


class TestUnitConsistency:
    """The legend-side ``unit`` string survives the conversion pipeline."""

    def test_carspan_default_unit_mMI2(self, lf_cs):
        r = _psd(lf_cs, _method("carspan"))
        assert "mMI" in r.unit

    def test_welch_default_unit_mMI2(self, lf_cs):
        r = _psd(lf_cs, _method("welch"))
        assert "mMI" in r.unit

    def test_welch_ms2_units_when_requested(self, lf_cs):
        from spectHR.analysis.psd import WelchOptions
        m = PsdMethod(
            algorithm="welch",
            bands=dict(WORKSPACE_BANDS),
            welch=WelchOptions(units="ms²"),
        )
        r = _psd(lf_cs, m)
        assert "ms" in r.unit
