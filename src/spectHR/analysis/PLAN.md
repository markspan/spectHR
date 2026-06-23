# Implementation plan: additional Results metrics

> **Status (2026-06): Phases 1 and 2 are implemented.** Frequency completeness
> (`total_power`, `lf_nu`, `hf_nu`, `ln_hf`, `band_rel`/`band_peak` groups),
> time-domain staples (`nn50`/`pnn50`/`nn20`/`pnn20`, `mean_hr`/`sd_hr`,
> `cvnn`/`cvsd`, `hrv_ti`, `tinn`), Poincaré `csi`/`cvi`/`modified_csi`,
> `dfa_a2`, ICG `heather_index`, respiration `resp_rate_bpm`/`rrv`, and BP
> `sbp_sd`/`dbp_sd` are live, with tests in `tests/test_ecg_extra_metrics.py`
> and `tests/test_phase2_metrics.py`. **Phase 3 (entropy) remains.**

A concrete, ordered plan for the next per-epoch metrics, turning the candidate
list in the top-level [`roadmap.MD`](../../../roadmap.MD) into specs an
implementer can pick up. Scope here is the **cheap, high-value columns that
reuse data the `EpochContext` already caches**, so each is a small
`@epoch_metric` that appears in the Results table and the CSV / HDF5 export
automatically. The larger items (artefact correction, ICG hemodynamics beyond
the Heather index, sequence-method BRS, spectral BP variability, event-related
responses) stay in `roadmap.MD`; they are pipeline stages or new docks, not
columns, and are out of scope for this plan.

## Baseline (already implemented, do not re-add)

Registered today: `count mean median min max rmssd sdnn sdsd sd1 sd2 sd_ratio
ellipse_area stationarity stationarity_z dfa_a1 dc ac lf_hf_ratio
twave_amplitude` plus the `band_powers` group; `bp_sbp/dbp/pp/map`;
`resp_freq hf_resp_in_band resp_mvo resp_svo rsa rsa0`; `pep pep_q/b/c_ms
pep_n_beats`; and the `transfer_band_metrics` group.

## Conventions for every item below

* One function decorated `@epoch_metric` (column name = function name), in the
  series module from [`README.md`](README.md). Group metrics use
  `@epoch_metric_group` when the columns are data-driven (one per band).
* **Reuse the cached intermediates** on the `EpochContext` (`ctx.psd`,
  `ctx.bp_beats`, `ctx.resp_beats`, `ctx.rsa_beats`, `ctx.pep_detail`), never
  recompute them. A bare time-domain metric may take the IBI series and use
  `ibi_clean_ms` / `successive_diffs_ms` from `ibi_helpers`.
* In `ecg_metrics.py` the `min`/`max` HRV metrics shadow the builtins; use
  `builtins.min` / `builtins.max` (or `np`).
* Return `float("nan")` when the inputs are missing or too short; never raise
  (the table swallows exceptions to NaN, which hides bugs, see the
  `twave_amplitude` regression). Add a value-checking test per metric.

---

## Phase 1: cheap wins on the cached PSD and the IBI series

These need no new computation, only arithmetic on `ctx.psd` (`.freqs`, `.power`)
and the IBI series, and they round out the table researchers compare against
Kubios / NeuroKit2.

### 1a. Frequency-domain completeness (`ecg_metrics.py`, reads `ctx.psd`)

| Column | Definition |
|---|---|
| `total_power` | Power integrated over VLF+LF+HF (the conventional total); NaN if those bands are absent. |
| `lf_nu` | `100 * LF / (LF + HF)`. |
| `hf_nu` | `100 * HF / (LF + HF)`. |
| `ln_hf` | `ln(HF)` (natural log of HF power). |
| `band_rel` *(group)* | `{band}_pct` = `100 * band / total_power`, one per configured band (data-driven, parallels `band_powers`). |
| `band_peak` *(group)* | `{band}_peak_hz` = frequency of the maximum PSD value inside the band. |

LF/HF read `ctx.psd_method.bands["LF"|"HF"]`; reuse `band_power_rectangular`
already used by `band_powers`. Standard-name metrics yield NaN when a band was
renamed away.

### 1b. Time-domain staples (`ecg_metrics.py`, reads the IBI series)

| Column | Definition |
|---|---|
| `nn50` / `pnn50` | count and `%` of successive `|ΔIBI| > 50 ms`. |
| `nn20` / `pnn20` | same at 20 ms. |
| `mean_hr` | `60000 / mean(IBI_ms)` (bpm). |
| `sd_hr` | SD of the per-beat instantaneous HR `60000 / IBI_ms`. |
| `cvnn` | `100 * sdnn / mean` (coefficient of variation of IBIs). |
| `cvsd` | `100 * sdsd / mean`. |
| `hrv_ti` | HRV triangular index: `N / max(histogram count)`, IBI histogram at 1/128 s (7.8125 ms) bins. |
| `tinn` | Triangular Interpolation of the NN histogram (ms), base width of the fitted triangle. |

### 1c. Poincaré complements (`ecg_metrics.py`, reuse `sd1`/`sd2`)

| Column | Definition |
|---|---|
| `csi` | Cardiac Sympathetic Index `L / T`, with `T = 4·SD1`, `L = 4·SD2` (Toichi 1997). |
| `cvi` | Cardiac Vagal Index `log10(L · T)`. |
| `modified_csi` | `L² / T`. |

### 1d. Non-linear, near-free (`ecg_metrics.py`, reuse the DFA machinery)

| Column | Definition |
|---|---|
| `dfa_a2` | Long-term DFA scaling exponent over box sizes 16-64 beats (second scale range of `dfa_fluctuation`); NaN below `2·64` beats. |

**Phase-1 acceptance:** each column verified against its definition on a
synthetic IBI/PSD series, and `lf_nu + hf_nu ≈ 100` by construction. One test
module (`tests/test_ecg_extra_metrics.py`).

---

## Phase 2: small additions on the other cached series

### 2a. ICG Heather index (`icg_metrics.py`, reads `ctx.pep_detail`)

`heather_index` = `(dZ/dt)max at the C-point / (t_C - t_Q)` (Ω/s²), a
contractility index. The ensemble already scores Q and C and carries the
`dZ/dt` ensemble, so this is a read of `pep_detail` (no new detection). NaN when
no ICG channel or no scorable ensemble. *(LVET / SV / CO / TPR stay in the
roadmap: they need X-point detection and the thoracic constants ρ, L, Z0.)*

### 2b. Respiration (`respiration_metrics.py`, reuse `_mean_breath_hz` / `rsp_phases`)

| Column | Definition |
|---|---|
| `resp_rate_bpm` | `60 * resp_freq` (breaths per minute), the clinician-facing unit. |
| `rrv` | Respiration-rate variability: SD of the per-cycle breath durations from `rsp_phases`. |

### 2c. Blood-pressure variability, time-domain (`bp_metrics.py`, reads `ctx.bp_beats`)

| Column | Definition |
|---|---|
| `sbp_sd` | `nanstd` of the per-beat systolic series. |
| `dbp_sd` | `nanstd` of the per-beat diastolic series. |

*(Spectral BP variability, e.g. LF-SBP, is a separate PSD pass on the per-beat
BP series, roadmap item 2.4.)*

---

## Phase 3: entropy family (new calculator)

`sampen` and `apen` on the IBI series (m = 2, r = 0.2·SDNN by default; expose m
and r; require a minimum beat count). Self-contained in `ecg_metrics.py`.
`mse` (multiscale entropy) is a later extension. These are sensitive to
artefacts and series length, so they benefit from the roadmap's artefact
correction (1.1) landing first; until then, blank them on short epochs.

---

## Validation and provenance (alongside the work, not after)

* A test per metric pins it to an independently computed value on a synthetic
  signal; where a standard exists, cross-check against Kubios / NeuroKit2 on a
  shared recording within a stated tolerance (extend
  [`docs/ALGORITHM_AUDIT.md`](../../../docs/ALGORITHM_AUDIT.md)).
* Keep every column's unit in its docstring (the Results headers surface it as a
  tooltip); normalised / dimensionless columns say so.

## Suggested order

1. Phase 1a + 1b (frequency completeness + time-domain staples), the highest
   value-to-effort and what reviewers expect by default.
2. Phase 1c + 1d (CSI/CVI, DFA-α2).
3. Phase 2a Heather index, then 2b respiration, then 2c BP variability.
4. Phase 3 entropy.

References for the formulae are in the top-level
[`readme.MD` § References](../../../readme.MD#references) and `roadmap.MD`.
