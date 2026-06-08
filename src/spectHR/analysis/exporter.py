# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/exporter.py
"""
EpochExporter: collect per-epoch PSD, profile, transfer and respiration
arrays for CSV / HDF5 export.

This class is **Qt-free and UI-free**.  Moving the computation here means:

* It is independently testable without a Qt environment.
* The ``EpochContext`` objects produced by
  :meth:`~spectHR.DataSet.PhysioData.PhysioData.epoched_parameters_table`
  are *reused* rather than discarded and recomputed.  By the time the export
  pass runs, ``ctx.psd``, ``ctx.rsa_beats``, and ``ctx.pep_detail`` are
  already populated in the context's ``cached_property`` cache — the exporter
  reads them for free.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.profile import (
    compute_band_power_profile,
    profile_band_data,
    profile_summary_scalars,
)
from spectHR.analysis.transfer import (
    compute_transfer,
    compute_transfer_profile,
    resolve_transfer_input,
    transfer_summary_scalars,
)
from spectHR.config import WorkspaceView
from spectHR.Tools.Logger import logger


class EpochExporter:
    """Compute per-epoch export data, reusing :class:`EpochContext` caches.

    Parameters
    ----------
    dataset
        The loaded ``PhysioData`` instance.
    workspace
        Raw workspace configuration dict (or ``None``).
    contexts
        ``dict[label, EpochContext]`` returned as the fourth element of
        :meth:`~spectHR.DataSet.PhysioData.PhysioData.epoched_parameters_table`.
        The PSD, RSA, and ICG computations on each context are already cached;
        only profile / transfer / transfer-profile computations are run fresh.
    """

    def __init__(self, dataset, workspace, contexts: dict) -> None:
        self.dataset = dataset
        self._ws = WorkspaceView(workspace)
        self.contexts: dict = contexts

    # ------------------------------------------------------------------

    def collect(self) -> "dict[str, dict]":
        """Compute all per-epoch export data.

        Returns
        -------
        epoch_data : dict[str, dict]
            Mapping ``label → data`` where each value has keys:

            ``scalars``
                Profile / transfer scalar columns for the CSV.  (The
                ``@epoch_metric`` scalars are added by the caller.)
            ``psd``
                Dict with ``freqs``, ``power``, ``unit``, ``method``,
                ``freq_res``, ``bands`` (per-band sub-dict).
            ``profile``
                Sliding-window band-power profile dict, or ``None``.
            ``transfer``
                Transfer-function dict, or ``None`` (no RSP channel).
            ``transfer_profile``
                Transfer-profile dict, or ``None``.
            ``respiration``
                Per-breath RSA arrays dict, or ``None``.
            ``icg``
                PEP ensemble detail dict, or ``None``.
        """
        ws = self._ws
        if not self.contexts:
            return {}

        psd_method = ws.psd_method
        prof_cfg   = ws.profile_settings
        tf_cfg     = ws.transfer_settings
        emit_bands, adaptive_band_name = ws.resolved_profile_bands

        bands_dict = ws.display_bands
        tf_band_edges = {
            name: (float(spec["low"]), float(spec["high"]))
            for name, spec in bands_dict.items()
            if name != "FullRange" and "low" in spec and "high" in spec
        }

        tf_input_signal = str(tf_cfg["input_signal"])
        rsp_ts, _ = resolve_transfer_input(self.dataset, tf_input_signal)

        result: dict[str, dict] = {}

        for label, ctx in self.contexts.items():
            epoch: dict = {
                "scalars": {}, "psd": None, "profile": None,
                "transfer": None, "transfer_profile": None,
                "respiration": None, "icg": None,
            }

            # ---- PSD (free — ctx.psd already cached) ----------------
            psd_res = ctx.psd
            if psd_res is not None and psd_method is not None:
                try:
                    freqs    = np.asarray(psd_res.freqs)
                    power    = np.asarray(psd_res.power)
                    psd_unit = (psd_res.unit or "").replace("/Hz", "")
                    band_psd: dict = {}
                    for bname, bspec in psd_method.bands.items():
                        mask = (freqs >= bspec.low) & (freqs <= bspec.high)
                        band_psd[bname] = {
                            "freqs":      freqs[mask],
                            "power":      power[mask],
                            "integrated": float(band_power_rectangular(
                                              freqs, power, bspec.low, bspec.high)),
                            "low":  bspec.low,
                            "high": bspec.high,
                        }
                    epoch["psd"] = {
                        "freqs":    freqs,
                        "power":    power,
                        "unit":     psd_res.unit or "",
                        "psd_unit": psd_unit,
                        "method":   psd_res.method or "",
                        "freq_res": float(freqs[1] - freqs[0]) if freqs.size > 1 else 0.0,
                        "bands":    band_psd,
                    }
                except Exception as exc:
                    logger.debug("PSD export failed for epoch %r: %s", label, exc)

            # ---- Profile (computed fresh) ----------------------------
            try:
                view = ctx.view
                prof_res = compute_band_power_profile(
                    view,
                    window_s           = prof_cfg["window_s"],
                    step_s             = prof_cfg["step_s"],
                    psd_method         = psd_method,
                    adaptive_source    = prof_cfg["adaptive_source"],
                    smooth_breath_freq = prof_cfg["smooth_breath_freq"],
                )
                ts    = np.asarray(prof_res.timestamps)
                t_rel = (
                    ts - (ts[0] - prof_cfg["window_s"] / 2.0)
                    if ts.size else ts
                )
                band_prof = profile_band_data(prof_res, t_rel, emit_bands=emit_bands)

                epoch["scalars"].update(profile_summary_scalars(
                    prof_res, t_rel,
                    emit_bands=emit_bands,
                    window_s=prof_cfg["window_s"],
                    step_s=prof_cfg["step_s"],
                    adaptive_band_name=adaptive_band_name,
                    adaptive_source=prof_cfg["adaptive_source"],
                ))

                resp_freqs = (
                    np.asarray(prof_res.resp_freqs, dtype=np.float64).ravel()
                    if prof_res.resp_freqs is not None else None
                )
                epoch["profile"] = {
                    "timestamps": ts,
                    "t_rel":      t_rel,
                    "unit":       prof_res.unit or "",
                    "method":     prof_res.method or "",
                    "window_s":   prof_cfg["window_s"],
                    "step_s":     prof_cfg["step_s"],
                    "adaptive_band":   adaptive_band_name or "",
                    "adaptive_source": prof_cfg["adaptive_source"],
                    "resp_freqs": resp_freqs,
                    "bands":      band_prof,
                }
            except Exception as exc:
                logger.debug("Profile export failed for epoch %r: %s", label, exc)

            # ---- Transfer (computed fresh) ---------------------------
            if rsp_ts is not None and tf_band_edges:
                try:
                    tf_res = compute_transfer(
                        ctx.view, rsp_ts,
                        input_signal  = tf_input_signal,
                        bands         = tf_band_edges,
                        min_coherence = float(tf_cfg["min_coherence"]),
                        smooth        = bool(tf_cfg["smooth"]),
                        f_max         = float(tf_cfg["f_max"]),
                    )
                    tf_freqs = np.asarray(tf_res.freqs)
                    tf_mod   = np.asarray(tf_res.modulus)
                    tf_pw    = np.asarray(tf_res.phase_wrapped)
                    tf_pu    = np.asarray(tf_res.phase_unwrapped)
                    tf_coh   = np.asarray(tf_res.coherence)

                    band_tf: dict = {}
                    for bname, (blow, bhigh) in tf_band_edges.items():
                        mask = (tf_freqs >= blow) & (tf_freqs <= bhigh)
                        bt   = (tf_res.band_results or {}).get(bname)
                        band_tf[bname] = {
                            "freqs":               tf_freqs[mask],
                            "modulus_raw":         tf_mod[mask],
                            "phase_wrapped_raw":   tf_pw[mask],
                            "phase_unwrapped_raw": tf_pu[mask],
                            "coherence_raw":       tf_coh[mask],
                            "low":   blow,
                            "high":  bhigh,
                            "modulus":            float(bt.modulus)            if bt else np.nan,
                            "phase_wrapped":      float(bt.phase)              if bt else np.nan,
                            "phase_unwrapped":    float(bt.phase_unwrapped)    if bt else np.nan,
                            "weighted_coherence": float(bt.weighted_coherence) if bt else np.nan,
                            "n_points":           int(bt.n_points)             if bt else 0,
                            "n_coherent":         int(bt.n_coherent)           if bt else 0,
                        }

                    epoch["scalars"].update(transfer_summary_scalars(
                        tf_res,
                        smooth        = bool(tf_cfg["smooth"]),
                        min_coherence = float(tf_cfg["min_coherence"]),
                        f_max         = float(tf_cfg["f_max"]),
                    ))

                    epoch["transfer"] = {
                        "freqs":          tf_freqs,
                        "modulus":        tf_mod,
                        "phase_wrapped":  tf_pw,
                        "phase_unwrapped":tf_pu,
                        "coherence":      tf_coh,
                        "method":         tf_res.method or "",
                        "freq_resolution":float(tf_res.freq_resolution),
                        "smooth":         bool(tf_cfg["smooth"]),
                        "min_coherence":  float(tf_cfg["min_coherence"]),
                        "f_max":          float(tf_cfg["f_max"]),
                        "bands":          band_tf,
                    }
                except Exception as exc:
                    logger.debug("Transfer export failed for epoch %r: %s", label, exc)

                # ---- Transfer profile (computed fresh) ---------------
                try:
                    tfp_res = compute_transfer_profile(
                        ctx.view, rsp_ts,
                        input_signal  = tf_input_signal,
                        bands         = tf_band_edges,
                        window_s      = float(tf_cfg["window_s"]),
                        step_s        = float(tf_cfg["step_s"]),
                        min_coherence = float(tf_cfg["min_coherence"]),
                        f_max         = float(tf_cfg["f_max"]),
                        smooth        = bool(tf_cfg["smooth"]),
                    )
                    band_tfp: dict = {}
                    for b, bname in enumerate(tfp_res.band_names):
                        band_tfp[bname] = {
                            "modulus":            np.asarray(tfp_res.modulus[b]),
                            "phase":              np.asarray(tfp_res.phase[b]),
                            "phase_unwrapped":    np.asarray(tfp_res.phase_unwrapped[b]),
                            "weighted_coherence": np.asarray(tfp_res.weighted_coherence[b]),
                            "n_coherent":         np.asarray(tfp_res.n_coherent[b],
                                                             dtype=np.int32),
                        }
                    epoch["transfer_profile"] = {
                        "timestamps":    np.asarray(tfp_res.timestamps),
                        "method":        tfp_res.method or "",
                        "window_s":      float(tf_cfg["window_s"]),
                        "step_s":        float(tf_cfg["step_s"]),
                        "smooth":        bool(tf_cfg["smooth"]),
                        "min_coherence": float(tf_cfg["min_coherence"]),
                        "f_max":         float(tf_cfg["f_max"]),
                        "bands":         band_tfp,
                    }
                except Exception as exc:
                    logger.debug(
                        "Transfer-profile export failed for epoch %r: %s", label, exc)

            # ---- RSA per-breath (free — ctx.rsa_beats already cached) --
            rsa_raw = ctx.rsa_beats
            if rsa_raw is not None and rsa_raw.size > 0:
                try:
                    rsa0_arr = np.where(
                        np.isfinite(rsa_raw) & (rsa_raw > 0), rsa_raw, 0.0,
                    )
                    epoch["respiration"] = {
                        "rsa":          rsa_raw,
                        "rsa0":         rsa0_arr,
                        "breath_times": ctx.breath_times[:rsa_raw.size],
                        "lag_s":        ctx.rsa_lag_s,
                        "n_breaths":    int(rsa_raw.size),
                        "n_valid":      int(
                            np.sum(np.isfinite(rsa_raw) & (rsa_raw > 0))
                        ),
                    }
                except Exception as exc:
                    logger.debug("RSA export failed for epoch %r: %s", label, exc)

            # ---- ICG ensemble (free — ctx.pep_detail already cached) ---
            detail = ctx.pep_detail
            if detail is not None:
                epoch["icg"] = detail

            result[label] = epoch

        return result
