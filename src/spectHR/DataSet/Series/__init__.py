# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/Series/__init__.py
# Public re-exports for the Series sub-package.

from spectHR.DataSet.Series.TimeSeries import TimeSeries, TimeSeriesView
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.Series.CardioSeriesProtocol import CardioSeriesLike
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Series.CardioSeriesView import CardioSeriesView
from spectHR.DataSet.Series.RespirationSeries import RespirationSeries
from spectHR.DataSet.Series.RespirationSeriesView import RespirationSeriesView


__all__ = [
    # Raw time series
    "TimeSeries",
    "TimeSeriesView",
    "EventSeries",
    # Cardio
    "CardioSeriesLike",
    "CardioSeries",
    "CardioSeriesView",
    # Respiration
    "RespirationSeries",
    "RespirationSeriesView",
]
