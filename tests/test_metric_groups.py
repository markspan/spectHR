# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# tests/test_metric_groups.py
"""
Tests for the multi-column metric-group registry and the analysis-layer
scalar-flattening helpers.

These cover the parameters whose CSV column *set* is data-driven and therefore
cannot be a single-valued ``@epoch_metric``:

* ``band_powers`` - an ``@epoch_metric_group`` emitting one ``{band}_power``
  column for every non-standard configured band (reuses the cached PSD).
* ``profile_summary_scalars`` / ``transfer_summary_scalars`` - pure functions
  that turn a ProfileResult / TransferResult into the named scalar columns the
  parameters export writes, so the column naming lives in the analysis layer.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectHR.analysis.psd import BandSpec, PsdMethod
from spectHR.analysis.psd._utils import ProfileResult
from spectHR.analysis.epoch_context import EpochContext
from spectHR.analysis.registry import (
    epoch_metric_group,
    get_metric_groups,
)
from spectHR.analysis.frequency_metrics import (
    band_powers,
    STANDARD_BAND_POWER_COLUMNS,
)
from spectHR.analysis.profile import profile_summary_scalars
from spectHR.analysis.transfer import (
    BandTransfer,
    TransferResult,
    transfer_summary_scalars,
)

from conftest import WORKSPACE_BANDS, make_spectral_cs


# ===========================================================================
# Group-metric registry
# ===========================================================================

class TestGroupRegistry:
    def test_band_powers_is_registered(self):
        assert "band_powers" in get_metric_groups()
        assert get_metric_groups()["band_powers"] is band_powers

    def test_get_metric_groups_returns_copy(self):
        snap = get_metric_groups()
        snap["bogus"] = lambda ctx: {}
        assert "bogus" not in get_metric_groups()

    def test_duplicate_group_name_rejected(self):
        with pytest.raises(ValueError):
            @epoch_metric_group
            def band_powers(ctx):   # noqa: F811 - clashes with the real one
                return {}


# ===========================================================================
# band_powers group metric
# ===========================================================================

def _method_with_custom_band() -> PsdMethod:
    """Workspace bands plus one renamed/extra band ('MyBand')."""
    bands = dict(WORKSPACE_BANDS)
    bands["MyBand"] = BandSpec(low=0.10, high=0.20)
    return PsdMethod(algorithm="carspan", bands=bands, mean_convention="harmonic")


class TestBandPowersGroup:
    def test_emits_only_non_standard_bands(self):
        cs = make_spectral_cs(0.25)
        ctx = EpochContext(cs, psd_method=_method_with_custom_band())
        cols = band_powers(ctx)
        # The custom band gets a column ...
        assert "myband_power" in cols
        assert np.isfinite(cols["myband_power"])
        # ... and the standard bands never do (those are single-valued metrics).
        for std in STANDARD_BAND_POWER_COLUMNS:
            assert std not in cols

    def test_empty_when_no_method(self):
        cs = make_spectral_cs(0.25)
        ctx = EpochContext(cs, psd_method=None)
        assert band_powers(ctx) == {}

    def test_only_standard_bands_gives_no_columns(self):
        cs = make_spectral_cs(0.25)
        method = PsdMethod(
            algorithm="carspan",
            bands=dict(WORKSPACE_BANDS),     # FullRange/VLF/LF/HF only
            mean_convention="harmonic",
        )
        ctx = EpochContext(cs, psd_method=method)
        assert band_powers(ctx) == {}

    def test_reuses_cached_psd(self):
        # band_powers must not trigger a second PSD computation: it reads the
        # context's cached psd, identical to the standard band-power metrics.
        cs = make_spectral_cs(0.25)
        ctx = EpochContext(cs, psd_method=_method_with_custom_band())
        _ = ctx.psd          # prime the cache
        cached = ctx.psd
        band_powers(ctx)
        assert ctx.psd is cached


# ===========================================================================
# profile_summary_scalars
# ===========================================================================

def _profile_result() -> ProfileResult:
    return ProfileResult(
        timestamps=np.array([10.0, 20.0, 30.0]),
        band_names=["LF", "HF"],
        band_power=np.array([[1.0, 3.0, 2.0], [0.5, 0.5, np.nan]]),
        unit="mMI²",
        method="carspan",
        window_s=64.0,
        step_s=10.0,
        resp_freqs=None,
    )


class TestProfileSummaryScalars:
    def test_per_band_and_metadata_columns(self):
        pr = _profile_result()
        t_rel = pr.timestamps
        out = profile_summary_scalars(
            pr, t_rel,
            emit_bands=["LF", "HF"],
            window_s=64.0, step_s=10.0,
        )
        # LF stats over [1, 3, 2]
        assert out["LF_prof_mean"] == pytest.approx(2.0)
        assert out["LF_prof_min"] == pytest.approx(1.0)
        assert out["LF_prof_max"] == pytest.approx(3.0)
        assert out["LF_prof_t_max"] == pytest.approx(20.0)   # window of the max
        # HF ignores the NaN window
        assert out["HF_prof_mean"] == pytest.approx(0.5)
        # Metadata
        assert out["prof_method"] == "carspan"
        assert out["prof_unit"] == "mMI²"
        assert out["prof_window_s"] == 64.0
        assert out["prof_step_s"] == 10.0
        assert out["prof_n_windows"] == 3

    def test_emit_bands_filters_and_orders(self):
        pr = _profile_result()
        out = profile_summary_scalars(
            pr, pr.timestamps, emit_bands=["HF"], window_s=64.0, step_s=10.0,
        )
        assert any(k.startswith("HF_prof_") for k in out)
        assert not any(k.startswith("LF_prof_") for k in out)

    def test_unknown_emit_band_skipped(self):
        pr = _profile_result()
        out = profile_summary_scalars(
            pr, pr.timestamps, emit_bands=["NOPE"], window_s=64.0, step_s=10.0,
        )
        assert not any("_prof_mean" in k for k in out)   # no band columns

    def test_adaptive_columns_only_when_named(self):
        pr = _profile_result()
        without = profile_summary_scalars(
            pr, pr.timestamps, window_s=64.0, step_s=10.0,
        )
        assert "prof_adaptive_band" not in without
        with_ad = profile_summary_scalars(
            pr, pr.timestamps, window_s=64.0, step_s=10.0,
            adaptive_band_name="RSP", adaptive_source="icg",
        )
        assert with_ad["prof_adaptive_band"] == "RSP"
        assert with_ad["prof_adaptive_source"] == "icg"


# ===========================================================================
# transfer_summary_scalars
# ===========================================================================

def _transfer_result() -> TransferResult:
    bt = BandTransfer(
        weighted_coherence=0.8,
        modulus=12.5,
        phase=0.3,
        phase_unwrapped=0.3,
        n_points=10,
        n_coherent=7,
    )
    return TransferResult(
        freqs=np.linspace(0.0, 0.5, 11),
        modulus=np.ones(11),
        phase_wrapped=np.zeros(11),
        phase_unwrapped=np.zeros(11),
        coherence=np.ones(11),
        freq_resolution=0.05,
        method="carspan_transfer",
        band_results={"LF": bt},
    )


class TestTransferSummaryScalars:
    def test_per_band_and_metadata_columns(self):
        out = transfer_summary_scalars(
            _transfer_result(), smooth=True, min_coherence=0.5, f_max=0.4,
        )
        assert out["LF_tf_modulus"] == pytest.approx(12.5)
        assert out["LF_tf_phase_w"] == pytest.approx(0.3)
        assert out["LF_tf_phase_u"] == pytest.approx(0.3)
        assert out["LF_tf_coherence"] == pytest.approx(0.8)
        assert out["LF_tf_n_points"] == 10
        assert out["LF_tf_n_coherent"] == 7
        assert out["tf_method"] == "carspan_transfer"
        assert out["tf_freq_resolution"] == pytest.approx(0.05)
        assert out["tf_smooth"] == 1
        assert out["tf_min_coherence"] == pytest.approx(0.5)
        assert out["tf_f_max"] == pytest.approx(0.4)

    def test_no_band_results_gives_metadata_only(self):
        tr = _transfer_result()
        tr = TransferResult(
            freqs=tr.freqs, modulus=tr.modulus,
            phase_wrapped=tr.phase_wrapped, phase_unwrapped=tr.phase_unwrapped,
            coherence=tr.coherence, freq_resolution=tr.freq_resolution,
            method=tr.method, band_results=None,
        )
        out = transfer_summary_scalars(
            tr, smooth=False, min_coherence=0.5, f_max=0.4,
        )
        assert not any(k.startswith("LF_tf_") for k in out)
        assert out["tf_smooth"] == 0
        assert out["tf_method"] == "carspan_transfer"
