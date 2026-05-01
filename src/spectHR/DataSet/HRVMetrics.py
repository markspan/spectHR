"""
HRVMetrics.py

Provides:
    - @hrv_metric decorator
    - HRVMetric for automatic HRV metric discovery
    - Standard HRV functions ready for use in RTopSeries and RTopSeriesView.

This file is independent and can be imported anywhere.
"""

from __future__ import annotations
from typing import Callable, Dict
import numpy as np


# ---------------------------------------------------------
# DECORATOR
# ---------------------------------------------------------
def hrv_metric(func: Callable) -> Callable:
    """
    Decorator: Marks a method as an HRV metric.

    Any method decorated with @hrv_metric will automatically be included
    in HRVMetric.metric_table() and metric_table_epoch().

    The function must:
        - be an instance method: func(self)
        - return a float (metric value)
    """
    func._is_hrv_metric = True
    return func


# ---------------------------------------------------------
# MIXIN
# ---------------------------------------------------------
class HRVMetric:
    """
    Adds automatic HRV metric capabilities to a class.

    A class inheriting HRVMetric may define any number of HRV metrics
    using the @hrv_metric decorator.

    Example:
        @hrv_metric
        def rmssd(self):
            ...
    """

    # ===== METRIC DISCOVERY =====
    @classmethod
    def get_metric_functions(cls) -> Dict[str, Callable]:
        """
        Return all metric functions defined with @hrv_metric in this class.
        """
        metrics = {}
        for name in dir(cls):
            obj = getattr(cls, name)
            if callable(obj) and getattr(obj, "_is_hrv_metric", False):
                metrics[name] = obj
        return metrics

    # ===== FULL-SERIES TABLE =====
    def metric_table(self) -> dict:
        """
        Compute all metrics for the full series.
        Returns a dictionary: metric_name → metric_value (float)
        """
        metrics = self.get_metric_functions()
        return {
            name: float(fn(self))
            for name, fn in metrics.items()
        }

    # ===== EPOCH TABLE =====
    def metric_table_epoch(self, starttime: float, endtime: float) -> dict:
        """
        Compute all metrics for a given epoch.

        Requires subclass (e.g., RTopSeries) to provide .view(start, end).

        Returns:
            dict: metric_name → metric_value
        """
        if not hasattr(self, "view"):
            raise AttributeError("Class inheriting HRVMetric must implement .view(start, end).")

        view = self.view(starttime, endtime)
        metrics = self.get_metric_functions()

        return {
            name: float(fn(view))
            for name, fn in metrics.items()
        }
