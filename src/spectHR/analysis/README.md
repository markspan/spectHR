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
