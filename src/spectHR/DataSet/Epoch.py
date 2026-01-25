from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True, slots=True)
class Epoch:
    """
    Single contiguous time interval used for segmentation/analysis.

    Attributes
    ----------
    active:
        Whether this epoch participates in analyses/UI.
    start:
        Start time in seconds (dataset time base).
    end:
        End time in seconds (dataset time base).
    """

    active: bool
    start: float
    end: float

    # --------------------------------------------------
    # Basic properties
    # --------------------------------------------------
    @property
    def duration(self) -> float:
        """Epoch duration in seconds."""
        return float(self.end - self.start)

    @property
    def midpoint(self) -> float:
        """Midpoint time (seconds)."""
        return float((self.start + self.end) / 2.0)

    @property
    def bounds(self) -> tuple[float, float]:
        """(start, end) as a tuple of floats."""
        return float(self.start), float(self.end)

    # --------------------------------------------------
    # Validation / predicates
    # --------------------------------------------------
    @property
    def is_valid(self) -> bool:
        """True if start < end and both bounds are finite."""
        return bool(np.isfinite(self.start) and np.isfinite(self.end) and (self.start < self.end))

    def contains(self, t: float, *, inclusive: bool = True) -> bool:
        """
        Return True if time t lies within the epoch.

        Parameters
        ----------
        t:
            Time in seconds.
        inclusive:
            If True, include endpoints (start <= t <= end).
            If False, use open interval (start < t < end).
        """
        if inclusive:
            return bool(self.start <= t <= self.end)
        return bool(self.start < t < self.end)

    def overlaps(self, other: "Epoch", *, inclusive: bool = True) -> bool:
        """
        Return True if this epoch overlaps another epoch.
        """
        a0, a1 = self.start, self.end
        b0, b1 = other.start, other.end
        if inclusive:
            return bool(a0 <= b1 and b0 <= a1)
        return bool(a0 < b1 and b0 < a1)

    # --------------------------------------------------
    # Array utilities
    # --------------------------------------------------
    def mask(self, times: np.ndarray, *, inclusive: bool = True) -> np.ndarray:
        """
        Boolean mask for an array of times.

        Parameters
        ----------
        times:
            1D array of times in seconds.
        inclusive:
            If True, include endpoints.

        Returns
        -------
        np.ndarray
            Boolean mask aligned to `times`.
        """
        times = np.asarray(times, dtype=float)
        if inclusive:
            return (times >= self.start) & (times <= self.end)
        return (times > self.start) & (times < self.end)

    def clip(self, times: np.ndarray, values: np.ndarray, *, inclusive: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """
        Convenience helper: return (times, values) restricted to the epoch.

        This is useful for plotting routines.

        Parameters
        ----------
        times:
            1D times array.
        values:
            1D values array, same length as times.
        inclusive:
            If True, include endpoints.

        Returns
        -------
        t_clip, v_clip:
            Sub-arrays restricted to the epoch.
        """
        m = self.mask(times, inclusive=inclusive)
        return times[m], values[m]

@dataclass
class Phase:
    """
    Repeating physiological phase consisting of multiple time intervals.

    Examples
    --------
    - inhalation phases
    - exhalation phases
    - artifact intervals
    """

    active: bool
    intervals: Sequence[Tuple[float, float]]

    @property
    def n_intervals(self) -> int:
        return len(self.intervals)

    @property
    def durations(self) -> np.ndarray:
        return np.asarray([end - start for start, end in self.intervals], dtype=float)

    @property
    def total_duration(self) -> float:
        return float(np.sum(self.durations))

    def contains(self, t: float) -> bool:
        return any(start <= t <= end for start, end in self.intervals)

    def mask(self, times: np.ndarray) -> np.ndarray:
        times = np.asarray(times, dtype=float)
        m = np.zeros(times.shape, dtype=bool)
        for start, end in self.intervals:
            m |= (times >= start) & (times <= end)
        return m