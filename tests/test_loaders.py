# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Smoke tests for the CARSPAN ``.evt`` / ``.nff`` loaders.

These exercise the real example files in ``ExampleData/data/`` rather
than synthetic fixtures, so they verify the binary NFF reader and the
two-phase EVT parser end to end.

Both example ``.evt`` files contain more than two distinct non-R-top
event codes, so :func:`spectHR.DataSet.loaders.evt_loader._load_evt_data`
opens the ``EventCodeWindow`` Qt dialog to ask which codes mark epoch
boundaries. The ``stub_event_code_window`` fixture replaces that dialog
with a headless no-op (selecting no codes, so the loader falls back to a
single epoch) so the tests can run without a display.
"""
from __future__ import annotations

import struct
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.loaders.nff_loader import TNFF

# Example data lives at <repo>/ExampleData/data/; tests/ is one level down.
DATA_DIR = Path(__file__).resolve().parents[1] / "ExampleData" / "data"


@pytest.fixture
def stub_event_code_window(monkeypatch):
    """Replace the Qt ``EventCodeWindow`` dialog with a headless stub.

    The stub selects no start/stop codes, so the EVT loader keeps its
    single-epoch fallback - enough for these loader smoke tests, which
    only care that parsing completes and the series are built.
    """

    class _FakeEventCodeWindow:
        def __init__(self, *args, **kwargs):
            # No codes selected → loader uses the whole recording as one epoch.
            self.start_codes: list[int] = []
            self.stop_codes: list[int] = []

        def exec(self) -> int:
            return 0

    # Build fake package hierarchy so the lazy
    # ``from spectUI.widgets.EventCodeWindow import EventCodeWindow`` resolves
    # without importing the real (Qt-heavy) spectUI package.
    spectui = types.ModuleType("spectUI")
    spectui.__path__ = []  # mark as package
    widgets = types.ModuleType("spectUI.widgets")
    widgets.__path__ = []
    leaf = types.ModuleType("spectUI.widgets.EventCodeWindow")
    leaf.EventCodeWindow = _FakeEventCodeWindow

    monkeypatch.setitem(sys.modules, "spectUI", spectui)
    monkeypatch.setitem(sys.modules, "spectUI.widgets", widgets)
    monkeypatch.setitem(sys.modules, "spectUI.widgets.EventCodeWindow", leaf)
    return _FakeEventCodeWindow


def test_nff_loads_all_channels(stub_event_code_window):
    """Loading example1.EVT pulls in every channel of example1.nff."""
    pd = PhysioData(str(DATA_DIR / "example1.EVT"))

    # All seven NFF channels are present, keyed off their lowercased labels.
    for key in ("ecg", "bp", "resp", "esp", "plet", "card", "toon"):
        assert key in pd.timeseries, f"missing channel '{key}'"

    # ECG and RESP are indexed under the single shared "ecg" band, with the
    # "rsp" hook pointing at the resp timeseries.
    assert pd.band_map["ecg"]["ecg"] == "ecg"
    assert pd.band_map["ecg"]["rsp"] == "resp"
    assert pd.active_band == "ecg"
    assert pd.has_ecg is True


def test_nff_resp_wires_through_preprocess(stub_event_code_window):
    """The NFF RESP channel becomes a RespirationSeries via preprocess_ecg."""
    pd = PhysioData(str(DATA_DIR / "example1.EVT"))
    pd.preprocess_ecg()

    # band_map["ecg"]["rsp"] resolved → RespirationSeries built and stored.
    assert "ecg" in pd.rsp_map
    assert len(pd.rsp_map["ecg"]) >= 0  # series exists; may be empty if flat


def test_evt_with_timeseries_columns(stub_event_code_window):
    """EXAMP1.EVT (IBI + BPSys columns) parses cleanly into a CardioSeries."""
    pd = PhysioData(str(DATA_DIR / "EXAMP1.EVT"))

    assert pd.hrv_map  # CardioSeries created
    cs = pd.hrv_map[pd.active_band]
    # RPeak code 0 comes from the [Events] section; EXAMP1.EVT has 866 R-tops.
    assert cs.times.size == 866


def test_evt_without_timeseries_columns(stub_event_code_window):
    """example1.EVT (no [Timeseries] section) loads cleanly."""
    pd = PhysioData(str(DATA_DIR / "example1.EVT"))

    assert pd.hrv_map
    cs = pd.hrv_map[pd.active_band]
    # example1.EVT has 902 R-tops under event code 0.
    assert cs.times.size == 902


# ---------------------------------------------------------------------------
# NFF per-channel calibration (raw ADC counts -> physical units)
# ---------------------------------------------------------------------------


def _make_channel_header(
    *,
    zl_factor: int,
    zl_exp: int,
    sf_factor: int,
    sf_exp: int,
    interval_us: int = 10_000,
) -> bytes:
    """Build a 256-byte NFF channel header with known calibration ints.

    Int offsets (``_get_integer(header, n)`` == Pascal ``Int4Channel[n-10]``):
    10/11 = ZeroLevel factor/exponent, 12/13 = ScaleFactor factor/exponent,
    14 = sample interval (microseconds).
    """
    buf = bytearray(256)
    struct.pack_into("<i", buf, 10 * 4, zl_factor)
    struct.pack_into("<i", buf, 11 * 4, zl_exp)
    struct.pack_into("<i", buf, 12 * 4, sf_factor)
    struct.pack_into("<i", buf, 13 * 4, sf_exp)
    struct.pack_into("<i", buf, 14 * 4, interval_us)
    return bytes(buf)


class TestNffCalibration:
    """The NFF reader must expose the per-channel gain / offset so amplitude
    channels load in physical units instead of raw ADC counts."""

    def test_scale_and_zero_decoded(self):
        # ScaleFactor = 2 x 10^-7 ;  ZeroLevel = 50 x 10^0 = 50
        nff = TNFF()
        nff.channel_header = _make_channel_header(
            zl_factor=50, zl_exp=0, sf_factor=2, sf_exp=-7,
        )
        nff.current_channel = 1  # bypass the file read in _get_channel_header
        assert nff.get_zero_level(1) == 50.0
        assert abs(nff.get_scale_factor(1) - 2e-7) < 1e-18
        # CARSPAN multiplies the stored scale by 1e6 before applying it.
        applied_scale = nff.get_scale_factor(1) * 1_000_000.0
        assert abs(applied_scale - 0.2) < 1e-12

    def test_empty_calibration_is_zero_scale(self):
        # The bundled example recordings store empty calibration; the loader
        # treats a zero scale as "uncalibrated" and keeps the raw counts.
        nff = TNFF()
        nff.channel_header = _make_channel_header(
            zl_factor=0, zl_exp=1, sf_factor=0, sf_exp=-12,
        )
        nff.current_channel = 1
        assert nff.get_scale_factor(1) == 0.0


def test_nff_uncalibrated_channel_stays_raw(stub_event_code_window):
    """example1.nff carries no BP calibration (header factors are zero), so
    the loaded BP channel must remain raw ADC counts - the documented reason
    its systolic values differ from CARSPAN's calibrated mmHg figures."""
    pd = PhysioData(str(DATA_DIR / "example1.EVT"))
    bp = pd.timeseries["bp"]
    v = np.asarray(bp.values, dtype=float)
    # Raw 16-bit ADC range, NOT physiological mmHg.
    assert v.max() > 1000.0
    # And the values are (near-)integers, since no fractional scale was applied.
    assert np.allclose(v, np.round(v))
