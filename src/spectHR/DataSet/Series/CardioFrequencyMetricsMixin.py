"""
CardioFrequencyMetricsMixin.py – Unified frequency-domain HRV interface.

This mixin provides a single entry point (``psd()``) that dispatches to
one of three PSD back-ends — Welch, Lomb-Scargle, or CARSPAN — and
normalises every result to a common unit: **mMI²/Hz** (milli-modulation-
index squared per Hz).

It is designed to be mixed into a ``CardioSeries`` class that provides:

    self.times      np.ndarray of R-peak timestamps (seconds)
    self.ibi        np.ndarray property (np.diff(times) with trailing NaN)
    self.labels     np.ndarray of per-beat labels ("N", "TL", "T", …)

Data classes
------------
``PSDResult``  — immutable container returned by every PSD method, holding
                 frequencies, power, optional confidence bounds, unit string,
                 and method name.

Unit conversion
---------------
CARSPAN outputs Hz (events²/Hz).  Welch and Lomb-Scargle output ms²/Hz.
To convert both to mMI²/Hz (Modulation Index, CARSPAN Eq. 3.20):

    CARSPAN (Hz)  → mMI²/Hz:  multiply by mean_ibi_ms² × 10⁶
                               (because MI = S_xx / x̄² and x̄ = N/T in Hz,
                                so S'_xx [mMI²] = S_xx [Hz] × (T/N)² × 10⁶
                                                = S_xx × mean_ibi_s² × 10⁶)

    Welch / L-S (ms²/Hz) → mMI²/Hz:  divide by mean_ibi_ms² then × 10⁶
                               (MI² = Var / mean² → ms²/Hz / ms² → 1/Hz,
                                then × 10⁶ for mMI² display)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

# PSD back-ends (located in spectHR.Tools)
from spectHR.Tools.PSD import WelchPSD
from spectHR.Tools.PSD import LombScarglePSD
from spectHR.Tools.PSD import CarspanPSD


# ---------------------------------------------------------------------------
# PSDResult data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PSDResult:
    """
    Immutable container for a PSD computation result.

    Attributes
    ----------
    freqs : np.ndarray
        Frequency axis in Hz.
    power : np.ndarray
        Power spectral density values.
    unit : str
        Physical unit of *power* (e.g. ``"mMI²/Hz"``).
    method : str
        Name of the method that produced this result.
    ci_lower : np.ndarray or None
        Lower confidence-interval bound (same unit as *power*).
    ci_upper : np.ndarray or None
        Upper confidence-interval bound.
    """

    freqs: np.ndarray
    power: np.ndarray
    unit: str = "mMI²/Hz"
    method: str = ""
    ci_lower: Optional[np.ndarray] = None
    ci_upper: Optional[np.ndarray] = None


# ---------------------------------------------------------------------------
# Module-level configuration (mirrors existing pattern in CardioMetricsMixin)
# ---------------------------------------------------------------------------

# Active PSD method: "welch", "lombscargle", "carspan", or "carspan_strict"
METHOD: str = "welch"

# Confidence-interval significance level
CI_ALPHA: float = 0.05

# Frequency bands — loaded from workspace; these are fall-back defaults
HRV_FREQUENCY_BANDS: Dict[str, Dict] = {
    "VLF": {"low": 0.003, "high": 0.04, "color": "blue"},
    "LF": {"low": 0.04, "high": 0.15, "color": "darkgreen"},
    "HF": {"low": 0.15, "high": 0.40, "color": "red"},
}


def load_frequency_bands(bands_config: dict) -> None:
    """
    Replace the module-level HRV_FREQUENCY_BANDS from workspace config.

    Parameters
    ----------
    bands_config : dict
        Mapping of band name → {``"low"``, ``"high"``, ``"color"``}.
    """
    global HRV_FREQUENCY_BANDS
    HRV_FREQUENCY_BANDS = dict(bands_config)


def load_method(method: str) -> None:
    """Set the active PSD method (``"welch"``, ``"lombscargle"``, ``"carspan"``, ``"carspan_strict"``)."""
    global METHOD
    METHOD = method


def load_ci_alpha(alpha: float) -> None:
    """Set the confidence-interval significance level."""
    global CI_ALPHA
    CI_ALPHA = alpha


# ---------------------------------------------------------------------------
# Mixin class
# ---------------------------------------------------------------------------


class CardioFrequencyMetricsMixin:
    """
    Mixin that adds frequency-domain HRV methods to a CardioSeries.

    Expects the host class to provide:

    - ``self.times``   : np.ndarray — R-peak timestamps (s)
    - ``self.ibi``     : np.ndarray — inter-beat intervals (s), trailing NaN
    - ``self.labels``  : np.ndarray — per-beat labels
    """

    # ---------------------------------------------------------------
    #  Private helpers — extract clean data from the host object
    # ---------------------------------------------------------------

    def _ibi_clean_pairs(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Return aligned (times, ibi_ms) arrays with invalid intervals removed.

        An IBI is invalid if:
        - It is NaN (the trailing element, or a computational artefact).
        - The beat's label is "TL" (too long) or "T" (technical artefact).

        Returns
        -------
        ibi_times_s : np.ndarray, shape (M,)
            Timestamps (s) of the R-peak at the *start* of each valid IBI.
        ibi_values_ms : np.ndarray, shape (M,)
            Duration of each valid IBI in milliseconds.
        """
        ibi_s = self.ibi  # np.diff(times) + trailing NaN, in seconds
        labels = self.labels

        # Build validity mask
        valid = np.ones(len(ibi_s), dtype=bool)

        # Exclude NaN IBIs
        valid &= ~np.isnan(ibi_s)

        # Exclude labelled artefacts (TL = too long, T = technical)
        if labels is not None and len(labels) == len(ibi_s):
            for bad_label in ("TL", "T"):
                valid &= labels != bad_label

        times_s = self.times[valid]
        values_ms = ibi_s[valid] * 1000.0  # seconds → milliseconds

        return times_s, values_ms

    def _event_times_clean(self) -> np.ndarray:
        """
        Return R-peak timestamps for events whose *surrounding* IBIs are
        valid — i.e. the event participates in at least one valid interval.

        For CARSPAN's event-series DFT we need the actual R-peak times,
        not the IBI midpoints.  We keep every beat that is *not* labelled
        as a technical artefact.

        Returns
        -------
        np.ndarray, shape (N,)
            Clean R-peak timestamps in seconds.
        """
        labels = self.labels
        times = self.times

        if labels is None or len(labels) == 0:
            return times.copy()

        # Keep beats that are NOT technical artefacts
        valid = np.ones(len(times), dtype=bool)
        for bad_label in ("TL", "T"):
            valid &= labels != bad_label

        return times[valid]

    def _mean_ibi_ms(self) -> float:
        """
        Mean IBI in milliseconds, computed as T / (N − 1) × 1000.

        Here T = last_time − first_time (total observation span) and
        N = number of R-peaks.  This avoids bias from excluded intervals
        and is consistent with the CARSPAN definition x̄ = N/T.

        Returns
        -------
        float
            Mean IBI in ms.
        """
        times = self._event_times_clean()
        N = times.size
        if N < 2:
            raise ValueError("Need at least 2 R-peak events to compute mean IBI.")

        T = float(times[-1] - times[0])
        # mean IBI = T / (N-1)  in seconds, then × 1000 for ms
        return (T / (N - 1)) * 1000.0

    def _mmi2_factor(self) -> float:
        """
        Conversion factor from Hz (events²/Hz) to mMI²/Hz.

        CARSPAN Eq. 3.20 defines the modulation index spectrum as:

            S'_xx(f) = S_xx(f) / x̄²

        where x̄ = mean heart rate = N/T (in Hz).  Since
        1/x̄ = T/N = mean_ibi_s, we have:

            S'_xx = S_xx × mean_ibi_s²

        To display in **milli**-MI² (× 10⁶):

            factor = mean_ibi_s² × 10⁶ = (mean_ibi_ms / 1000)² × 10⁶
                   = mean_ibi_ms² × 10⁻⁶ × 10⁶ = mean_ibi_ms²  (… ÷ 1)

        Wait — let's be precise:

            mean_ibi_s = mean_ibi_ms / 1000
            mean_ibi_s² = mean_ibi_ms² / 10⁶
            factor = mean_ibi_s² × 10⁶ = mean_ibi_ms²

        So the factor is simply mean_ibi_ms² (!).

        Returns
        -------
        float
            mean_ibi_ms² — multiply CARSPAN Hz output by this to get mMI²/Hz.
        """
        mean_ibi = self._mean_ibi_ms()
        return mean_ibi**2

    # ---------------------------------------------------------------
    #  Public API — PSD
    # ---------------------------------------------------------------

    def psd(
        self,
        method: Optional[str] = None,
        with_ci: bool = True,
    ) -> PSDResult:
        """
        Compute the power spectral density, normalised to **mMI²/Hz**.

        Parameters
        ----------
        method : str, optional
            One of ``"welch"``, ``"lombscargle"``, ``"carspan"``,
            ``"carspan_strict"``.  Defaults to the module-level ``METHOD``.
        with_ci : bool
            If True (default), include confidence-interval bounds.

        Returns
        -------
        PSDResult
            Frequencies, power (mMI²/Hz), optional CI bounds, unit, method.

        Notes
        -----
        Welch and Lomb-Scargle analyse the **IBI series** (interval durations),
        while CARSPAN analyses the **event series** (R-peak times as unit
        impulses).  These are fundamentally different representations of the
        same cardiac process.  Both are normalised to mMI²/Hz (modulation
        index), but absolute values are **not directly comparable** across
        representation types.  Within each representation family, results
        are consistent and comparable (e.g. Welch vs. Lomb-Scargle).
        """
        method = method or METHOD

        if method == "welch":
            return self._psd_welch(with_ci=with_ci)
        elif method == "lombscargle":
            return self._psd_lombscargle(with_ci=with_ci)
        elif method == "carspan_strict":
            return self._psd_carspan_strict(with_ci=with_ci)
        elif method == "carspan":
            return self._psd_carspan(with_ci=with_ci)
        else:
            raise ValueError(
                f"Unknown PSD method '{method}'. "
                "Choose from: welch, lombscargle, carspan, carspan_strict."
            )

    def band_power(
        self,
        band_name: str,
        method: Optional[str] = None,
    ) -> float:
        """
        Integrated band power in **mMI²**.

        Uses rectangular summation (CARSPAN Eq. 3.28) on the native PSD grid.

        Parameters
        ----------
        band_name : str
            Key into ``HRV_FREQUENCY_BANDS`` (e.g. ``"VLF"``, ``"LF"``,
            ``"HF"``).
        method : str, optional
            PSD method.  Defaults to module-level ``METHOD``.

        Returns
        -------
        float
            Band power in mMI².
        """
        if band_name not in HRV_FREQUENCY_BANDS:
            raise KeyError(
                f"Unknown band '{band_name}'. "
                f"Available: {list(HRV_FREQUENCY_BANDS.keys())}"
            )

        band = HRV_FREQUENCY_BANDS[band_name]
        f_low = band["low"]
        f_high = band["high"]

        # Get the PSD (already in mMI²/Hz)
        result = self.psd(method=method, with_ci=False)

        return CarspanPSD.band_power_rectangular(
            result.freqs, result.power, f_low, f_high
        )

    def band_powers(
        self,
        method: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Compute all configured band powers at once.

        Returns
        -------
        dict
            Mapping band_name → power in mMI².
        """
        result = self.psd(method=method, with_ci=False)
        powers = {}

        for name, band in HRV_FREQUENCY_BANDS.items():
            powers[name] = CarspanPSD.band_power_rectangular(
                result.freqs, result.power, band["low"], band["high"]
            )

        return powers

    # ---------------------------------------------------------------
    #  Private dispatchers — one per back-end
    # ---------------------------------------------------------------

    def _psd_welch(self, with_ci: bool = True) -> PSDResult:
        """
        Compute Welch PSD and convert ms²/Hz → mMI²/Hz.

        Conversion:
            mMI²/Hz = (ms²/Hz) / mean_ibi_ms² × 10⁶
                     = (ms²/Hz) × 10⁶ / mean_ibi_ms²

        (Since MI = deviation / mean, MI² = (ms²) / (ms²) = dimensionless,
        and per-Hz gives 1/Hz.  The 10⁶ scales to *milli*-MI².)
        """
        ibi_times_s, ibi_values_ms = self._ibi_clean_pairs()
        factor = self._mmi2_factor()  # mean_ibi_ms²

        # Conversion multiplier: ms²/Hz → mMI²/Hz
        # MI² = variance / mean² → (ms²/Hz) / (ms²) = 1/Hz
        # mMI² = MI² × 10⁶
        convert = 1e6 / factor  # = 10⁶ / mean_ibi_ms²

        f_max = max(b["high"] for b in HRV_FREQUENCY_BANDS.values())

        if with_ci:
            freqs, power, ci_lo, ci_hi = WelchPSD.compute_welch_psd_with_ci(
                ibi_times_s, ibi_values_ms, alpha=CI_ALPHA
            )
            # Trim to f_max
            mask = freqs <= f_max
            return PSDResult(
                freqs=freqs[mask],
                power=power[mask] * convert,
                unit="mMI²/Hz",
                method="welch",
                ci_lower=ci_lo[mask] * convert,
                ci_upper=ci_hi[mask] * convert,
            )
        else:
            freqs, power = WelchPSD.compute_welch_psd(
                ibi_times_s,
                ibi_values_ms,
            )
            mask = freqs <= f_max
            return PSDResult(
                freqs=freqs[mask],
                power=power[mask] * convert,
                unit="mMI²/Hz",
                method="welch",
            )

    def _psd_lombscargle(self, with_ci: bool = True) -> PSDResult:
        """
        Compute Lomb-Scargle PSD and convert ms²/Hz → mMI²/Hz.

        Same conversion as Welch: multiply by 10⁶ / mean_ibi_ms².
        """
        ibi_times_s, ibi_values_ms = self._ibi_clean_pairs()
        factor = self._mmi2_factor()
        convert = 1e6 / factor

        f_max = max(b["high"] for b in HRV_FREQUENCY_BANDS.values())

        if with_ci:
            freqs, power, ci_lo, ci_hi = LombScarglePSD.compute_lombscargle_psd_with_ci(
                ibi_times_s,
                ibi_values_ms,
                alpha=CI_ALPHA,
                f_max=f_max,
            )
            return PSDResult(
                freqs=freqs,
                power=power * convert,
                unit="mMI²/Hz",
                method="lombscargle",
                ci_lower=ci_lo * convert,
                ci_upper=ci_hi * convert,
            )
        else:
            freqs, power = LombScarglePSD.compute_lombscargle_psd(
                ibi_times_s,
                ibi_values_ms,
                f_max=f_max,
            )
            return PSDResult(
                freqs=freqs,
                power=power * convert,
                unit="mMI²/Hz",
                method="lombscargle",
            )

    def _psd_carspan_strict(self, with_ci: bool = True) -> PSDResult:
        """
        Compute strict CARSPAN PSD and convert Hz → mMI²/Hz.

        Conversion:
            mMI²/Hz = Hz × mean_ibi_ms²

        (S'_xx = S_xx / x̄²;  x̄ = HR = 1/mean_ibi_s;
         so S'_xx = S_xx × mean_ibi_s² → × 10⁶ for mMI² → factor = mean_ibi_ms²)
        """
        event_times = self._event_times_clean()
        factor = self._mmi2_factor()  # mean_ibi_ms²

        f_max = max(b["high"] for b in HRV_FREQUENCY_BANDS.values())

        if with_ci:
            freqs, power, ci_lo, ci_hi = CarspanPSD.compute_carspan_psd_strict_with_ci(
                event_times,
                alpha_ci=CI_ALPHA,
                f_max=f_max,
            )
            return PSDResult(
                freqs=freqs,
                power=power * factor,
                unit="mMI²/Hz",
                method="carspan_strict",
                ci_lower=ci_lo * factor,
                ci_upper=ci_hi * factor,
            )
        else:
            freqs, power = CarspanPSD.compute_carspan_psd_strict(
                event_times,
                f_max=f_max,
            )
            return PSDResult(
                freqs=freqs,
                power=power * factor,
                unit="mMI²/Hz",
                method="carspan_strict",
            )

    def _psd_carspan(self, with_ci: bool = True) -> PSDResult:
        """
        Compute configurable CARSPAN PSD and convert Hz → mMI²/Hz.

        Same conversion as strict: multiply by mean_ibi_ms².
        """
        event_times = self._event_times_clean()
        factor = self._mmi2_factor()

        f_max = max(b["high"] for b in HRV_FREQUENCY_BANDS.values())

        if with_ci:
            freqs, power, ci_lo, ci_hi = CarspanPSD.compute_carspan_psd_with_ci(
                event_times,
                alpha_ci=CI_ALPHA,
                f_max=f_max,
            )
            return PSDResult(
                freqs=freqs,
                power=power * factor,
                unit="mMI²/Hz",
                method="carspan",
                ci_lower=ci_lo * factor,
                ci_upper=ci_hi * factor,
            )
        else:
            freqs, power = CarspanPSD.compute_carspan_psd(
                event_times,
                f_max=f_max,
            )
            return PSDResult(
                freqs=freqs,
                power=power * factor,
                unit="mMI²/Hz",
                method="carspan",
            )
