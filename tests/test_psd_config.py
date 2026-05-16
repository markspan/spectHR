"""
tests/test_psd_config.py — configuration plumbing.

Covers
------
* :class:`BandSpec` — defaults, optional fields, frozenness.
* :class:`PsdMethod` — defaults, immutability, default bands.
* :func:`spectUI.workSpace.psd_method_from_workspace` —
    f_max derivation from bands, mean_convention selection,
    silent dropping of unknown JSON keys, missing-section fall-backs.
* :func:`PhysioData.set_psd_method` — walks ``hrv_map``, the new
    library-side replacement for the old ``apply_psd_method_to_dataset``.
* :class:`CardioSeriesView` ``psd_method`` delegation — read/write
    both reach the parent ``CardioSeries``.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from spectHR.DataSet.Series.CardioMetricsMixin import (
    BandSpec,
    PsdMethod,
)
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Series.CardioSeriesView import CardioSeriesView
from spectHR.DataSet.PhysioData import PhysioData
from spectHR.Tools.PSD.WelchPSD import WelchOptions
from spectHR.Tools.PSD.LombScarglePSD import LombscargleOptions
from spectHR.Tools.PSD.CarspanPSD import CarspanOptions

from spectUI.workSpace import psd_method_from_workspace


# ===========================================================================
# BandSpec
# ===========================================================================


class TestBandSpec:
    def test_minimum_construction(self):
        b = BandSpec(low=0.02, high=0.06)
        assert b.low == 0.02
        assert b.high == 0.06

    def test_frozen(self):
        b = BandSpec(low=0.02, high=0.06)
        with pytest.raises(FrozenInstanceError):
            b.low = 0.03   # type: ignore[misc]

    def test_no_display_attributes(self):
        """:class:`BandSpec` carries only the frequency edges; display
        attributes (colour, alpha) belong to the UI workspace dict."""
        b = BandSpec(low=0.02, high=0.5)
        assert not hasattr(b, "color")
        assert not hasattr(b, "alpha")


# ===========================================================================
# PsdMethod
# ===========================================================================


class TestPsdMethod:
    def test_defaults(self):
        m = PsdMethod()
        assert m.algorithm == "carspan"
        assert m.alpha_ci == 0.05
        assert m.mean_convention == "harmonic"
        assert isinstance(m.welch, WelchOptions)
        assert isinstance(m.lombscargle, LombscargleOptions)
        assert isinstance(m.carspan, CarspanOptions)

    def test_default_bands_present(self):
        m = PsdMethod()
        assert {"FullRange", "VLF", "LF", "HF"} <= set(m.bands)

    def test_frozen(self):
        m = PsdMethod()
        with pytest.raises(FrozenInstanceError):
            m.algorithm = "welch"   # type: ignore[misc]

    def test_independent_default_bands_per_instance(self):
        """``field(default_factory=...)`` must give each instance its
        own dict — otherwise mutation would leak across instances."""
        a = PsdMethod()
        b = PsdMethod()
        assert a.bands is not b.bands


# ===========================================================================
# Workspace builder: psd_method_from_workspace
# ===========================================================================


class TestPsdMethodFromWorkspace:
    """The UI calls this once per LoadWorkspace and once per
    Edit-Parameters save. It owns the workspace-dict → typed-dataclass
    translation."""

    def _ws(self, **overrides):
        """Build a minimal workspace dict, optionally overriding the
        FrequencyAnalysis section piecewise."""
        fa = {
            "method": "carspan",
            "bands": {
                "FullRange": {"low": 0.02, "high": 0.5, "color": "gray"},
                "VLF": {"low": 0.02, "high": 0.06, "color": "blue"},
                "LF":  {"low": 0.07, "high": 0.14, "color": "darkgreen"},
                "HF":  {"low": 0.15, "high": 0.40, "color": "red"},
            },
            "carspan": {},
            "welch": {},
            "lombscargle": {},
        }
        fa.update(overrides)
        return {"FrequencyAnalysis": fa}

    def test_algorithm_carries_through(self):
        m = psd_method_from_workspace(self._ws(method="welch"))
        assert m.algorithm == "welch"

    def test_f_max_taken_from_largest_band_high(self):
        ws = self._ws()
        ws["FrequencyAnalysis"]["bands"]["FullRange"]["high"] = 0.8
        m = psd_method_from_workspace(ws)
        assert m.carspan.f_max == 0.8

    def test_f_max_picks_max_when_fullrange_smaller_than_hf(self):
        """If a user sets FullRange.high below HF.high (mis-config), the
        builder still picks the largest band edge so HF stays inside."""
        ws = self._ws()
        ws["FrequencyAnalysis"]["bands"]["FullRange"]["high"] = 0.3
        # HF default high = 0.40, larger than the new FullRange.high.
        m = psd_method_from_workspace(ws)
        assert m.carspan.f_max == 0.40

    def test_mean_convention_harmonic_for_default(self):
        m = psd_method_from_workspace(self._ws(method="carspan"))
        assert m.mean_convention == "harmonic"

    def test_mean_convention_harmonic_for_welch(self):
        m = psd_method_from_workspace(self._ws(method="welch"))
        assert m.mean_convention == "harmonic"

    def test_mean_convention_arithmetic_for_strict(self):
        m = psd_method_from_workspace(self._ws(method="carspan_strict"))
        assert m.mean_convention == "arithmetic"

    def test_unknown_keys_silently_dropped(self):
        """Forward-compatible: extra JSON keys must not crash the
        dataclass constructor (the workspace JSON may carry keys from a
        newer version of spectHR)."""
        ws = self._ws()
        ws["FrequencyAnalysis"]["carspan"]["a_future_knob"] = 42
        ws["FrequencyAnalysis"]["welch"]["xyz"] = "unknown"
        m = psd_method_from_workspace(ws)   # must not raise
        assert m.carspan.freq_resolution == 0.01

    def test_alpha_ci_carried_through(self):
        ws = self._ws()
        ws["FrequencyAnalysis"]["confidence_interval_alpha"] = 0.10
        m = psd_method_from_workspace(ws)
        assert m.alpha_ci == 0.10

    def test_alpha_ci_defaults_when_missing(self):
        ws = self._ws()
        # No confidence_interval_alpha key at all.
        m = psd_method_from_workspace(ws)
        assert m.alpha_ci == 0.05

    def test_band_display_attrs_ignored_by_builder(self):
        """``color`` / ``alpha`` from the workspace JSON are display
        attributes; the workspace builder strips them. They survive on
        the raw workspace dict for ``PSDPlotWidget`` to consume."""
        ws = self._ws()
        ws["FrequencyAnalysis"]["bands"]["FullRange"]["alpha"] = 0.05
        ws["FrequencyAnalysis"]["bands"]["VLF"]["color"] = "navy"
        m = psd_method_from_workspace(ws)
        # The library-side BandSpec only carries the edges.
        assert m.bands["FullRange"].low == 0.02
        assert m.bands["FullRange"].high == 0.5
        assert not hasattr(m.bands["FullRange"], "alpha")
        assert not hasattr(m.bands["VLF"], "color")

    def test_empty_frequency_analysis_section_falls_back(self):
        """An entirely empty FrequencyAnalysis still produces a workable
        PsdMethod (uses defaults)."""
        m = psd_method_from_workspace({"FrequencyAnalysis": {}})
        assert m.algorithm == "carspan"
        # f_max falls through to the dataclass default (0.5) when no
        # bands are configured.
        assert m.carspan.f_max == 0.5


# ===========================================================================
# CardioSeriesView psd_method delegation
# ===========================================================================


class _StubPhysioData:
    """Lightweight PhysioData stand-in to satisfy CardioSeries[label].

    ``Epoch`` is a positional-only dataclass (``active, start, end``); no
    label field. The epoch name lives in the surrounding
    ``epochs`` dict key.
    """

    def __init__(self, epoch_start: float = 0.0, epoch_end: float = 10.0):
        from spectHR.DataSet.Epoch import Epoch
        self.epochs = {
            "rest": Epoch(True, epoch_start, epoch_end),
        }
        self.hrv_map: dict[str, CardioSeries] = {}
        self.active_band: str | None = "default"
        self.timeseries: dict = {}


def _make_master_with_pd():
    """Helper: build a CardioSeries wired into a stub PhysioData."""
    pd = _StubPhysioData()
    times = np.linspace(0.0, 10.0, 13)
    cs = CardioSeries(times)
    cs._pd = pd
    pd.hrv_map["default"] = cs
    return pd, cs


class TestViewDelegation:
    """``CardioSeriesView.psd_method`` is a property that reads and
    writes through ``self._parent.psd_method``. The master series is
    the single source of truth."""

    def test_unset_view_returns_none(self):
        _, cs = _make_master_with_pd()
        view = cs["rest"]
        assert view.psd_method is None

    def test_setting_on_parent_visible_to_view(self):
        _, cs = _make_master_with_pd()
        method = PsdMethod(algorithm="welch")
        cs.psd_method = method
        view = cs["rest"]
        assert view.psd_method is method

    def test_setting_on_view_propagates_to_parent(self):
        _, cs = _make_master_with_pd()
        view = cs["rest"]
        method = PsdMethod(algorithm="lombscargle")
        view.psd_method = method
        assert cs.psd_method is method

    def test_fresh_view_picks_up_latest_parent_value(self):
        """A view created *after* an assignment must still see the
        current value — the property delegates, not snapshots."""
        _, cs = _make_master_with_pd()
        cs.psd_method = PsdMethod(algorithm="welch")
        v_before = cs["rest"]
        assert v_before.psd_method.algorithm == "welch"
        cs.psd_method = PsdMethod(algorithm="carspan_strict")
        v_after = cs["rest"]
        # And the already-built view sees the new value too.
        assert v_before.psd_method.algorithm == "carspan_strict"
        assert v_after.psd_method.algorithm == "carspan_strict"


# ===========================================================================
# PhysioData.set_psd_method
# ===========================================================================


class TestPhysioDataSetPsdMethod:
    """The library now owns the per-dataset walk that the UI used to do
    in spectUI/workSpace.py."""

    def test_walks_hrv_map(self):
        pd = _StubPhysioData()
        cs1 = CardioSeries(np.linspace(0.0, 10.0, 13))
        cs2 = CardioSeries(np.linspace(0.0, 10.0, 13))
        pd.hrv_map = {"band1": cs1, "band2": cs2}
        m = PsdMethod(algorithm="welch")
        PhysioData.set_psd_method(pd, m)
        assert cs1.psd_method is m
        assert cs2.psd_method is m

    def test_empty_hrv_map_no_error(self):
        pd = _StubPhysioData()
        pd.hrv_map = {}
        m = PsdMethod()
        PhysioData.set_psd_method(pd, m)   # must not raise

    def test_views_pick_up_the_pushed_method(self):
        """Setting on the master must be visible to per-epoch views."""
        pd, cs = _make_master_with_pd()
        m = PsdMethod(algorithm="carspan_strict", mean_convention="arithmetic")
        PhysioData.set_psd_method(pd, m)
        view = cs["rest"]
        assert view.psd_method is m
        assert view.psd_method.mean_convention == "arithmetic"
