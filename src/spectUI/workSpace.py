# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

from spectHR.Tools.Logger import logger

# The workspace -> algorithm-parameter bridge lives in the headless library
# (spectHR.config) so scripts and the test-suite can build a PsdMethod from a
# config dict without importing the Qt UI. Re-exported here for backward
# compatibility with the many ``from spectUI.workSpace import ...`` call sites.
from spectHR.config import (  # noqa: F401  (re-export)
    LOG_LEVELS,
    RSA_REJECTION_MODES,
    RSP_SOURCES,
    bp_calibration_from_workspace,
    display_bands_from_workspace,
    log_level_from_workspace,
    profile_settings_from_workspace,
    psd_ci_alpha,
    psd_method_from_workspace,
    resolved_profile_bands,
    rsa_rejection_from_workspace,
    rsp_source_from_workspace,
    spectrogram_settings_from_workspace,
    transfer_settings_from_workspace,
)

from platformdirs import user_documents_path

_DEFAULT_WORKSPACE = {
    "Directories": {
        "DataDirectory": str(user_documents_path() / "spectHR"),
        "CacheDirectory": str(user_documents_path() / "spectHR/cache"),
        "OutputDirectory": str(user_documents_path() / "spectHR/export"),
    },
    "FrequencyAnalysis": {
        "method": "carspan",
        "bands": {
            "FullRange": {"low": 0.02, "high": 0.5, "color": "gray", "alpha": 0.35},
            "VLF": {"low": 0.02, "high": 0.06, "color": "blue"},
            "LF": {"low": 0.07, "high": 0.14, "color": "darkgreen"},
            "HF": {"low": 0.15, "high": 0.40, "color": "red"},
        },
        "carspan": {
            "freq_resolution": 0.01,
            "signal": "events",
            "window": "10% cosine bell",
            "smooth_for_display": True,
            "plot_units": "mMI²/Hz",
            "dc_removal": False,
        },
        "welch": {
            "fs": 4.0,
            "nperseg": 256,
            "noverlap": 128,
            "nfft": 1024,
            "window": "hann",
            "units": "mMI²",
        },
        "lombscargle": {
            "nfreqs": 100,
            "fmin_floor": 1e-4,
            "units": "mMI²",
        },
        "confidence_interval_alpha": 0.05,
    },
    "CardioParameters": {
        "IbiClassification": {
            "window_length": 51,
            "n_std": 4.0,
            "max_ibi_sec": 2.0,
            "min_peak_distance_ms": 300.0,
        },
        "EcgPreprocessing": {
            "filter_type": "highpass",
            "filter_cutoff": 1.0,
        },
    },
    # ------------------------------------------------------------------
    # Manual signal calibration (raw ADC counts -> physical units)
    # ------------------------------------------------------------------
    # CARSPAN derives blood-pressure time series from the raw BP waveform
    # via a linear calibration ``mmHg = scale * raw + zero`` entered by the
    # user in the *Specify data* dialog (Carspan manual sec. 8.1.2). The
    # bundled ``example1.nff`` ships *uncalibrated* - its NFF header carries
    # no scale/zero - so the loader leaves it in raw counts and this manual
    # calibration is applied afterwards (in ``PreProcessFile``) to reproduce
    # the manual's figures (MEAN BPSys 121.5 mmHg). The manual's worked
    # example specifies exactly Scale Factor 0.125, Zero Level 0 for this
    # dataset, which are the defaults here.
    #
    # Applied only when the NFF header did *not* already carry a per-channel
    # calibration (mirrors the manual's "when not already included in the
    # header" rule); a header-calibrated channel is left untouched.
    # ``bp_scale`` is in mmHg per raw count; leave it at 1.0 / 0.0 for a
    # no-op (raw counts preserved).
    "Calibration": {
        "bp_scale": 0.125,
        "bp_zero": 0.0,
    },
    # ------------------------------------------------------------------
    # Impedance cardiography (ICG) — pre-ejection period (PEP)
    # ------------------------------------------------------------------
    # ``b_point_guard_ms`` is the width (ms) of the guard zone immediately
    # before the dZ/dt C-point (peak ejection velocity) that is excluded
    # from the B-point search. The B-point (aortic-valve opening) is
    # anatomically never within a few dozen ms of the C-point; without the
    # guard the global 2nd-derivative maximum can latch onto a secondary
    # acceleration bump adjacent to C on distorted morphologies (e.g.
    # standing), placing the B-point — and hence PEP — too late. The
    # default 30 ms sits at the physiological floor of the C-B interval;
    # raise it if your B-points still read late, lower it (toward 0, which
    # disables the guard) if a short upstroke is being clipped.
    "IcgAnalysis": {
        "b_point_guard_ms": 30.0,
    },
    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    # Minimum severity a log record must have to be shown (in the Log dock
    # and on the console). One of DEBUG / INFO / WARNING / ERROR / CRITICAL;
    # records below the chosen level are dropped. DEBUG is the most verbose,
    # CRITICAL the quietest. Applied to the "spectHR" logger on start-up and
    # whenever the workspace is edited or opened.
    "Logging": {
        "level": "INFO",
    },
    # ------------------------------------------------------------------
    # Spectral profiles
    # ------------------------------------------------------------------
    # A spectral profile is the time course of a band-power measure
    # inside one epoch - implemented as the standard PSD pipeline
    # applied to a window that slides along the recording with a fixed
    # step (see CARSPAN manual sec. 3.3.5, Eq. 3.34 / 3.35). The compute
    # algorithm and band definitions are inherited from
    # ``FrequencyAnalysis`` so a profile of `band X` is computed with
    # the same PSD method (Welch / Lomb-Scargle / CARSPAN / strict) and
    # the same edges as the corresponding PSD band - they're two views
    # of the same underlying analysis.
    #
    # ``bands`` lists the band names (matching keys in
    # ``FrequencyAnalysis.bands``) the profile plot should draw. The
    # profile compute may compute all configured bands; this list is a
    # display filter only.
    #
    # ``window (sec)`` and ``step (sec)`` are the sliding-window parameters
    # in seconds; step must be strictly smaller than window (otherwise
    # there's no overlap, no profile), and the manual recommends
    # window >= 3 * 1/f_l_min for reliable estimates.
    # The pre-formatted key names (spaces + parentheses) are intentional:
    # they bypass the _label() camelCase/snake_case splitter and appear
    # in the dialog exactly as written here.
    "Profiles": {
        "window (sec)": 30.0,
        "step (sec)": 5.0,
        "bands": ["LF", "HF"],
        # ``adaptive_bands`` maps band names to their adaptive half-width
        # settings. Each entry opts that band into respiration-centered
        # profile integration (same idea as CARSPAN's
        # ``TAnaBand.RespirationBand`` flag, "Add variable band" button
        # in ``F_SpecAnalysisProfiles.pas``).
        #
        # Stored here on Profiles - not on FrequencyAnalysis.bands -
        # because the flag is consulted *only* by the sliding-window
        # profile compute (``band_power_profile``). Whole-epoch PSDs and
        # band_powers always use the absolute Hz edges from
        # ``FrequencyAnalysis.bands`` and are unaffected.
        #
        # Format:
        #   {"HF": {"lower half-width (Hz)": 0.04,
        #           "upper half-width (Hz)": 0.04}}
        #
        # "lower half-width (Hz)": how far below the per-window mean
        #   breathing frequency the band edge falls
        #   (band_low  = resp_freq - lower_half_width).
        # "upper half-width (Hz)": how far above it
        #   (band_high = resp_freq + upper_half_width).
        #
        # The static ``FrequencyAnalysis.bands`` edges (``low``/``high``)
        # are left untouched - they remain the edges for whole-epoch
        # band powers and PSD display. Only the profile builder uses
        # these half-widths.
        #
        # Default is empty: every band starts static. Researchers add
        # bands here when their recording involves breathing-rate changes
        # (paced breathing, stress protocols, biofeedback). Typically
        # only HF is tracked. Has effect only when a RespirationSeries
        # is present; without a breathing signal the bands silently fall
        # back to their static edges - exactly what CARSPAN does when
        # ``FRespFreqList`` is empty.
        "adaptive_bands": {},
        # How the per-window breathing frequency is derived for adaptive bands:
        #   "respiration_channel" - CARSPAN-faithful: use the mean breath
        #     frequency from the RespirationSeries in PhysioData.rsp_map.
        #     Falls back to static edges if no respiration channel is loaded.
        #   "psd_peak" - no respiration channel required: find the frequency
        #     of maximum power within the band's static [low, high] range in
        #     the per-window PSD, and centre the adaptive band there.
        "adaptive_source": "respiration_channel",
        # Smooth the per-window breathing frequency before using it to
        # position the adaptive band edges. The same Pascal-faithful
        # 3-point MA kernel used by the PSD smoother is applied to the
        # full sequence of per-window breath frequencies; single-window
        # spikes (e.g. a missed breath cycle or a noisy rsp signal) are
        # replaced by their neighbours' average before the band edges are
        # computed. Setting this to True requires a two-pass calculation
        # (freq-collection pass, smooth, band-power pass); the
        # smoothed frequencies are also what the right-axis overlay in
        # the profile plot draws. Defaults to False (CARSPAN-faithful:
        # raw per-window breathing frequency, no temporal smoothing).
        "smooth_breath_freq": False,
        # Apply Pascal's 3-point MA along each band's time series before
        # plotting. Same kernel + edge policy as the PSD smoother - plot
        # only; band-power integration is unaffected. Defaults to
        # False because the reference Delphi profile view doesn't apply
        # any time-axis smoother - the plotted line is the raw
        # band-power per profile window. Flip to True for an
        # easier-on-the-eye curve when the data is noisy.
        "smooth_for_display": False,
    },
    # ------------------------------------------------------------------
    # Spectrogram
    # ------------------------------------------------------------------
    # Time-frequency view of the per-window PSD. Sliding-window scheme
    # mirrors Profiles, but the per-window PSD is kept whole and shown
    # as a (time, freq, power) heat map rather than collapsed to band
    # integrals. The PSD method (Welch, Lomb-Scargle, CARSPAN, strict)
    # is inherited from FrequencyAnalysis so the colour-encoded
    # spectrum stays consistent with the PSD and Profile views.
    #
    # window (sec) and step (sec) carry the same meaning as on the
    # Profile side, per-window length and slide. show_respiration_
    # overlay draws the per-window breathing-frequency trace over the
    # heat map when a RespirationSeries is loaded for the epoch.
    "Spectrogram": {
        "window (sec)": 30.0,
        "step (sec)": 5.0,
        "show_respiration_overlay": True,
        # Matplotlib colormap name driving the pcolormesh tile. The
        # default (RdYlBu_r) is the standard neuroimaging ERSP palette,
        # blue at low power and red at high. Any other matplotlib
        # colormap name works at the renderer level; the Settings
        # dialog dropdown lists the most useful subset.
        "colormap": "RdYlBu_r",
    },
    # ------------------------------------------------------------------
    # Transfer function (Respiration -> HR)
    # ------------------------------------------------------------------
    # Bode-plot view of compute_transfer / compute_transfer_profile in
    # spectHR.analysis.transfer. Per epoch: a 3-row stacked tile with
    # modulus, phase and coherence sharing the frequency x-axis.
    # Profile (sliding-window): the same 3-row stack with band-summary
    # statistics on the time x-axis.
    "TransferAnalysis": {
        # Which signal drives the transfer-function *input* channel (the
        # output is always IBI/HR). "bp_sys"/"bp_dia" give the
        # blood-pressure->HR baroreflex-sensitivity transfer using per-beat
        # systolic / diastolic pressure (the default; systolic is the Robbe
        # et al. 1987 BRS convention); "rsp" is the classic respiration->HR
        # (respiratory sinus arrhythmia) transfer. Requires the matching
        # channel to be present (blood pressure or respiration).
        "input_signal": "bp_sys",
        "window (sec)": 30.0,
        "step (sec)": 5.0,
        # Squared-coherence threshold used by the band integrators
        # (Caluculate_ModulusSum / Caluculate_PhaseSum) and by the
        # phase mask in the per-epoch plot. CARSPAN default 0.5.
        "min_coherence": 0.5,
        # Frequency-axis range for the per-epoch Bode plots (Hz). f_max
        # also caps the native DFT grid - everything above it is dropped
        # before the transfer formula. 0.5 covers everything
        # physiologically interesting for adult HRV.
        "f_min": 0.0,
        "f_max": 0.5,
        # 3-point triangular smoother on the auto- and cross-spectra
        # before computing transfer / coherence. Without it the
        # single-block periodogram makes coherence identically 1 at
        # every bin (uninformative). CARSPAN profile path always
        # smooths; the per-epoch path historically did not. Default
        # True so the coherence panel reads correctly.
        "smooth": True,
        # "wrapped"   keeps phase in (-pi, pi], easier to read structure.
        # "unwrapped" cumulates 2 pi jumps, useful for delay estimation.
        "phase_view": "wrapped",
        # Horizontal coherence threshold line on the bottom panel of
        # the per-epoch tile. The line sits at ``min_coherence`` (the
        # statistical gate the band integrators use) - useful as a
        # visual cue for which bins are being averaged into the band
        # means. Toggle to hide it; the position itself follows
        # ``min_coherence`` so the marker can't drift away from the
        # actual cutoff.
        "show_coherence_threshold": True,
        # Alpha applied to phase points below the coherence threshold,
        # so the user can see where phase is being read off noise.
        # 0.0 fully hides them, 1.0 shows them solid.
        "coherence_mask_alpha": 0.20,
    },
    # ------------------------------------------------------------------
    # Respiration analysis
    # ------------------------------------------------------------------
    # ``RespirationSeries.from_timeseries`` derives its peak-detection
    # prominence from the signal's own MAD/sigma (see the docstring at
    # ``spectHR.DataSet.Series.RespirationSeries.from_timeseries``):
    #
    #   sigma     = 1.4826 * MAD(y)        # robust noise estimate
    #   prominence = prominence_rel * sigma
    #
    # When the full recording mixes resting and task periods, breathing
    # depth and noise level can differ substantially between them. A
    # single global prominence threshold then either misses shallow
    # breaths in one epoch or admits noise as breaths in another. Running
    # the segmentation **per epoch** lets the threshold adapt to each
    # epoch's typical breath amplitude.
    #
    # Set ``per_epoch: true`` to iterate over the recording's epochs and
    # build the RespirationSeries from per-epoch segmentations
    # concatenated together. The default ``experiment`` epoch - which
    # the loaders create as a placeholder spanning the entire recording -
    # is skipped when it still covers the whole signal, so turning the
    # flag on without defining task epochs yet is a no-op.
    "RespirationAnalysis": {
        "per_epoch": False,
        "rsa_lag_s": 1.0,
        "rsa_overlay": "rsa0",
        # Respiration source for RSA / transfer / resp_rate on ICG-capable
        # (VU-AMS) recordings:
        #   "icg"           - thoracic-impedance (ICG / dZ) signal; the
        #                     channel VU-AMS itself scores RSA from (default,
        #                     matches VU-AMS).
        #   "accelerometer" - 3-axis chest-wall accelerometer PCA surrogate;
        #                     useful for ambulatory/movement recordings or
        #                     devices without an ICG channel.
        # Only affects EDF recordings that carry both candidate channels.
        "rsp_source": "icg",
        # Breath rejection mode for the Grossman peak-to-valley RSA algorithm:
        #   "none"   - no extra rejection (default; legacy behaviour).
        #   "strict" - VU-AMS-style guards (irregular IBI + irregular rate);
        #              brings RSA0 closer to VU-AMS output on noisy recordings.
        "rsa_rejection_mode": "none",
    },
}


# ---------------------------------------------------------------------------
# Workspace-level accessors (free functions, since the workspace is a dict)
# ---------------------------------------------------------------------------

# Fallback used by :func:`get_export_dir` when a workspace is missing or
# lacks the ``Directories.OutputDirectory`` entry. Mirrors the value in
# ``_DEFAULT_WORKSPACE`` so the two stay in lock-step automatically.
DEFAULT_EXPORT_DIR = user_documents_path() / "spectHR" / "export"


def get_export_dir(workspace, *, context: str = "Export"):
    """Return ``workspace["Directories"]["OutputDirectory"]`` as a :class:`Path`.

    The workspace is a plain ``dict`` (no class wrapper), so this is the
    canonical accessor for the configured export folder. Centralising it
    here means every widget that writes files (PSDPlotWidget,
    ProfilePlotWidget, ParametersPlotWidget, ...) reaches the directory
    through one code path and shares one fallback rule.

    Parameters
    ----------
    workspace : dict or None
        The workspace dictionary as loaded by :func:`LoadWorkspace`. May
        be ``None`` when a widget was constructed without one.
    context : str, optional
        Short label inserted into the warning message (e.g. ``"PSD"``,
        ``"Profile"``, ``"Parameters"``). Defaults to ``"Export"``.

    Returns
    -------
    pathlib.Path
        The directory the caller should write to. Existence is **not**
        guaranteed - callers should call ``mkdir(parents=True,
        exist_ok=True)`` and handle ``OSError`` themselves.

    Notes
    -----
    When the workspace is ``None`` or the expected nesting is missing
    the function emits a single ``logger.warning`` and falls back to
    :data:`DEFAULT_EXPORT_DIR`, so an export attempt always has somewhere
    to land instead of crashing on a ``KeyError``.
    """
    if workspace is not None:
        try:
            return Path(workspace["Directories"]["OutputDirectory"])
        except (KeyError, TypeError):
            logger.warning(
                f"{context} export: workspace lacks "
                "Directories.OutputDirectory; falling back to default "
                "export folder."
            )
    return DEFAULT_EXPORT_DIR




















def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override values win."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class WorkspaceConfig(dict):
    """Typed wrapper around the workspace dict.

    Subclasses :class:`dict` so all existing ``workspace["Section"]`` and
    ``workspace.get(...)`` call sites continue to work without modification.
    The typed properties below eliminate bare string-key access in new code
    and make the available sections discoverable via auto-complete.

    Construct from any plain dict::

        ws = WorkspaceConfig(LoadWorkspace("myworkspace.json"))

    or let :func:`LoadWorkspace` return one directly.
    """

    # ------------------------------------------------------------------
    # Section properties — each returns the raw sub-dict (or {} on miss)
    # ------------------------------------------------------------------

    @property
    def directories(self) -> dict:
        """``workspace["Directories"]`` with empty-dict guard."""
        return self.get("Directories", {}) or {}

    @property
    def frequency_analysis(self) -> dict:
        """``workspace["FrequencyAnalysis"]`` with empty-dict guard."""
        return self.get("FrequencyAnalysis", {}) or {}

    @property
    def profiles(self) -> dict:
        """``workspace["Profiles"]`` with empty-dict guard."""
        return self.get("Profiles", {}) or {}

    @property
    def spectrogram(self) -> dict:
        """``workspace["Spectrogram"]`` with empty-dict guard."""
        return self.get("Spectrogram", {}) or {}

    @property
    def transfer_analysis(self) -> dict:
        """``workspace["TransferAnalysis"]`` with empty-dict guard."""
        return self.get("TransferAnalysis", {}) or {}

    @property
    def cardiо_parameters(self) -> dict:
        """``workspace["CardioParameters"]`` with empty-dict guard."""
        return self.get("CardioParameters", {}) or {}

    @property
    def respiration_analysis(self) -> dict:
        """``workspace["RespirationAnalysis"]`` with empty-dict guard."""
        return self.get("RespirationAnalysis", {}) or {}

    # ------------------------------------------------------------------
    # Convenience path properties
    # ------------------------------------------------------------------

    @property
    def output_directory(self) -> "Path":
        """Configured output directory as a :class:`~pathlib.Path`."""
        raw = self.directories.get("OutputDirectory")
        return Path(raw) if raw else DEFAULT_EXPORT_DIR

    @property
    def data_directory(self) -> "Path":
        """Configured data directory as a :class:`~pathlib.Path`."""
        raw = self.directories.get("DataDirectory")
        return Path(raw) if raw else Path(".")

    @property
    def cache_directory(self) -> "Path":
        """Configured cache directory as a :class:`~pathlib.Path`."""
        raw = self.directories.get("CacheDirectory")
        return Path(raw) if raw else Path(".")


def LoadWorkspace(json_file=None) -> "WorkspaceConfig":
    """Load the workspace JSON, create the file from defaults if missing.

    Side effects are intentionally minimal: this function only reads /
    writes the JSON file and ensures cache / output directories exist.
    PSD configuration is **not** pushed into any module-level globals -
    callers should use :func:`psd_method_from_workspace` to build a
    :class:`PsdMethod` and pass it explicitly to every compute call.

    Returns
    -------
    dict
        The full nested workspace with all chapters.
    """
    workspace = copy.deepcopy(_DEFAULT_WORKSPACE)

    if json_file is None:
        json_file = user_documents_path() / "DefaultWorkSpace.json"

    specthr_dir = user_documents_path() / "spectHR"
    if not specthr_dir.exists():
        os.makedirs(specthr_dir)

    if os.path.exists(json_file):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            workspace = _deep_merge(workspace, loaded)
        except Exception as e:
            logger.warning(f"Could not load workspace file: {e}")
    else:
        _ensure_dirs(workspace)
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(workspace, f, indent=4, ensure_ascii=False)

    _migrate_respiration_band_to_profiles(workspace)
    _migrate_window_keys(workspace)
    _ensure_dirs(workspace)
    return WorkspaceConfig(workspace)


def _migrate_respiration_band_to_profiles(workspace: dict) -> None:
    """One-time migration of an earlier flag location.

    An interim version of the editor stored the profile-adaptive flag
    *per band* under ``FrequencyAnalysis.bands.<name>.respiration_band``.
    That location was wrong: the flag is consulted only by the profile
    compute, so it conceptually belongs on the Profiles section.

    This function sweeps every band entry, accumulates any band where
    the legacy flag is True into ``Profiles.adaptive_bands``, and
    strips the legacy key from the band dict in place. Bands that
    never had the legacy flag set are left untouched. No-op on
    workspaces that never went through the interim version.

    Logged at INFO level so a user who notices their old JSON has
    been silently rewritten can tell what happened.
    """
    fa_bands = (workspace.get("FrequencyAnalysis", {}) or {}).get("bands", {})
    if not isinstance(fa_bands, dict):
        return
    profiles = workspace.setdefault("Profiles", {})
    adaptive = list(profiles.get("adaptive_bands", []) or [])
    migrated: list[str] = []
    for name, spec in fa_bands.items():
        if not isinstance(spec, dict) or "respiration_band" not in spec:
            continue
        was_adaptive = bool(spec.pop("respiration_band"))
        if was_adaptive and name not in adaptive:
            adaptive.append(name)
            migrated.append(name)
    if migrated:
        profiles["adaptive_bands"] = adaptive
        logger.info(
            "Migrated respiration_band flag from FrequencyAnalysis.bands "
            f"to Profiles.adaptive_bands: {migrated}"
        )

    # Second pass: if adaptive_bands is still a list (old format from the
    # first iteration of the feature), convert it to the new dict format
    # with default half-widths, keeping only the first entry - adaptive
    # tracking is now a single-band setting.
    adaptive_val = profiles.get("adaptive_bands")
    if isinstance(adaptive_val, list):
        first = adaptive_val[:1]  # keep at most one band
        profiles["adaptive_bands"] = {
            name: {
                "lower half-width (Hz)": 0.04,
                "upper half-width (Hz)": 0.04,
            }
            for name in first
        }
        if adaptive_val:
            logger.info(
                "Migrated Profiles.adaptive_bands from list to dict format "
                f"(single-band): {first}"
            )
    # Third pass: if the dict somehow has more than one entry (saved by an
    # interim multi-select version), collapse to the first entry.
    elif isinstance(adaptive_val, dict) and len(adaptive_val) > 1:
        first_key = next(iter(adaptive_val))
        profiles["adaptive_bands"] = {first_key: adaptive_val[first_key]}
        logger.info(
            f"Collapsed multi-entry Profiles.adaptive_bands to single band: {first_key}"
        )


def _migrate_window_keys(workspace: dict) -> None:
    """Rename legacy ``window_s`` / ``step_s`` profile keys.

    An earlier version of ``_DEFAULT_WORKSPACE`` stored the sliding-window
    parameters as ``window_s`` and ``step_s``. The canonical names are now
    ``"window (sec)"`` and ``"step (sec)"`` - the pre-formatted spelling
    that passes through ``_label()`` unchanged and appears cleanly in the
    Edit-Parameters dialog.

    This migration runs on every ``LoadWorkspace`` call. It is idempotent:
    if the new keys already exist they are left untouched (the old values
    are still dropped so the dialog doesn't show duplicates).
    """
    profiles = workspace.get("Profiles")
    if not isinstance(profiles, dict):
        return
    renamed: list[str] = []
    for old, new in (("window_s", "window (sec)"), ("step_s", "step (sec)")):
        if old not in profiles:
            continue
        if new not in profiles:
            profiles[new] = profiles[old]
            renamed.append(f"{old} → {new!r}")
        del profiles[old]
    if renamed:
        logger.info("Migrated Profiles window/step keys: %s", ", ".join(renamed))


def SaveWorkspace(workspace: dict, json_file) -> None:
    """Save the full workspace dict (all chapters) to a JSON file."""
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(workspace, f, indent=4, ensure_ascii=False)


def _ensure_dirs(workspace: dict) -> None:
    """Create CacheDirectory and OutputDirectory if they do not exist."""
    dirs = workspace.get("Directories", {})
    for key in ("CacheDirectory", "OutputDirectory"):
        path = dirs.get(key)
        if path and not os.path.exists(path):
            os.makedirs(path)


# ---------------------------------------------------------------------------
# Note: the workspace -> PsdMethod / settings translation functions now live
# in the headless ``spectHR.config`` module and are re-exported at the top of
# this file. Only Qt / app-IO helpers remain below.
# ---------------------------------------------------------------------------


def PopulateTree(treewidget, workspace: dict) -> None:
    """Populate a QTreeWidget with files from workspace DataDirectory."""
    # Qt is imported locally so this module's other (pure) helpers don't
    # require PySide6 just to be importable.
    from PySide6.QtWidgets import QTreeWidgetItem
    from PySide6.QtCore import Qt

    treewidget.clear()
    data_dir = workspace["Directories"]["DataDirectory"]
    categories = {
        "XDF Files": "*.xdf",
        "VAMS EDF Files": "*.edf",
        "CARSPAN EVT Files": "*.evt",
        "RR Text Files": "*.txt",
    }
    treewidget.setHeaderLabels(["WorkSpace Data"])
    for label, pattern in categories.items():
        parent = QTreeWidgetItem([label])
        extension = pattern.split("*")[-1].lower()
        files = sorted(
            [f for f in os.listdir(data_dir) if f.lower().endswith(extension)]
        )
        for fname in files:
            if fname.lower() == "requirements.txt":
                continue
            item = QTreeWidgetItem(parent, [fname])
            item.setData(
                0,
                Qt.UserRole,
                {
                    "type": "dataset",
                    "filename": fname,
                    "bands_expanded": False,
                },
            )
        treewidget.addTopLevelItem(parent)
    treewidget.expandAll()
