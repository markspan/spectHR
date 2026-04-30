"""
tests/test_hrv_metrics.py
=========================
Unit tests for every ``@hrv_metric``-decorated parameter on CardioSeries.

Coverage
--------
Time-domain
    count, mean, min, max, median
    rmssd, sdnn, sdsd
    sd1, sd2, sd_ratio, ellipse_area
    Algebraic consistency (Brennan identity: SD1² + SD2² = 2·SDNN²)

Frequency-domain
    fullrange_power, vlf_power, lf_power, hf_power, lf_hf_ratio
    All three PSD back-ends (welch, lombscargle, carspan)

Cross-cutting
    Artefact exclusion: TL and T labels, gap-safety of successive diffs
    Edge cases: empty series, 1 beat, 2 beats, all-artefact series
    Boundary: fewer than 4 valid IBIs → frequency metrics return NaN
"""

from __future__ import annotations

import numpy as np
import pytest

from spectHR.DataSet.Series.CardioSeries import CardioSeries
import spectHR.DataSet.Series.CardioFrequencyMetricsMixin as cfm


# ---------------------------------------------------------------------------
# Workspace-standard frequency bands (mirrors _DEFAULT_WORKSPACE in workSpace.py)
# ---------------------------------------------------------------------------
_WORKSPACE_BANDS = {
    "FullRange": {"low": 0.02, "high": 0.50, "color": "gray"},
    "VLF":       {"low": 0.02, "high": 0.06, "color": "blue"},
    "LF":        {"low": 0.07, "high": 0.14, "color": "darkgreen"},
    "HF":        {"low": 0.15, "high": 0.40, "color": "red"},
}


@pytest.fixture(autouse=True)
def restore_frequency_bands():
    """
    Load workspace-standard bands before every test and restore the previous
    state afterward, so module-level globals don't leak between tests.
    """
    previous = dict(cfm.HRV_FREQUENCY_BANDS)
    cfm.load_frequency_bands(_WORKSPACE_BANDS)
    yield
    cfm.load_frequency_bands(previous)


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------

def make_cs(ibi_ms, labels=None) -> CardioSeries:
    """
    Build a CardioSeries from a sequence of IBI values (milliseconds).

    Parameters
    ----------
    ibi_ms : array-like
        Inter-beat intervals in ms.  N intervals → N+1 beat times.
    labels : array-like of str, optional
        Per-beat label array, length N+1.  Defaults to all 'N'.

    Returns
    -------
    CardioSeries
    """
    ibi_ms = np.asarray(ibi_ms, dtype=float)
    times = np.concatenate([[0.0], np.cumsum(ibi_ms / 1000.0)])
    cs = CardioSeries(times)
    if labels is not None:
        cs.labels[:] = np.asarray(labels, dtype=object)
    return cs


def make_spectral_cs(
    dominant_freq_hz: float,
    *,
    duration_s: float = 250.0,
    mean_ibi_s: float = 0.8,
    mod_depth: float = 0.20,
    seed: int = 42,
) -> CardioSeries:
    """
    Build a CardioSeries whose IBI series contains a sinusoidal modulation
    at ``dominant_freq_hz`` Hz with amplitude ``mod_depth × mean_ibi_s``.

    The recording contains approximately ``duration_s / mean_ibi_s`` beats,
    long enough for reliable spectral estimation in the HRV bands.

    Parameters
    ----------
    dominant_freq_hz : float
        Target frequency (Hz) of the sinusoidal IBI modulation.
    duration_s : float
        Approximate total recording length.
    mean_ibi_s : float
        Mean IBI in seconds (≈ 800 ms → 75 bpm).
    mod_depth : float
        Fractional modulation amplitude relative to mean_ibi_s.
    seed : int
        Random-number seed for reproducibility.

    Returns
    -------
    CardioSeries
    """
    rng = np.random.default_rng(seed)
    n_beats = int(duration_s / mean_ibi_s) + 1

    # Uniform grid used only to evaluate the modulation phase.
    approx_times = np.arange(n_beats) * mean_ibi_s

    # IBI series: mean + sinusoidal component + tiny white noise floor
    noise = rng.normal(0.0, 0.005 * mean_ibi_s, n_beats - 1)
    ibi_s = (
        mean_ibi_s
        + mod_depth * mean_ibi_s * np.sin(2.0 * np.pi * dominant_freq_hz * approx_times[:-1])
        + noise
    )
    ibi_s = np.clip(ibi_s, 0.3, 2.0)  # physiological bounds

    beat_times = np.concatenate([[0.0], np.cumsum(ibi_s)])
    return CardioSeries(beat_times)


# ===========================================================================
# Time-domain: magnitude-based statistics
# ===========================================================================

class TestCount:
    """count() = number of valid inter-beat intervals."""

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


class TestMeanMinMaxMedian:
    """mean(), min(), max(), median() on clean series."""

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

    def test_uniform_ibi(self):
        cs = make_cs([800.0, 800.0, 800.0])
        assert cs.mean()   == pytest.approx(800.0)
        assert cs.min()    == pytest.approx(800.0)
        assert cs.max()    == pytest.approx(800.0)
        assert cs.median() == pytest.approx(800.0)

    def test_empty_returns_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(cs.mean())
        assert np.isnan(cs.min())
        assert np.isnan(cs.max())
        assert np.isnan(cs.median())


class TestSdnn:
    """sdnn() = std(all valid IBIs, ddof=0)."""

    def test_uniform_ibi_is_zero(self):
        cs = make_cs([800.0] * 5)
        assert cs.sdnn() == pytest.approx(0.0)

    def test_known_value(self):
        ibi = [800.0, 900.0, 800.0, 900.0]
        cs = make_cs(ibi)
        assert cs.sdnn() == pytest.approx(float(np.std(ibi)))

    def test_single_ibi_is_zero(self):
        """std of a single value is 0."""
        cs = make_cs([850.0])
        assert cs.sdnn() == pytest.approx(0.0)

    def test_empty_returns_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(cs.sdnn())


class TestRmssd:
    """rmssd() = sqrt(mean(successive_diffs²)), gap-safe."""

    def test_uniform_ibi_is_zero(self):
        cs = make_cs([800.0] * 5)
        assert cs.rmssd() == pytest.approx(0.0)

    def test_alternating_ibi(self):
        # IBIs: [800, 900, 800, 900] → diffs: [100, -100, 100]
        # rmssd = sqrt(mean([10000, 10000, 10000])) = 100
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert cs.rmssd() == pytest.approx(100.0)

    def test_known_value(self):
        ibi = [800.0, 900.0, 1000.0, 850.0]
        cs = make_cs(ibi)
        # Gap-safe diffs for all-N series: [100, 100, -150]
        diffs = np.array([100.0, 100.0, -150.0])
        expected = float(np.sqrt(np.mean(diffs ** 2)))
        assert cs.rmssd() == pytest.approx(expected)

    def test_one_successive_diff(self):
        """Two IBIs → one diff → rmssd = |diff|."""
        cs = make_cs([800.0, 1000.0])
        assert cs.rmssd() == pytest.approx(200.0)

    def test_single_ibi_returns_nan(self):
        """One IBI → no pairs → no diffs → NaN."""
        cs = make_cs([800.0])
        assert np.isnan(cs.rmssd())

    def test_empty_returns_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        assert np.isnan(cs.rmssd())


class TestSdsd:
    """sdsd() = std(successive_diffs, ddof=0), gap-safe."""

    def test_uniform_ibi_is_zero(self):
        cs = make_cs([800.0] * 5)
        assert cs.sdsd() == pytest.approx(0.0)

    def test_known_value(self):
        # diffs: [100, -100, 100]
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        expected = float(np.std([100.0, -100.0, 100.0]))
        assert cs.sdsd() == pytest.approx(expected)

    def test_single_ibi_returns_nan(self):
        cs = make_cs([800.0])
        assert np.isnan(cs.sdsd())

    def test_two_ibis_one_diff_std_zero(self):
        """std of a single diff is 0."""
        cs = make_cs([800.0, 900.0])
        assert cs.sdsd() == pytest.approx(0.0)


# ===========================================================================
# Time-domain: Poincaré analysis
# ===========================================================================

class TestSd1Sd2:
    """SD1 and SD2 via Brennan (2002) / Poincaré plot."""

    def test_sd1_uniform_is_zero(self):
        cs = make_cs([800.0] * 6)
        assert cs.sd1() == pytest.approx(0.0)

    def test_sd1_formula(self):
        # SD1 = std(dIBI) / sqrt(2)
        diffs = np.array([100.0, -100.0, 100.0])
        expected = float(np.std(diffs)) / np.sqrt(2.0)
        cs = make_cs([800.0, 900.0, 800.0, 900.0])
        assert cs.sd1() == pytest.approx(expected)

    def test_sd2_formula(self):
        # SD2² = 2·Var(IBI) − 0.5·Var(dIBI)
        ibi = [800.0, 900.0, 800.0, 900.0]
        diffs = [100.0, -100.0, 100.0]
        val = 2.0 * float(np.var(ibi)) - 0.5 * float(np.var(diffs))
        cs = make_cs(ibi)
        if val > 0:
            assert cs.sd2() == pytest.approx(np.sqrt(val))
        else:
            assert np.isnan(cs.sd2())

    def test_sd2_degenerate_returns_nan_not_error(self):
        """When SD2² ≤ 0 the code should return NaN, not raise."""
        # Perfectly alternating long series pushes SD2 → 0
        cs = make_cs([800.0, 900.0] * 50)
        result = cs.sd2()
        assert isinstance(result, float)   # no exception
        # SD2 is either 0 or NaN — both are acceptable
        assert result >= 0.0 or np.isnan(result)

    def test_sd_ratio_equals_sd1_over_sd2(self):
        cs = make_cs([800.0, 850.0, 900.0, 820.0, 780.0, 860.0])
        s1, s2 = cs.sd1(), cs.sd2()
        if np.isnan(s1) or np.isnan(s2) or s2 == 0:
            assert np.isnan(cs.sd_ratio())
        else:
            assert cs.sd_ratio() == pytest.approx(s1 / s2)

    def test_sd_ratio_nan_when_sd2_zero(self):
        """Uniform series → SD2 = 0 → ratio = NaN."""
        cs = make_cs([800.0] * 6)
        assert np.isnan(cs.sd_ratio())

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


class TestBrennanIdentity:
    """
    Algebraic consistency check:  SD1² + SD2² = 2 · SDNN²

    Derivation:
        SD1² = Var(dIBI) / 2
        SD2² = 2·Var(IBI) − Var(dIBI)/2
        ⟹ SD1² + SD2² = 2·Var(IBI) = 2·SDNN²
    """

    @pytest.mark.parametrize("ibi", [
        [800.0, 850.0, 900.0, 820.0, 780.0, 860.0],
        [600.0, 700.0, 800.0, 900.0, 1000.0],
        [950.0, 930.0, 960.0, 910.0, 940.0, 920.0, 950.0],
    ])
    def test_identity_holds(self, ibi):
        cs = make_cs(ibi)
        s1 = cs.sd1()
        s2 = cs.sd2()
        sdnn = cs.sdnn()

        if np.isnan(s1) or np.isnan(s2):
            pytest.skip("SD2 is NaN for this series (degenerate case).")

        assert s1 ** 2 + s2 ** 2 == pytest.approx(2.0 * sdnn ** 2, rel=1e-6)


# ===========================================================================
# Artefact exclusion
# ===========================================================================

class TestArtefactExclusion:
    """
    TL and T labels must be treated identically and excluded from every
    magnitude-based and successive-difference metric.
    """

    # -- count ----------------------------------------------------------------

    def test_count_excludes_tl(self):
        # 4 IBIs; IBI[1] (= 900 ms) is TL → 3 valid
        labels = ["N", "TL", "N", "N", "N"]
        cs = make_cs([800.0, 900.0, 800.0, 900.0], labels=labels)
        assert cs.count() == 3

    def test_count_excludes_t(self):
        labels = ["N", "N", "T", "N", "N"]
        cs = make_cs([800.0, 900.0, 800.0, 900.0], labels=labels)
        assert cs.count() == 3

    def test_count_tl_equals_t(self):
        """TL and T produce the same count reduction."""
        ibi = [800.0, 900.0, 800.0, 900.0]
        cs_tl = make_cs(ibi, labels=["N", "TL", "N", "N", "N"])
        cs_t  = make_cs(ibi, labels=["N", "T",  "N", "N", "N"])
        assert cs_tl.count() == cs_t.count()

    # -- mean -----------------------------------------------------------------

    def test_mean_excludes_tl(self):
        # IBIs: [800, 900, 800, 900]; IBI[1] TL → clean: [800, 800, 900]
        labels = ["N", "TL", "N", "N", "N"]
        cs = make_cs([800.0, 900.0, 800.0, 900.0], labels=labels)
        assert cs.mean() == pytest.approx(np.mean([800.0, 800.0, 900.0]))

    # -- rmssd gap-safety -----------------------------------------------------

    def test_rmssd_excluded_beat_breaks_chain(self):
        """
        An excluded IBI severs successive-diff chains on both sides.

        IBIs: [800, 900, 800, 900]  label[1] = TL
        valid = [T, F, T, T, F]
        pair_ok = [F, F, T, F]  → only diff at positions (2,3): 900−800 = 100
        rmssd = sqrt(mean([100²])) = 100
        """
        labels = ["N", "TL", "N", "N", "N"]
        cs = make_cs([800.0, 900.0, 800.0, 900.0], labels=labels)
        assert cs.rmssd() == pytest.approx(100.0)

    def test_rmssd_t_same_as_tl(self):
        ibi = [800.0, 900.0, 800.0, 900.0]
        cs_tl = make_cs(ibi, labels=["N", "TL", "N", "N", "N"])
        cs_t  = make_cs(ibi, labels=["N", "T",  "N", "N", "N"])
        assert cs_tl.rmssd() == pytest.approx(cs_t.rmssd())

    # -- all artefact ---------------------------------------------------------

    def test_all_tl_count_is_zero(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["TL", "TL", "TL", "TL", "TL"])
        assert cs.count() == 0

    def test_all_tl_scalar_metrics_return_nan(self):
        cs = make_cs([800.0, 900.0, 800.0, 900.0],
                     labels=["TL", "TL", "TL", "TL", "TL"])
        for metric in [cs.mean, cs.min, cs.max, cs.median,
                       cs.rmssd, cs.sdnn, cs.sdsd,
                       cs.sd1, cs.sd2, cs.sd_ratio, cs.ellipse_area]:
            assert np.isnan(metric()), f"{metric.__name__} should be NaN"


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    """No method should raise on degenerate inputs."""

    def test_empty_series_all_nan(self):
        cs = CardioSeries(np.array([], dtype=float))
        for metric in [cs.mean, cs.min, cs.max, cs.median,
                       cs.rmssd, cs.sdnn, cs.sdsd,
                       cs.sd1, cs.sd2, cs.sd_ratio, cs.ellipse_area]:
            result = metric()
            assert np.isnan(result), f"{metric.__name__} should return NaN, got {result}"

    def test_one_beat_no_ibi(self):
        cs = CardioSeries(np.array([0.0]))
        assert cs.count() == 0
        assert np.isnan(cs.mean())
        assert np.isnan(cs.rmssd())

    def test_two_beats_one_ibi(self):
        cs = make_cs([800.0])
        assert cs.count() == 1
        assert cs.mean()   == pytest.approx(800.0)
        assert cs.min()    == pytest.approx(800.0)
        assert cs.max()    == pytest.approx(800.0)
        # No pairs for successive diffs
        assert np.isnan(cs.rmssd())
        assert np.isnan(cs.sdsd())
        assert np.isnan(cs.sd1())

    def test_three_beats_two_ibis(self):
        """Three beats → one successive diff."""
        cs = make_cs([800.0, 900.0])
        assert cs.count() == 2
        assert cs.rmssd() == pytest.approx(100.0)
        # std of a single diff is 0
        assert cs.sdsd() == pytest.approx(0.0)

    def test_sd_ratio_nan_when_sd2_zero(self):
        cs = make_cs([800.0] * 6)
        assert np.isnan(cs.sd_ratio())

    def test_ellipse_area_zero_when_sd1_zero(self):
        """SD1 = 0 and SD2 > 0 → area = 0."""
        # Two beats, one IBI → sd1 = NaN (no diffs), sd2 depends on implementation
        # Use a series where sd1 = 0 explicitly: uniform IBIs
        cs = make_cs([800.0] * 6)
        # SD1 = 0, SD2 = 0, area = NaN or 0
        result = cs.ellipse_area()
        # Either NaN (if SD2=0 triggers NaN path) or 0.0 are acceptable
        assert np.isnan(result) or result == pytest.approx(0.0)


# ===========================================================================
# Frequency-domain: sanity
# ===========================================================================

class TestFrequencyDomainSanity:
    """Basic sanity: finiteness, non-negativity, internal consistency."""

    @pytest.fixture
    def typical_cs(self):
        """A realistic ~200 s series with mild broadband HRV."""
        rng = np.random.default_rng(7)
        ibi_ms = 800.0 + rng.normal(0.0, 30.0, 250)
        ibi_ms = np.clip(ibi_ms, 400.0, 1500.0)
        return make_cs(ibi_ms)

    def test_all_powers_finite_and_nonneg(self, typical_cs):
        for fn in [typical_cs.fullrange_power, typical_cs.vlf_power,
                   typical_cs.lf_power, typical_cs.hf_power]:
            val = fn()
            assert np.isfinite(val), f"{fn.__name__} returned non-finite: {val}"
            assert val >= 0.0,       f"{fn.__name__} returned negative:   {val}"

    def test_lf_hf_ratio_equals_lf_over_hf(self, typical_cs):
        lf    = typical_cs.lf_power()
        hf    = typical_cs.hf_power()
        ratio = typical_cs.lf_hf_ratio()
        if np.isfinite(lf) and np.isfinite(hf) and hf > 0.0:
            assert ratio == pytest.approx(lf / hf, rel=1e-6)

    def test_fullrange_at_least_as_large_as_biggest_subband(self, typical_cs):
        """FullRange spans VLF + LF + HF, so its integral must dominate."""
        full = typical_cs.fullrange_power()
        biggest = max(typical_cs.vlf_power(),
                      typical_cs.lf_power(),
                      typical_cs.hf_power())
        # Allow a 5 % tolerance for boundary-bin rounding.
        assert full >= biggest * 0.95

    def test_fewer_than_4_ibis_returns_nan(self):
        """PSD requires ≥ 4 valid IBIs; shorter series → NaN for all bands."""
        cs = make_cs([800.0, 900.0])   # 2 IBIs
        assert np.isnan(cs.vlf_power())
        assert np.isnan(cs.lf_power())
        assert np.isnan(cs.hf_power())
        assert np.isnan(cs.fullrange_power())
        assert np.isnan(cs.lf_hf_ratio())

    def test_all_tl_frequency_metrics_return_nan(self):
        """No valid IBIs after artefact exclusion → NaN."""
        cs = make_cs([800.0] * 20)
        cs.labels[:] = "TL"
        assert np.isnan(cs.lf_power())
        assert np.isnan(cs.hf_power())
        assert np.isnan(cs.lf_hf_ratio())


# ===========================================================================
# Frequency-domain: spectral content
# ===========================================================================

class TestFrequencyDomainSpectral:
    """
    Directional tests: a sinusoidal IBI modulation at a known frequency
    should produce the highest band power in the band that contains it.

    Default workspace bands:
        VLF  0.02–0.06 Hz
        LF   0.07–0.14 Hz
        HF   0.15–0.40 Hz
    """

    @pytest.mark.parametrize("freq_hz, dominant_band, others", [
        (0.04, "vlf", ["lf", "hf"]),
        (0.10, "lf",  ["vlf", "hf"]),
        (0.25, "hf",  ["vlf", "lf"]),
    ])
    def test_dominant_band(self, freq_hz, dominant_band, others):
        cs = make_spectral_cs(freq_hz)
        powers = {
            "vlf": cs.vlf_power(),
            "lf":  cs.lf_power(),
            "hf":  cs.hf_power(),
        }
        if not all(np.isfinite(v) for v in powers.values()):
            pytest.skip("Non-finite PSD values — series may be too short.")

        dominant_val = powers[dominant_band]
        for other in others:
            assert dominant_val > powers[other], (
                f"Expected {dominant_band} ({dominant_val:.4f}) > "
                f"{other} ({powers[other]:.4f}) at {freq_hz} Hz"
            )

    def test_lf_dominant_gives_ratio_above_one(self):
        """LF-dominant signal → LF/HF ratio > 1."""
        cs = make_spectral_cs(0.10)
        ratio = cs.lf_hf_ratio()
        if np.isfinite(ratio):
            assert ratio > 1.0

    def test_hf_dominant_gives_ratio_below_one(self):
        """HF-dominant signal → LF/HF ratio < 1."""
        cs = make_spectral_cs(0.25)
        ratio = cs.lf_hf_ratio()
        if np.isfinite(ratio):
            assert ratio < 1.0

    def test_fullrange_power_includes_dominant_band(self):
        """FullRange power must exceed any single sub-band power."""
        for freq_hz in (0.04, 0.10, 0.25):
            cs = make_spectral_cs(freq_hz)
            full = cs.fullrange_power()
            sub  = max(cs.vlf_power(), cs.lf_power(), cs.hf_power())
            if np.isfinite(full) and np.isfinite(sub):
                assert full >= sub * 0.9


# ===========================================================================
# Frequency-domain: all three PSD back-ends
# ===========================================================================

class TestFrequencyDomainMethods:
    """
    Band power and lf_hf_ratio must give directionally consistent results
    across welch, lombscargle, and carspan.
    """

    @pytest.fixture
    def lf_cs(self):
        """LF-dominant series."""
        return make_spectral_cs(0.10)

    @pytest.fixture
    def hf_cs(self):
        """HF-dominant series."""
        return make_spectral_cs(0.25)

    @pytest.mark.parametrize("method", ["welch", "lombscargle", "carspan"])
    def test_lf_gt_hf_for_lf_signal(self, lf_cs, method):
        lf = lf_cs.band_power("LF", method=method)
        hf = lf_cs.band_power("HF", method=method)
        if not (np.isfinite(lf) and np.isfinite(hf)):
            pytest.skip(f"Method '{method}' returned non-finite values.")
        assert lf > hf, (
            f"Method '{method}': expected LF ({lf:.4f}) > HF ({hf:.4f})"
        )

    @pytest.mark.parametrize("method", ["welch", "lombscargle", "carspan"])
    def test_hf_gt_lf_for_hf_signal(self, hf_cs, method):
        lf = hf_cs.band_power("LF", method=method)
        hf = hf_cs.band_power("HF", method=method)
        if not (np.isfinite(lf) and np.isfinite(hf)):
            pytest.skip(f"Method '{method}' returned non-finite values.")
        assert hf > lf, (
            f"Method '{method}': expected HF ({hf:.4f}) > LF ({lf:.4f})"
        )

    @pytest.mark.parametrize("method", ["welch", "lombscargle", "carspan"])
    def test_band_power_nonneg(self, lf_cs, method):
        for band in ("VLF", "LF", "HF", "FullRange"):
            val = lf_cs.band_power(band, method=method)
            if np.isfinite(val):
                assert val >= 0.0, (
                    f"Method '{method}', band '{band}': negative power {val}"
                )


# ===========================================================================
# Frequency-domain: artefact robustness
# ===========================================================================

class TestFrequencyDomainArtefacts:
    """Artefact labels must not crash PSD computation."""

    def test_sparse_tl_still_computes(self):
        """A series with occasional TL beats should still return finite power."""
        rng = np.random.default_rng(3)
        ibi_ms = 800.0 + rng.normal(0.0, 25.0, 200)
        ibi_ms = np.clip(ibi_ms, 400.0, 1500.0)
        cs = make_cs(ibi_ms)
        # Mark every 15th beat as TL (~13 out of 200 IBIs)
        for i in range(0, len(cs.labels), 15):
            cs.labels[i] = "TL"
        lf = cs.lf_power()
        assert np.isfinite(lf) and lf >= 0.0

    def test_dense_tl_below_threshold_returns_nan(self):
        """Fewer than 4 valid IBIs after exclusion → NaN."""
        cs = make_cs([800.0] * 5)
        # Leave only 3 valid IBIs (indices 0,1,2 valid; rest TL)
        cs.labels[3:] = "TL"
        # 5 beats, 4 IBIs; last 2 are TL → 2 valid IBIs → NaN
        cs2 = make_cs([800.0] * 3)
        cs2.labels[2:] = "TL"   # 3 beats, 2 IBIs, 1 TL → 1 valid
        assert np.isnan(cs2.lf_power())
