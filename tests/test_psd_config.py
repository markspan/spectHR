"""
tests/test_psd_config.py — configuration plumbing.

Covers
------
* :class:`BandSpec` — defaults, optional fields, frozenness.
* :class:`PsdMethod` — defaults, immutability, default bands.
* :func:`spectHR.config.psd_method_from_workspace` —
    f_max derivation from bands, mean_convention selection,
    silent dropping of unknown JSON keys, missing-section fall-backs.
    Imported from the headless ``spectHR.config`` module so this test
    stays Qt-free (``spectUI.workSpace`` re-exports the same function).
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from spectHR.analysis.psd import (
    BandSpec,
    PsdMethod,
    WelchOptions,
    LombscargleOptions,
    CarspanOptions,
)

from spectHR.config import psd_method_from_workspace


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


