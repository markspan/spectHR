# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for the functional single-beat editing API on :class:`Events`.

These are the R-peak edit *algorithms* (add / move / delete / reclassify and
the abnormal-beat queries) that the interactive editor's ``RTopController``
delegates to.  Pure spectHR, no Qt.
"""
from __future__ import annotations

import numpy as np

from spectHR.session import Events


def _ev(times, labels=None) -> Events:
    times = np.asarray(times, dtype=float)
    if labels is None:
        labels = np.full(times.shape, "N", dtype=object)
    return Events(times, np.asarray(labels, dtype=object))


# --- added -----------------------------------------------------------------


def test_added_keeps_sorted_and_immutable():
    e = _ev([0.0, 1.0, 2.0]).added(0.5)
    assert list(e.times) == [0.0, 0.5, 1.0, 2.0]
    assert e.times.flags.writeable is False


def test_added_inserts_label():
    e = _ev([0.0, 2.0]).added(1.0, "S")
    assert list(e.labels) == ["N", "S", "N"]


# --- moved -----------------------------------------------------------------


def test_moved_resorts_and_carries_label():
    e = _ev([0.0, 1.0, 2.0, 3.0], ["N", "S", "N", "N"]).moved(1.0, 2.5)
    assert list(e.times) == [0.0, 2.0, 2.5, 3.0]
    assert e.labels[list(e.times).index(2.5)] == "S"  # the moved beat kept its label


def test_moved_empty_returns_self():
    e = _ev([])
    assert e.moved(1.0, 2.0) is e


# --- removed ----------------------------------------------------------------


def test_removed_nearest():
    e = _ev([0.0, 1.0, 2.0]).removed(1.1)
    assert list(e.times) == [0.0, 2.0]


def test_removed_empty_returns_self():
    e = _ev([])
    assert e.removed(1.0) is e


# --- reclassified -----------------------------------------------------------


def test_reclassified_labels_all_beats_and_marks_trailing_T():
    times = np.arange(0.0, 10.0, 0.8)
    e = _ev(times).reclassified()
    assert e.labels.shape == times.shape
    assert e.labels[-1] == "T"  # trailing NaN-IBI beat


def test_reclassified_forwards_kwargs():
    times = np.arange(0.0, 10.0, 0.8)
    e = _ev(times).reclassified(window_length=7, n_std=2.0, max_ibi_sec=1.9)
    assert e.labels.shape == times.shape


# --- abnormal queries -------------------------------------------------------


def test_abnormal_mask_excludes_final_beat():
    e = _ev([0.0, 1.0, 2.0], ["S", "N", "S"])
    assert list(e.abnormal_mask()) == [True, False, False]  # last always excluded


def test_next_prev_abnormal_skip_trailing_T():
    e = _ev([0.0, 1.0, 2.0, 3.0, 4.0], ["N", "S", "N", "L", "T"])
    assert e.next_abnormal(0.0) == 1.0
    assert e.next_abnormal(1.0) == 3.0
    assert e.next_abnormal(3.0) is None      # trailing "T" excluded
    assert e.prev_abnormal(5.0) == 3.0
    assert e.prev_abnormal(1.0) is None
