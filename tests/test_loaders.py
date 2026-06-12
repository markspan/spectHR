# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Smoke tests for the CARSPAN ``.evt`` / ``.nff`` loaders.

These exercise the real example files in ``ExampleData/data/`` rather than
synthetic fixtures, so they verify the binary NFF reader and the two-phase EVT
parser end to end.

Both example ``.evt`` files contain more than two distinct non-R-top event
codes, so :func:`spectHR.DataSet.loaders.evt_loader._parse_evt` opens the
``EventCodeWindow`` Qt dialog to ask which codes mark epoch boundaries.  The
``stub_event_code_window`` fixture replaces that dialog with a headless no-op
so the tests can run without a display.
"""
from __future__ import annotations

import struct
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from spectHR.DataSet.loaders import load
from spectHR.DataSet.loaders.nff_loader import TNFF
from spectHR.session import Session

DATA_DIR = Path(__file__).resolve().parents[1] / "ExampleData" / "data"


@pytest.fixture
def stub_event_code_window(monkeypatch):
    """Replace the Qt ``EventCodeWindow`` dialog with a headless stub.

    Selecting no codes causes the EVT loader to fall back to a single epoch —
    sufficient for these smoke tests which only verify that parsing completes
    and the series are built.
    """

    class _FakeEventCodeWindow:
        def __init__(self, *args, **kwargs):
            self.start_codes: list[int] = []
            self.stop_codes: list[int] = []

        def exec(self) -> int:
            return 0

    spectui  = types.ModuleType("spectUI")
    spectui.__path__ = []
    widgets  = types.ModuleType("spectUI.widgets")
    widgets.__path__ = []
    leaf     = types.ModuleType("spectUI.widgets.EventCodeWindow")
    leaf.EventCodeWindow = _FakeEventCodeWindow

    monkeypatch.setitem(sys.modules, "spectUI",                          spectui)
    monkeypatch.setitem(sys.modules, "spectUI.widgets",                  widgets)
    monkeypatch.setitem(sys.modules, "spectUI.widgets.EventCodeWindow",  leaf)
    return _FakeEventCodeWindow


def test_nff_loads_all_channels(stub_event_code_window):
    """Loading example1.EVT pulls in every channel of example1.nff."""
    session = load(DATA_DIR / "example1.EVT")

    assert isinstance(session, Session)
    for key in ("ecg", "bp", "resp", "esp", "plet", "card", "toon"):
        assert key in session.samples, f"missing channel '{key}'"


def test_evt_loads_hrv_events(stub_event_code_window):
    """example1.EVT produces R-peak events under 'hrv'."""
    session = load(DATA_DIR / "example1.EVT")

    assert "hrv" in session.events
    hrv = session.events["hrv"]
    assert hrv.times.size == 902


def test_evt_with_timeseries_columns(stub_event_code_window):
    """EXAMP1.EVT (IBI + BPSys columns) parses cleanly into hrv events."""
    session = load(DATA_DIR / "EXAMP1.EVT")

    assert "hrv" in session.events
    assert session.events["hrv"].times.size == 866


def test_evt_has_experiment_epoch(stub_event_code_window):
    """Every EVT load produces at least an 'experiment' epoch."""
    session = load(DATA_DIR / "example1.EVT")

    assert "experiment" in session.epochs


def test_evt_epochs_from_event_declarations(stub_event_code_window):
    """[Events] Begin/End couples become one epoch each (plus 'experiment').

    example1.EVT declares BeginBlock/EndBlock (one couple) and
    Beginperiod/Enderiod (two couples) → experiment + epoch #1/#2/#3.
    """
    session = load(DATA_DIR / "example1.EVT")
    assert set(session.epochs) == {"experiment", "epoch #1", "epoch #2", "epoch #3"}
    # Each declared epoch is a real sub-window of the experiment.
    exp = session.epochs["experiment"]
    for name in ("epoch #1", "epoch #2", "epoch #3"):
        ep = session.epochs[name]
        assert exp.start <= ep.start < ep.end <= exp.end + 1.0


def test_nff_uncalibrated_channel_stays_raw(stub_event_code_window):
    """example1.nff carries no BP calibration (header factors are zero), so
    the loaded BP channel must remain raw ADC counts."""
    session = load(DATA_DIR / "example1.EVT")
    bp = session.samples["bp"]
    v = np.asarray(bp.values, dtype=float)
    assert v.max() > 1000.0
    assert np.allclose(v, np.round(v))


def test_nff_times_start_at_zero(stub_event_code_window):
    """Loaded NFF samples should be normalized so the earliest time is 0."""
    session = load(DATA_DIR / "example1.EVT")
    for name, s in session.samples.items():
        assert s.times[0] >= 0.0, f"channel '{name}' times do not start at 0"


def test_evt_rtops_aligned_with_nff_ecg(stub_event_code_window):
    """EVT R-tops and the NFF ECG share one time base after rebasing.

    Regression: rebasing the NFF samples to start at 0 must also rebase the
    EVT events by the same offset, or the R-tops drift ~t_min_nff seconds off
    the ECG (example1's NFF clock starts at ~287 s).
    """
    session = load(DATA_DIR / "example1.EVT")
    ecg = session.samples["ecg"]
    hrv = session.events["hrv"]

    # Every R-top falls inside the ECG span.
    assert hrv.times[0] >= ecg.times[0] - 0.1
    assert hrv.times[-1] <= ecg.times[-1] + 0.1

    # R-tops sit on R-waves: the ECG sample at each R-top time is an extreme
    # value (|z| well above baseline), not a mid-cycle sample.
    idx = np.clip(np.searchsorted(ecg.times, hrv.times), 0, ecg.values.size - 1)
    z = np.abs((ecg.values[idx] - ecg.values.mean()) / ecg.values.std())
    assert float(np.median(z)) > 1.5


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
    """Build a 256-byte NFF channel header with known calibration ints."""
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
        nff = TNFF()
        nff.channel_header = _make_channel_header(
            zl_factor=50, zl_exp=0, sf_factor=2, sf_exp=-7,
        )
        nff.current_channel = 1
        assert nff.get_zero_level(1) == 50.0
        assert abs(nff.get_scale_factor(1) - 2e-7) < 1e-18
        applied_scale = nff.get_scale_factor(1) * 1_000_000.0
        assert abs(applied_scale - 0.2) < 1e-12

    def test_empty_calibration_is_zero_scale(self):
        nff = TNFF()
        nff.channel_header = _make_channel_header(
            zl_factor=0, zl_exp=1, sf_factor=0, sf_exp=-12,
        )
        nff.current_channel = 1
        assert nff.get_scale_factor(1) == 0.0
