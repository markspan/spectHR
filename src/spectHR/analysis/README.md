# `spectHR/analysis/`: metric reference

This package holds spectHR's **headless** analysis library (no Qt, no
matplotlib). It computes every per-epoch scalar shown in the Results dock and
written to the CSV / HDF5 export, plus the windowed/spectral series the plot
docks draw.

The modules are organised **by the physiological series the metrics come
from**, one module per series type. If you are looking for where a column in
the Results table or the CSV is calculated, find its series below.

---

## How the metric system works

* A metric is a plain function decorated with **`@epoch_metric`** (one scalar →
  one column) or **`@epoch_metric_group`** (a dict → several data-driven
  columns, e.g. one per frequency band). The decorator registers it in
  [`registry.py`](registry.py); the **column name is the function name**.
* `Session.epochs_table(config)` evaluates every registered metric per active
  epoch. Each metric receives an
  **[`EpochContext`](epoch_context.py)**, the epoch's R-peak view plus the
  workspace settings (`psd_method`, RSA lag, …) and lazily-cached, shared
  intermediates: the PSD, the per-beat BP/respiration dicts, the per-breath RSA
  array and the PEP ensemble. Caching means the expensive passes run **once per
  epoch**, no matter how many columns read them.
* Importing `spectHR.analysis` imports every metric submodule, which is what
  populates the registry (see [`__init__.py`](__init__.py)).
* The [`exporter.py`](exporter.py) `EpochExporter` turns the table + the cached
  per-epoch arrays into the `<name>.csv` (scalars) and `<name>.h5` (all arrays
  and summary scalars) files.

**Convention, standard deviation.** Every SD / variance in this package uses the
**population estimator** (numpy default `ddof=0`, divide by N), not the N-1
sample estimator. This is CARSPAN parity, the original Pascal SD routines all
divide by the count (`T_EventFile.pas` `GetSampMeanAndStdDev`, `T_DataCorrect.pas`,
`T_AnaFunctions.pas`). It keeps the derived metrics mutually consistent (e.g.
`cvnn == 100·sdnn/mean`, `sd1 == sdsd/√2`). Do not switch any metric to `ddof=1`.

Scientific citations are not duplicated here, the algorithm docstrings and the
top-level [`readme.MD` § References](../../../readme.MD#references) carry the full
bibliography (Mulder, Grossman, Billman, Robbe, Riese, Lozano, Peng, Bauer, van
Roon, Task Force 1996, …).

---

## Series → module map

| Series (channel) | Module | Registered columns |
|---|---|---|
| **ECG → R-peaks → IBI** | [`ecg_metrics.py`](ecg_metrics.py) | `count` `mean` `median` `min` `max` `rmssd` `sdnn` `sdsd` `nn50` `pnn50` `nn20` `pnn20` `mean_hr` `sd_hr` `cvnn` `cvsd` `hrv_ti` `tinn` `sd1` `sd2` `sd_ratio` `ellipse_area` `csi` `cvi` `modified_csi` `stationarity` `stationarity_z` `dfa_a1` `dfa_a2` `dc` `ac` `lf_hf_ratio` `total_power` `lf_nu` `hf_nu` `ln_hf` `twave_amplitude` + `band_powers`/`band_rel`/`band_peak` groups (`{band}_power`/`_pct`/`_peak_hz`) |
| **Blood pressure** waveform | [`bp_metrics.py`](bp_metrics.py) | `bp_sbp` `bp_dbp` `bp_pp` `bp_map` `sbp_sd` `dbp_sd` |
| **Respiration** (+ RSA) | [`respiration_metrics.py`](respiration_metrics.py) | `resp_freq` `resp_rate_bpm` `rrv` `hf_resp_in_band` `resp_mvo` `resp_svo` `rsa` `rsa0` |
| **ICG** (`dZ/dt`, sympathetic) | [`icg_metrics.py`](icg_metrics.py) | `pep` `pep_b_ms` `pep_c_ms` `pep_q_ms` `pep_n_beats` `heather_index` |
| **input → HR coupling** (BP or resp) | [`transfer_metrics.py`](transfer_metrics.py) | `transfer_band_metrics` group (`{band}_tf_modulus`, `{band}_tf_coherence`, `{band}_tf_phase_w`) |

---

## ECG / IBI series: [`ecg_metrics.py`](ecg_metrics.py)

Everything here is computed from the cleaned inter-beat intervals (artefact
beats dropped by [`ibi_helpers.py`](ibi_helpers.py)). Grouped by HRV method:

* **Time-domain**, `count`, `mean`, `median`, `min`, `max` (IBI magnitude);
  `rmssd` (RMS of successive differences), `sdnn` (SD of IBIs), `sdsd` (SD of
  successive differences), all in ms. `nn50`/`pnn50` and `nn20`/`pnn20` (count
  and % of successive differences exceeding 50 / 20 ms), `mean_hr`/`sd_hr`
  (mean and SD of the per-beat instantaneous heart rate, bpm), `cvnn`/`cvsd`
  (coefficients of variation `100·SDNN/mean` and `100·SDSD/mean`, %).
* **Geometric** (Task Force 1996, 1/128 s histogram bins), `hrv_ti` (triangular
  index, total IBIs / modal-bin height) and `tinn` (base width of the
  least-squares triangle fitted to the IBI histogram, ms).
* **Stationarity**, `stationarity` (IBI-vs-time linear correlation) and
  `stationarity_z` (reverse-arrangements z-score; `|z| > 1.96` flags a
  non-stationary epoch where whole-epoch spectra should be read with care).
* **Poincaré**, `sd1` (minor axis = `std(ΔIBI)/√2`), `sd2` (major axis via
  Brennan's identity `SD2² = 2·Var(IBI) − ½·Var(ΔIBI)`), `sd_ratio` (SD1/SD2),
  `ellipse_area` (`π·SD1·SD2`). `csi`/`cvi`/`modified_csi` (Toichi 1997 cardiac
  sympathetic `SD2/SD1`, vagal `log₁₀(16·SD1·SD2)` and modified `L²/T` indices).
* **Non-linear**, `dfa_a1` / `dfa_a2`: short- and long-term detrended-fluctuation
  scaling exponents (slope of `log F(n)` vs `log n`) over box sizes 4–16 and
  16–64 beats respectively, sharing one forward-segmentation implementation.
* **PRSA**, `dc` / `ac`: deceleration / acceleration capacity by phase-rectified
  signal averaging (anchor on IBI increases/decreases, average ±T beats, apply
  the four-point formula; `T = PrsaAnalysis.prsa_window`, default 30).
* **Frequency-domain**, `band_powers` emits one `{band}_power` column per
  configured band (rectangular integration of the IBI PSD); `band_rel`
  (`{band}_pct`, each band as % of the named-band total) and `band_peak`
  (`{band}_peak_hz`, frequency of the in-band PSD maximum). `total_power` (sum
  of the named non-FullRange bands), `lf_nu`/`hf_nu` (normalised units
  `100·LF/(LF+HF)` and `100·HF/(LF+HF)`), `ln_hf` (`ln` of HF power), and
  `lf_hf_ratio` the LF/HF quotient (report descriptively, not a clean
  sympatho-vagal index). The PSD itself is computed by the [`psd/`](psd/)
  sub-package (CARSPAN, Welch or Lomb-Scargle back-ends) and cached on the
  `EpochContext`.

## Blood-pressure series: [`bp_metrics.py`](bp_metrics.py)

CARSPAN-faithful beat-by-beat values, each gated on a cardiac interval
`[Rᵢ, Rᵢ₊₁]`, then averaged (`nanmean`) over the epoch:

* `bp_sbp` systolic (per-beat max), `bp_dbp` diastolic (foot minimum before the
  systolic peak), `bp_pp` pulse pressure (SBP − DBP), `bp_map` mean arterial
  pressure (true integral mean of the waveform between successive diastoles, not
  the `(SBP+2·DBP)/3` textbook form).
* `sbp_sd` / `dbp_sd` beat-to-beat BP variability (SD of the per-beat systolic /
  diastolic values over the epoch, mmHg).
* A scale-invariant **flat-line guard** (`is_flatline`) rejects beats from a
  clamped/disconnected transducer to `NaN`.

## Respiration series: [`respiration_metrics.py`](respiration_metrics.py)

All respiration-derived metrics, on the channel alone or coupled to the R-peaks:

* **Breathing-frequency context** (Grossman & Taylor 2007), `resp_freq` (mean
  breathing frequency, Hz), `resp_rate_bpm` (`60·resp_freq`, breaths per minute),
  `rrv` (respiration-rate variability, SD of the per-cycle breath durations, s)
  and `hf_resp_in_band` (True/False flag: is the mean breathing frequency inside
  the HF band? a False warns the epoch's HF power may not index RSA).
* **Respiratory volume** (CARSPAN), `resp_mvo` (mean respiration per cardiac
  interval) and `resp_svo` (mean over the half-window of samples ending at each
  R-peak).
* **Respiratory sinus arrhythmia** (Grossman 1990 peak-to-valley), `rsa` (mean
  over valid breath cycles, ms) and `rsa0` (VU-DAMS variant counting invalid
  breaths as zero over the total breath count). Per-breath shortest/longest IBI
  search with optional VU-DAMS code-5/-6 artefact guards.

## ICG series: [`icg_metrics.py`](icg_metrics.py)

Pre-ejection period from the impedance-cardiogram `dZ/dt`, R-peak-locked
ensemble averaging (integer indexing on a uniform grid):

* `pep` (ms, Q-onset → B-point), `pep_q_ms` / `pep_b_ms` / `pep_c_ms` (the scored
  landmark latencies) and `pep_n_beats` (beats in the ensemble). The B-point is
  the max upstroke acceleration before the C-point, searched within the
  `IcgAnalysis.b_point_guard_ms` window.
* `heather_index` contractility index, the peak `dZ/dt` at the C-point divided by
  the Q-to-C interval (s), read off the same ensemble.

## Coupling (transfer): [`transfer_metrics.py`](transfer_metrics.py)

`transfer_band_metrics` emits per-band modulus / phase / weighted-coherence
columns for the input→HR transfer function. The heavy computation lives in
[`transfer.py`](transfer.py); the default input is systolic BP (baroreflex),
falling back to respiration when no BP channel is present.

---

## Supporting modules (no registered metrics)

| Module | Role |
|---|---|
| [`registry.py`](registry.py) | the `@epoch_metric` / `@epoch_metric_group` decorators and the registry |
| [`epoch_context.py`](epoch_context.py) | per-epoch evaluation context + cached shared intermediates |
| [`exporter.py`](exporter.py) | `EpochExporter` → CSV (scalars) + HDF5 (all arrays) |
| [`ibi_helpers.py`](ibi_helpers.py) | artefact-aware IBI cleaning / successive-difference helpers |
| [`_beat_sampling.py`](_beat_sampling.py) | shared waveform-at-R-peak sampling helpers (BP + respiration) |
| [`psd/`](psd/) | PSD back-ends (CARSPAN / Welch / Lomb-Scargle) + band-power integration |
| [`profile.py`](profile.py) | sliding-window band-power profiles (Profiles dock) |
| [`spectrogram.py`](spectrogram.py) | time-frequency spectrogram (Spectrogram dock) |
| [`transfer.py`](transfer.py) | input→HR transfer-function and transfer-profile computation |
| [`derived_series.py`](derived_series.py) | HR / tachogram and other display-only derived series |
| [`detrend.py`](detrend.py) · [`_smoothing.py`](_smoothing.py) | detrending and the CARSPAN display smoother |

---

## Adding a metric

1. Decide which series it belongs to and open that module (create a new
   `*_metrics.py` only for a genuinely new series).
2. Write `@epoch_metric def my_metric(ctx) -> float:` (or a `@epoch_metric_group`
   for data-driven multi-column output). Read cached intermediates off `ctx`
   rather than recomputing.
3. List it in the module's header docstring.
4. It now appears automatically in the Results table and the CSV/HDF5 export,
   no wiring needed. Add a test under `tests/`.

See [`PLAN.md`](PLAN.md) for the concrete, ordered plan of the next metrics to
add (specs, formulae, which cached input each reuses), and the top-level
[`roadmap.MD`](../../../roadmap.MD) for the broader feature wishlist.

---

## Metric reference

One anchored section per registered metric: its docstring, the wrapper-to-
algorithm call chain (most metrics are thin wrappers that delegate to a helper or
a cached intermediate), and a link to the function that does the real
computation. So the Results dock can deep-link a column header straight to its
description, and from there to the maths. **This block is auto-generated**, run
`python -m spectHR.analysis._docgen` to refresh it after changing a metric
docstring or its delegation; a test keeps it in sync. Do not edit between the
markers by hand.

<!-- METRIC-REFERENCE:START -->

### ac

Acceleration Capacity (AC) in ms, PRSA sympatho-vagal index.

Call chain: `ac` -> `_prsa`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`_prsa`)

### band_peak

``{band}_peak_hz``: frequency of the maximum PSD value inside each band.

Group metric: emits several data-driven columns.

Source: [`ecg_metrics.py`](ecg_metrics.py) (`band_peak`)

### band_powers

``{band}_power`` column for every configured frequency band.

Group metric: emits several data-driven columns.

Call chain: `band_powers` -> `band_power_rectangular`

Algorithm: [`_band_power.py`](_band_power.py) (`band_power_rectangular`)

### band_rel

``{band}_pct``: each configured band's % of the total (non-FullRange) power.

Group metric: emits several data-driven columns.

Source: [`ecg_metrics.py`](ecg_metrics.py) (`band_rel`)

### bp_dbp

Diastolic blood pressure, epoch mean of the per-beat foot minima (CARSPAN).

Call chain: `bp_dbp` -> `_bp_metric` -> `bp_beat_parameters`

Algorithm: [`bp_metrics.py`](bp_metrics.py) (`bp_beat_parameters`)

### bp_map

Mean arterial pressure, epoch mean of the waveform integral mean (CARSPAN).

Call chain: `bp_map` -> `_bp_metric` -> `bp_beat_parameters`

Algorithm: [`bp_metrics.py`](bp_metrics.py) (`bp_beat_parameters`)

### bp_pp

Pulse pressure (SBP - DBP), epoch mean over beats (CARSPAN).

Call chain: `bp_pp` -> `_bp_metric` -> `bp_beat_parameters`

Algorithm: [`bp_metrics.py`](bp_metrics.py) (`bp_beat_parameters`)

### bp_sbp

Systolic blood pressure, epoch mean of the per-beat maxima (CARSPAN).

Call chain: `bp_sbp` -> `_bp_metric` -> `bp_beat_parameters`

Algorithm: [`bp_metrics.py`](bp_metrics.py) (`bp_beat_parameters`)

### count

Total number of valid inter-beat intervals.

Source: [`ecg_metrics.py`](ecg_metrics.py) (`count`)

### csi

Cardiac Sympathetic Index L/T (T = 4·SD1, L = 4·SD2; Toichi 1997).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`csi`)

### cvi

Cardiac Vagal Index log10(L·T) = log10(16·SD1·SD2) (Toichi 1997).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`cvi`)

### cvnn

Coefficient of variation of the IBIs: 100 * SDNN / mean (percent).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`cvnn`)

### cvsd

Coefficient of variation of successive differences: 100 * SDSD / mean (percent).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`cvsd`)

### dbp_sd

Beat-to-beat diastolic BP variability: SD of the per-beat DBP (mmHg).

Call chain: `dbp_sd` -> `_bp_std` -> `bp_beat_parameters`

Algorithm: [`bp_metrics.py`](bp_metrics.py) (`bp_beat_parameters`)

### dc

Deceleration Capacity (DC) in ms, PRSA parasympathetic index.

Call chain: `dc` -> `_prsa`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`_prsa`)

### dfa_a1

DFA short-term scaling exponent α1 (Peng et al. 1995, box sizes 4-16 beats).

Call chain: `dfa_a1` -> `dfa_alpha1`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`dfa_alpha1`)

### dfa_a2

DFA long-term scaling exponent α2 (Peng et al. 1995, box sizes 16-64 beats).

Call chain: `dfa_a2` -> `dfa_alpha1`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`dfa_alpha1`)

### ellipse_area

Area of the Poincaré ellipse, ``π · SD1 · SD2`` (ms²).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`ellipse_area`)

### heather_index

Heather index of myocardial contractility (needs ICG dZ/dt + ECG).

Source: [`icg_metrics.py`](icg_metrics.py) (`heather_index`)

### hf_nu

HF power in normalised units: 100 * HF / (LF + HF).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`hf_nu`)

### hf_resp_in_band

True if mean breathing frequency lies inside the HF band, else False (Grossman & Taylor 2007). A False value flags that the epoch's HF power may not reflect RSA.

Call chain: `hf_resp_in_band` -> `_mean_breath_hz` -> `mean_breath_frequency_hz`

Algorithm: [`RespirationSegmentation.py`](RespirationSegmentation.py) (`mean_breath_frequency_hz`)

### hrv_ti

HRV triangular index: total IBIs / height of the modal histogram bin (1/128 s bins).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`hrv_ti`)

### lf_hf_ratio

LF/HF ratio. Historically read as sympatho-vagal balance, but that interpretation is not supported by current evidence (Billman 2013; Reyes del Paso et al. 2013), LF reflects mixed autonomic influences, not a clean sympathetic index. Report the ratio descriptively.

Source: [`ecg_metrics.py`](ecg_metrics.py) (`lf_hf_ratio`)

### lf_nu

LF power in normalised units: 100 * LF / (LF + HF).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`lf_nu`)

### ln_hf

Natural log of HF power, ln(HF).

Call chain: `ln_hf` -> `_band_power`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`_band_power`)

### max

Maximum IBI (ms).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`max`)

### mean

Mean IBI (ms).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`mean`)

### mean_hr

Mean heart rate in bpm = 60000 / mean(IBI in ms).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`mean_hr`)

### median

Median IBI (ms).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`median`)

### min

Minimum IBI (ms).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`min`)

### modified_csi

Modified Cardiac Sympathetic Index L²/T (Toichi 1997).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`modified_csi`)

### nn20

Number of successive IBI differences greater than 20 ms.

Call chain: `nn20` -> `_nn_pnn`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`_nn_pnn`)

### nn50

Number of successive IBI differences greater than 50 ms.

Call chain: `nn50` -> `_nn_pnn`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`_nn_pnn`)

### pep

Pre-ejection period from the ensemble-averaged complex (ms; needs ICG dZ/dt).

Call chain: `pep` -> `pep_ensemble`

Algorithm: [`icg_metrics.py`](icg_metrics.py) (`pep_ensemble`)

### pep_b_ms

B-point (aortic-valve opening) latency relative to the R-peak, ms (needs ICG dZ/dt).

Call chain: `pep_b_ms` -> `_pep_detail_field` -> `pep_ensemble`

Algorithm: [`icg_metrics.py`](icg_metrics.py) (`pep_ensemble`)

### pep_c_ms

C-point (peak ejection velocity) latency relative to the R-peak, ms (needs ICG dZ/dt).

Call chain: `pep_c_ms` -> `_pep_detail_field` -> `pep_ensemble`

Algorithm: [`icg_metrics.py`](icg_metrics.py) (`pep_ensemble`)

### pep_n_beats

Number of beats in the PEP ensemble average for the epoch (needs ICG dZ/dt).

Call chain: `pep_n_beats` -> `_pep_detail_field` -> `pep_ensemble`

Algorithm: [`icg_metrics.py`](icg_metrics.py) (`pep_ensemble`)

### pep_q_ms

Q-onset latency relative to the R-peak, ms (≤ 0; needs ICG dZ/dt + ECG).

Call chain: `pep_q_ms` -> `_pep_detail_field` -> `pep_ensemble`

Algorithm: [`icg_metrics.py`](icg_metrics.py) (`pep_ensemble`)

### pnn20

Percentage of successive IBI differences greater than 20 ms.

Call chain: `pnn20` -> `_nn_pnn`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`_nn_pnn`)

### pnn50

Percentage of successive IBI differences greater than 50 ms.

Call chain: `pnn50` -> `_nn_pnn`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`_nn_pnn`)

### resp_freq

Mean breathing frequency in Hz (blank when no respiration channel).

Call chain: `resp_freq` -> `_mean_breath_hz` -> `mean_breath_frequency_hz`

Algorithm: [`RespirationSegmentation.py`](RespirationSegmentation.py) (`mean_breath_frequency_hz`)

### resp_mvo

Mean respiratory volume per cardiac interval, epoch mean (CARSPAN) (no unit!).

Call chain: `resp_mvo` -> `_resp_metric` -> `resp_beat_parameters`

Algorithm: [`respiration_metrics.py`](respiration_metrics.py) (`resp_beat_parameters`)

### resp_rate_bpm

Mean breathing rate in breaths per minute (60 * resp_freq).

Source: [`respiration_metrics.py`](respiration_metrics.py) (`resp_rate_bpm`)

### resp_svo

Sample respiratory volume at each R-peak, epoch mean (CARSPAN) (no unit!).

Call chain: `resp_svo` -> `_resp_metric` -> `resp_beat_parameters`

Algorithm: [`respiration_metrics.py`](respiration_metrics.py) (`resp_beat_parameters`)

### rmssd

Root mean square of successive differences (ms).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`rmssd`)

### rrv

Respiration-rate variability: SD of the per-cycle breath durations (s).

Source: [`respiration_metrics.py`](respiration_metrics.py) (`rrv`)

### rsa

Respiratory sinus arrhythmia: mean over valid breath cycles (Grossman 1990 peak-to-valley, ms).

Call chain: `rsa` -> `_rsa_metric`

Algorithm: [`respiration_metrics.py`](respiration_metrics.py) (`_rsa_metric`)

### rsa0

RSA with every invalid breath (negative or undetectable) counted as zero over the total breath count; reduces over-estimation bias (VU-DAMS RSA0, ms).

Call chain: `rsa0` -> `_rsa_metric`

Algorithm: [`respiration_metrics.py`](respiration_metrics.py) (`_rsa_metric`)

### sbp_sd

Beat-to-beat systolic BP variability: SD of the per-beat SBP (mmHg).

Call chain: `sbp_sd` -> `_bp_std` -> `bp_beat_parameters`

Algorithm: [`bp_metrics.py`](bp_metrics.py) (`bp_beat_parameters`)

### sd1

Poincaré SD1 (minor axis, ms) = std(dIBI) / sqrt(2).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`sd1`)

### sd2

Poincaré SD2 (major axis, ms) via Brennan's identity: ``SD2² = 2·Var(IBI) − 0.5·Var(dIBI)``.

Source: [`ecg_metrics.py`](ecg_metrics.py) (`sd2`)

### sd_hr

SD of the per-beat instantaneous heart rate (bpm).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`sd_hr`)

### sd_ratio

SD1 / SD2 - short-term vs long-term variability balance.

Source: [`ecg_metrics.py`](ecg_metrics.py) (`sd_ratio`)

### sdnn

Standard deviation of all valid IBIs (ms).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`sdnn`)

### sdsd

Standard deviation of successive differences (ms).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`sdsd`)

### stationarity

Correlation of IBI vs. time - drift indicator.

Source: [`ecg_metrics.py`](ecg_metrics.py) (`stationarity`)

### stationarity_z

Reverse-arrangements stationarity test statistic (Bendat & Piersol).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`stationarity_z`)

### tinn

Triangular Interpolation of the NN histogram (ms): base width of the least-squares triangle fitted to the IBI histogram (Task Force 1996).

Source: [`ecg_metrics.py`](ecg_metrics.py) (`tinn`)

### total_power

Total spectral power: sum of all configured bands except FullRange (mMI² by default).

Call chain: `total_power` -> `_total_power` -> `_band_power`

Algorithm: [`ecg_metrics.py`](ecg_metrics.py) (`_band_power`)

### transfer_band_metrics

Per-band transfer-function scalars (modulus, coherence, phase).

Group metric: emits several data-driven columns.

Call chain: `transfer_band_metrics` -> `compute_transfer`

Algorithm: [`transfer.py`](transfer.py) (`compute_transfer`)

### twave_amplitude

Mean T-wave amplitude per beat (ECG channel), in ECG signal units.

Source: [`ecg_metrics.py`](ecg_metrics.py) (`twave_amplitude`)

<!-- METRIC-REFERENCE:END -->

