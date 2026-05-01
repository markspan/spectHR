"""
_loader_utils.py – Helpers shared by the file loaders in this package.

Lives next to the concrete loaders (polar_csv.py, harness_csv.py, ...) so each
one can import a sibling helper without pulling in the full package.
"""

from __future__ import annotations

import numpy as np


# Threshold for the polarity heuristic.  Empirically, on a centre-third slice
# of a chest-lead ECG the ratio
#
#     |mean − min| / |mean − max|
#
# stays close to 1 when the R-peaks point upward and grows clearly above 1
# when they point downward (the larger-magnitude excursion has now moved
# below the mean).  1.5 sits comfortably between the two regimes for every
# Polar / Harness recording we currently support.
_POLARITY_THRESHOLD = 1.5


def is_inverted_ecg(values: np.ndarray) -> bool:
    """
    Heuristic: does the ECG signal appear to have inverted polarity?

    Looks at the centre third of the recording — a region that avoids
    settling artefacts near the start/end — and compares how far the mean
    sits from the minimum vs. the maximum.  When R-peaks point downward
    the dominant excursion is below the mean, pushing the ratio above
    ``_POLARITY_THRESHOLD``.

    Parameters
    ----------
    values : np.ndarray
        ECG amplitude samples (any unit).

    Returns
    -------
    bool
        ``True`` if the signal looks inverted and should be negated;
        ``False`` otherwise.  A series shorter than 3 samples or one with
        a degenerate (mean == max) middle third is reported as not
        inverted, since the heuristic cannot meaningfully decide.
    """
    n = values.size
    if n < 3:
        return False

    centre_third = values[n // 3 : 2 * n // 3]
    if centre_third.size == 0:
        return False

    mean_value = float(centre_third.mean())
    denom = abs(mean_value - float(centre_third.max()))
    if denom == 0:
        # Flat or degenerate window — heuristic cannot decide.
        return False

    magic = abs(mean_value - float(centre_third.min())) / denom
    return magic > _POLARITY_THRESHOLD
