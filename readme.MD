<p align="center">
  <img src="images/specthr_logo.png" alt="spectHR logo" width="160" />
</p>

<details open>
<summary>⚠️ CAUTION</summary>
This project is a work in progress. Blood pressure analysis is not yet implemented. Breathing signal extraction and visualisation are functional but should be treated as experimental.
</details>

---

<details open>
<summary><a href="#what-is-specthr"><strong>What is spectHR?</strong></a></summary>
</details>

<details>
<summary><a href="#theoretical-background"><strong>Theoretical background</strong></a></summary>

- [Mental effort, not stress](#mental-effort-not-stress)
- [Frequency bands](#frequency-bands)
- [Practical considerations](#practical-considerations)

</details>

<details open>
<summary><a href="#getting-started"><strong>Getting started</strong></a></summary>
</details>

<details>
<summary><a href="#the-interface-at-a-glance"><strong>The interface at a glance</strong></a></summary>

- [Step 1, Check and clean the ECG (Preprocessing tab)](#step-1-check-and-clean-the-ecg-preprocessing-tab)
- [Step 2, Inspect the IBI timeseries (IBI Series tab)](#step-2-inspect-the-ibi-timeseries-ibi-series-tab)
- [Step 3, Define your analysis segments (Epochs tab)](#step-3-define-your-analysis-segments-epochs-tab)
- [Step 4, Explore autonomic dynamics (Poincaré tab)](#step-4-explore-autonomic-dynamics-poincaré-tab)
- [Step 5, Examine frequency-domain HRV (PSD tab)](#step-5-examine-frequency-domain-hrv-psd-tab)
- [Step 6, Track band power over time (Profiles tab)](#step-6-track-band-power-over-time-profiles-tab)
- [Step 7, Export your results (Parameters tab)](#step-7-export-your-results-parameters-tab)

</details>

<details open>
<summary><a href="#configuring-the-analysis"><strong>Configuring the analysis</strong></a></summary>
</details>

<details>
<summary><a href="#data-formats"><strong>Data Formats</strong></a></summary>

- [XDF (LabStreamingLayer)](#xdf-labstreaminglayer)
- [Polar .txt](#polar-txt)
- [CARSPAN .evt / .nff](#carspan-evt--nff)

</details>

<details>
<summary><a href="#ibi-classification"><strong>IBI Classification</strong></a></summary>

- [Classification algorithm](#classification-algorithm)
- [Comparison with CARSPAN](#comparison-with-carspan)

</details>

<details open>
<summary><a href="#breathing-signal-extraction"><strong>Breathing Signal Extraction</strong></a></summary>
</details>

<details open>
<summary><a href="#poincaré-metrics"><strong>Poincaré Metrics</strong></a></summary>
</details>

<details>
<summary><a href="#power-spectral-density-method-details"><strong>Power Spectral Density, method details</strong></a></summary>

- [Welch's method](#welchs-method)
- [CARSPAN method](#carspan-method)
- [Spectral profiles](#spectral-profiles)
- [Confidence intervals](#confidence-intervals)
- [Frequency bands](#frequency-bands-1)
- [Units and normalisation](#units-and-normalisation)

</details>

<details>
<summary><a href="#installation"><strong>Installation</strong></a></summary>

- [Windows](#windows)
- [Linux](#linux)
- [macOS](#macos)

</details>

<details open>
<summary><a href="#contributing"><strong>Contributing</strong></a></summary>
</details>

<details open>
<summary><a href="#license"><strong>License</strong></a></summary>
</details>

<details open>
<summary><a href="#references"><strong>References</strong></a></summary>
</details>

---

# spectHR: An Interactive HRV Analysis Tool

## What is spectHR?

![spectHR](images/MainWindow.PNG)

**spectHR** is a free, open-source desktop application for Heart Rate Variability (HRV) analysis. It is built for researchers and students who want to move from a raw electrocardiogram (ECG) to interpretable HRV metrics without writing any code, and without trusting a black box.

Heart rate variability reflects the fluctuations inter-beat intervals (IBI). These fluctuations are regulated by the autonomic nervous system: higher HRV generally indicates flexible, healthy regulation; lower HRV is associated with stress, disease, or fatigue. By analysing the power in different frequency bands of the IBI series, spectHR lets you separate the parasympathetic (HF) and sympathetic/parasympathetic (LF) contributions to heart rate control in each named epoch of your recording.

The key principle behind spectHR is that **you have to check data quality**. Every step that could go wrong, R-peak detection, noisy intervals, epoch boundaries, is shown to you visually and can be corrected before any metrics are computed.

---

## Theoretical background

Generally, heart rate variability (HRV) reflects the continuous interplay between the two branches of the autonomic nervous system (ANS). The **parasympathetic** branch, acting via the vagus nerve, produces rapid beat-to-beat fluctuations, including respiratory sinus arrhythmia (RSA). The **sympathetic** branch exerts slower influences, mainly through vasomotor tone and blood pressure regulation. Because the two branches operate at different speeds, spectral analysis separates their contributions by frequency. ([Mulder, 1989](#ref-mulder1989); [Task Force of the European Society of Cardiology, 1996](#ref-taskforce1996)).

A note on the two-branch picture: both branches can be simultaneously active or withdrawn. HRV does not directly reveal what the sympathetic branch is doing. Broader conclusions about autonomic balance require additional signals such as blood pressure, breathing patterns or pre-ejection period.

### Mental effort, not stress

The CARSPAN tradition, which spectHR inherits, utilizes the constructs *mental effort* and *mental workload* rather than *stress*. Mental effort is defined as the resources invested in response to task demands - a construct that can be experimentally manipulated and whose physiological cost can be measured independently of the subjective experience of strain.

Mulder [(1980)](#ref-mulder1980) showed that task performance suppresses HRV, particularly in the mid-frequency band (~0.10 Hz) that reflects baroreceptor-driven blood pressure oscillations. Mulder [(1989)](#ref-mulder1989) formalised the framework: the suppression reflects invested effort, not task difficulty. A person who disengages from a hard task shows little HRV change; one working hard at an easy task shows a marked decrease ([Mulder, 1992](#ref-mulder1992)). The pattern generalises across driving ([de Waard, 1996](#ref-dewaard1996); [Mulder et al., 2004](#ref-mulder2004)), aviation ([De Rivecourt et al., 2008](#ref-derivecourt2008)), clinical work ([Peabody et al., 2023](#ref-peabody2023)), and driving simulation studies ([Arutyunova et al., 2024](#ref-arutyunova2024)).

HRV does not measure perceived stress. It measures a physiological state: the cost of effort investment that may or may not correspond to what a person calls "feeling stressed." The gap between the two is where individual differences and coping strategies operate. Treating HRV as a direct readout of stress conflates distinct levels of analysis.

### Frequency bands

spectHR computes power in three bands ([Mulder, 1989](#ref-mulder1989); [Mulder, 1988](#ref-mulder1988)), following the CARSPAN convention. Band boundaries are **user-configurable** to accommodate different research traditions.

### Practical considerations

**Recording length.** Frequency resolution is $\Delta f = 1/T$. A 5-minute epoch gives $\Delta f \approx 0.003$ Hz, enough to resolve MF and HF cleanly. Shorter epochs give coarser resolution and wider confidence intervals (visible in spectHR's shaded CI band). Note that this applies to spectral measures only: [Tegegne et al. (2019)](#ref-tegegne2018) showed that a 10-second ECG yields a valid RMSSD estimate in large samples.

**Artefacts are critical.** A single missed or spurious R-peak introduces broadband spectral energy that can swamp the genuine HRV signal ([Mulder, 1988](#ref-mulder1988)). This is why spectHR requires the user to inspect and verify the IBI series before computing any metrics.

**Normalisation.** Absolute spectral power in ms² scales with mean IBI squared, increasing at lower heart rates. The CARSPAN mMI² normalisation corrects for this automatically. For the Welch method the output unit is configurable: the default is **mMI²** (normalised, heart-rate-independent) but can be switched to **ms²** (raw IBI power, not normalised) via the `"units"` key in *Edit Parameters*. Whether to normalise HRV for mean heart rate is genuinely unresolved ([de Geus et al., 2019](#ref-degeus2019)), and no single recommendation fits all research questions.

<details>
The two choices show the same frequencies (the rhythms of heart rate variability), but measured differently.
ms²/Hz is the direct view. You take the sequence of beat-to-beat intervals in milliseconds, and ask how its variance is spread across frequencies. At any given frequency, this value tells you how much millisecond-squared variability sits there, per unit of frequency bandwidth. Integrate the curve over a band (for example HF, 0.15 to 0.40 Hz) and the result is band power in ms². That number is intuitive in absolute terms: an HF power of 1000 ms² means the HF rhythm contributes about √1000 ≈ 32 ms of variation to the IBI signal.
The catch is that ms²/Hz depends strongly on mean heart rate. Someone with a slow resting heart (mean IBI 1200 ms) has more absolute room to fluctuate in milliseconds than someone with a fast heart (mean IBI 600 ms), even when both modulate their heart rate by the same proportion. So comparing absolute ms² between subjects, or between rest and exercise within one subject, is muddied by baseline differences in heart rate.
mMI²/Hz removes that dependence. CARSPAN works from the R-peak event series and divides the spectrum by the squared mean heart rate. What comes out is dimensionless: it no longer asks "how many ms of fluctuation," but "what fraction of the mean does the rhythm modulate?" Because that fraction is small, the result is multiplied by 10⁶ so values land in a readable range. The unit name reflects this scaling: milli-Modulation-Index squared, mMI².
The y-axis of an mMI²/Hz plot is therefore a relative modulation strength per Hz. Integrating over a band gives band power in mMI², with a clean interpretation tied directly to the coefficient of variation of heart rate: a 1% CoV contributes 100 mMI² of total power (since 0.01² × 10⁶ = 100), and a 10% CoV contributes 10 000 mMI². Read backwards, an HF band power of 250 mMI² means the high-frequency rhythm modulates heart rate by roughly √(250 × 10⁻⁶) ≈ 1.6%.
In short: use ms²/Hz when you care about the absolute size of the millisecond fluctuations themselves. Use mMI²/Hz when you want to compare HRV rhythms across people, sessions, or conditions where mean heart rate differs, because it expresses the rhythms as a percentage of the heartbeat being modulated rather than as an absolute amplitude.
</details>

**spectHR operates on IBI time series.** The core analyses - time-domain HRV, spectral band power, Poincaré geometry - require only inter-beat intervals. Simultaneous blood pressure or respiration recordings are not needed. That said, the most reliable conclusions about mental effort come from converging evidence across heart rate, HRV, and when available, blood pressure and baroreflex sensitivity. Stuiver and Mulder [(2014)](#ref-stuiver2014) showed that the full cardiovascular pattern was more diagnostically informative than any single measure in isolation.

---

## Getting started

1. Launch the application. On first run it creates a default workspace pointing to your Documents folder.
2. Open **WorkSpace → Edit Workspace** to point spectHR at the folder where your data files live.
3. Your files appear in the tree on the left. Click one to load it.
4. Work through the tabs from left to right: clean the ECG, define your epochs, then read the results.

---

## The interface at a glance

The window is divided into two areas. On the left is a narrow **file tree** listing all datasets in your configured data folder. On the right is the main **analysis area**, organised into seven tabs:

| Tab | What you do there |
|-----|------------------|
| **Preprocessing** | Verify and correct R-peak detection |
| **IBI Series** | Review the IBI timeseries |
| **Poincaré** | Explore beat-to-beat dynamics visually |
| **Epochs** | Draw and adjust your analysis segments |
| **PSD** | Read the frequency-domain power spectrum per epoch |
| **Profiles** | Track each band's power as it evolves over time within an epoch |
| **Parameters** | See all HRV metrics in a table and export three CSVs (time-domain, PSD, profile summaries) |

---

### Step 1, Check and clean the ECG (Preprocessing tab)

This is the most important step. The quality of every metric downstream depends entirely on whether the R-peaks have been detected correctly.

When you select a file, spectHR loads the ECG, finds R-peaks automatically, and displays everything in the Preprocessing tab. The **main plot** shows the raw ECG signal in red. Every detected R-peak is marked with a vertical coloured line, and the IBI (in milliseconds) is printed as an arrow between consecutive peaks. A **colour code** immediately tells you which beats look suspicious, see [IBI Classification](#ibi-classification) for the full scheme.

If a breathing signal is available from the device's accelerometer, it appears as a **green curve** overlaid on the ECG. Light-blue shading marks inhalation phases. Below the main ECG is a **thumbnail strip** showing the entire recording. The **navigation bar** at the bottom lets you jump to the next or previous abnormal beat, pan, and zoom.

When you spot a problem, use the **mode selector**:
- **Drag**, shift a peak line to its correct position.
- **Add**, click anywhere on the ECG to insert a missing peak.
- **Remove**, click a peak line to delete a spurious detection.

All changes are saved automatically to the cache file when you leave the tab.

<details>
<summary>Tip</summary>

Right-clicking a file gives you **Reload Raw**, **Invert ECG Polarity**, and **Retrigger ECG**.

</details>

---

### Step 2, Inspect the IBI timeseries (IBI Series tab)

Once the peaks look correct, switch to the **IBI Series tab** to see heart rate over time in beats per minute. If a breathing signal is available it is shown as a faint green overlay.

![Heart Rate Series](images/IBIWindow.png)

---

### Step 3, Define your analysis segments (Epochs tab)

HRV metrics are always computed within named segments. The **Epochs tab** shows a Gantt-style chart. If your recording contains marker events, epochs are built automatically. You can also add epochs manually via **Actions → Add Epoch** and trim them by dragging their edges. Any change here immediately updates the Poincaré plot, the PSD plots, and the metrics table.

![Epochs](images/EpochsWindow.png)
---

### Step 4, Explore autonomic dynamics (Poincaré tab)

The **Poincaré tab** shows a scatter plot where each point represents one heartbeat: its IBI on the x-axis and the following IBI on the y-axis. A healthy autonomic system produces a characteristic elliptical cloud elongated along the diagonal. The short axis (SD1) reflects rapid, beat-to-beat variability; the long axis (SD2) reflects slower variability. Each active epoch is drawn in a different colour with its own ellipse overlaid.

![Poincare Plot](images/PoincareWindow.png)

<details>
<summary>A note on SD1 and SD2</summary>

SD1 and SD2 carry no statistical information beyond RMSSD and SDNN respectively. Van Roon et al. (2025) demonstrate this rigorously: SD1 $= \text{RMSSD}/\sqrt{2}$ by definition, and SD2 follows algebraically from SDNN and RMSSD. spectHR reports them because they are widely expected in the literature and because the Poincaré plot is a useful visual summary, but users should not treat SD1 and SD2 as independent metrics alongside RMSSD and SDNN in statistical analyses.

*van Roon, A.M., Span, M.M., Lefrandt, J.D., & Riese, H. (2025). Overview of mathematical relations between Poincaré plot measures and time and frequency domain measures of heart rate variability. Entropy, 27(8), 861.* https://doi.org/10.3390/e27080861

</details>

---

### Step 5, Examine frequency-domain HRV (PSD tab)

![spectHR](images/PSDWindow.PNG)

The **PSD tab** shows one power spectrum per active epoch. Four frequency bands are shaded (usefull defaults in brackets):

- **FullRange (0.02–0.65 Hz)**, the total HRV spectrum.
- **VLF (0.02–0.06 Hz)**, slow regulatory processes.
- **LF (0.07–0.14 Hz)**, baroreflex, mixed sympathetic/parasympathetic.
- **HF (0.15–0.40 Hz)**, respiratory sinus arrhythmia, parasympathetic tone.

Ranges are configurable. The shaded grey band is the **confidence interval**. Three PSD methods are available (`carspan`, `carspan_strict`, `welch`), selected in **WorkSpace → Edit Parameters**. The method takes effect immediately without restarting.

---

### Step 6, Track band power over time (Profiles tab)

![spectHR](images/ProfilesWindow.PNG)

The **Profiles tab** shows how each chosen frequency band's power *changes over the course of each epoch*. Where the PSD tab gives you one spectrum per epoch (collapsing time), the Profiles tab gives you one curve per band per epoch (collapsing frequency *within* the band, but resolving time).

Each subplot is one epoch; each filled, semi-transparent trace is one band. The x-axis is time within the epoch (seconds, with `t = 0` at the epoch's first R-peak); the y-axis is band power in mMI² (or ms², if you switched the Welch units). The y-axis is shared across epoch subplots so band-power magnitudes are directly comparable between epochs. Up / Down arrows zoom the shared axis; Shift+Ctrl+P exports every subplot to the configured output folder.

How the curve is computed: a fixed window of length `window_s` slides along the epoch in steps of `step_s`, and the active PSD method (CARSPAN-strict by default) is recomputed on the R-peaks inside each window. The band-power integration that produces one dot of the trace is the **same `band_powers()` call** used in the PSD tab, just applied per-window; flipping the PSD method in *Edit Parameters* therefore affects the Profiles tab the same way it affects the PSD tab.

Configure it under **WorkSpace → Edit Parameters → Profile Settings**:

| Setting | Default | What it does |
|---|---|---|
| `bands` | `["LF", "HF"]` | Tick-box list of band names to plot. Must match band names defined under PSD Settings; stale names from a band rename are dropped automatically. |
| `window_s` | 30 s | Length of the sliding window, in seconds. CARSPAN manual recommends `window_s ≥ 3 · 1/f_l_min` for reliable estimates of the lowest band (i.e. ≥ 50 s for an LF lower edge of 0.06 Hz). |
| `step_s` | 5 s | Step between successive windows. Must be strictly smaller than `window_s` (otherwise the windows don't overlap). |
| `smooth_for_display` | `false` | Apply the same Pascal 3-point moving-average smoother used by the PSD plot, along each band's time series. **Off by default** to match the Delphi reference (which never smooths the profile time series). |

Each profile dot is plotted at the **centre of the window that produced it**, not at the window's left edge. That matches Delphi's `PlotProfiles` (`T_AnaFunctions.pas:1521`), and the same convention `scipy.signal.spectrogram` uses with `mode='psd'`. So the first dot for a 30 s window lands at `t = 15 s` within the epoch; the apparent "gap" at the left of each plot is the half-window that the first window's centre is offset from `t = 0`.

---

### Step 7, Export your results (Parameters tab)

The **Parameters tab** shows a table with one row per epoch:

- **Time-domain:** count, mean, median, min, max, std, RMSSD, SDNN, SDSD
- **Poincaré:** SD1, SD2, SD2/SD1, ellipse area
- **Frequency-domain:** FullRange, VLF, LF, HF power and LF/HF ratio, in **mMI²** by default; Welch can be switched to **ms²** via *Edit Parameters*

Click **Save** to export. Three CSV files are written to the configured **Output** folder (see [Configuring the analysis](#configuring-the-analysis)). All three are one-row-per-epoch and use `epoch` as the natural join key, so they merge as standard data frames in R, JASP, or SPSS. The two spectral files also carry **raw-array columns** alongside the scalar summaries; those columns hold comma-separated numbers inside a single cell. Each such cell is quoted on write (RFC 4180), so any compliant CSV reader treats it as a single field, and downstream code unpacks the list with one `strsplit` (R) or `split` (Python) call.

| File | Per-row contents |
| --- | --- |
| `{basename}.csv` | The table shown on screen, time-domain + Poincaré + integrated band powers. Scalars only. |
| `{basename}_psd.csv` | Per band: scalar `<band>_power` plus the raw spectrum slice as two equal-length lists, `<band>_freqs` (Hz) and `<band>_psd_raw` (PSD values in mMI²/Hz by default). |
| `{basename}_profiles.csv` | A shared `profile_timestamps` list (epoch-relative window-centre seconds) and, per band: the five summary statistics (`<band>_mean / _std / _min / _max / _t_max`) plus the raw band-power-per-window list `<band>_profile_raw`. |

The bands you see in `_psd.csv` and `_profiles.csv` are exactly the bands defined under *Edit Parameters → PSD Settings → Bands*, in display order. The profile compute reuses the same band definitions as the PSD compute, so the two files describe the same partition of the spectrum.

Conventions inside the raw cells:

- Separator: `,` (comma), the same character the CSV uses between fields. Python's `csv.writer` quotes any field that contains commas, so the file stays a valid RFC 4180 CSV and every standard reader (Python `csv`, pandas `read_csv`, R `read.csv`, JASP, SPSS) parses the list cells as a single field.
- Number format: six significant digits via `g`, so both very small VLF powers (`1.23e-05`) and large peaks (`3.10e+04`) stay readable without overpadding either.
- Missing values: NaN windows / NaN PSD bins become empty positions inside the list (`...,1.23,,4.56,...`). R's `as.numeric(strsplit(cell, ",")[[1]])` and `pandas.to_numeric` both turn those into `NA` / `NaN` of their own accord.
- Lengths: within one row, `<band>_freqs` and `<band>_psd_raw` are equal length (the band slice); `profile_timestamps` and every `<band>_profile_raw` are equal length (`n_windows`).
- `t_max` is the **epoch-relative** time of the band-power peak (seconds from the epoch's first R-peak), so it matches the x-axis of the Profiles plot.

A typical `{basename}_psd.csv` (one row per epoch; truncated cells shown as `…`, the actual cells are wrapped in double quotes so the inner commas are not treated as field delimiters):

```csv
Subject,epoch,method,unit,FullRange_power,FullRange_freqs,FullRange_psd_raw,VLF_power,VLF_freqs,VLF_psd_raw,LF_power,LF_freqs,LF_psd_raw,HF_power,HF_freqs,HF_psd_raw
P01,sitting,carspan_strict,mMI²,1107.57,"0.02,0.03,…,0.49","3.98e4,2.17e4,…,1.53e3",657.29,"0.02,0.03,0.04,0.05,0.06","3.98e4,2.17e4,2.42e4,2.38e4,1.72e4",247.78,"0.07,…,0.14","1.52e4,…,1.76e3",113.75,"0.15,…,0.4","700,…,3.30e3"
```

And a typical `{basename}_profiles.csv` (truncated to LF / HF for readability; VLF and FullRange have the same six columns):

```csv
Subject,epoch,method,unit,window_sec,step_sec,n_windows,profile_timestamps,LF_mean,LF_std,LF_min,LF_max,LF_t_max,LF_profile_raw,HF_mean,HF_std,HF_min,HF_max,HF_t_max,HF_profile_raw
P01,sitting,carspan_strict,mMI²,30.0,5.0,29,"15,20,25,…,155",183.64,151.41,15.83,1158.49,75.0,"52.1,79.4,…,212.6",160.21,89.42,12.10,610.34,80.0,"55.4,110.2,…,380.8"
P01,standing,carspan_strict,mMI²,30.0,5.0,29,"15,20,25,…,155",268.43,554.07,9.27,3975.02,30.0,…,142.18,210.66,4.55,1382.61,55.0,…
```

Per-epoch failures (epoch too short for a profile window, no PSD method set, etc.) are logged and leave that epoch's per-band cells empty, so a single bad epoch never blocks the export of the rest.

#### Reading the exported CSVs into R

A complete walk-through that reproduces the Profile plot in **ggplot2** (with **dplyr** for the list-column unpacking) sits below. Drop it into an R script and adjust the `subject_id` / `output_dir` constants. The same `unpack_listcol` helper works for the `_psd.csv` file, so the snippet at the bottom shows the PSD spectrum equivalent.

```r
# spectHR companion-CSV reader + plotter
# --------------------------------------
# Loads {basename}_profiles.csv (and optionally _psd.csv), turns the
# comma-separated raw-array columns into long-format tibbles, and
# draws a profile plot that resembles spectHR's Profiles tab.

library(readr)     # read_csv
library(dplyr)     # mutate / filter / select / bind_rows
library(tidyr)     # unnest_longer
library(stringr)   # str_split
library(ggplot2)
library(scales)    # comma()

output_dir <- "~/Documents/spectHR/export"     # the workspace OutputDirectory
subject_id <- "P01"                            # {basename} of the recording

profiles_path <- file.path(output_dir, paste0(subject_id, "_profiles.csv"))
psd_path      <- file.path(output_dir, paste0(subject_id, "_psd.csv"))

# ---- helper: unpack one ',-separated list cell into a numeric vector ----
# Empty positions ("...,1.23,,4.56,...") become NA, which matches the
# convention spectHR uses for NaN windows / NaN PSD bins.
parse_listcol <- function(cell) {
  if (is.na(cell) || cell == "") return(numeric(0))
  as.numeric(str_split(cell, ",", simplify = TRUE)[1, ])
}

# ---- read profiles & long-pivot --------------------------------------
profiles_wide <- read_csv(profiles_path, show_col_types = FALSE)

# Bands present in the file = every column suffixed _profile_raw.
band_names <- profiles_wide |>
  names() |>
  (\(n) n[endsWith(n, "_profile_raw")])() |>
  sub("_profile_raw$", "", x = _)

# Stack one (epoch, band, t, power) row per window so ggplot can facet
# and colour by band naturally.
profiles_long <- bind_rows(lapply(band_names, function(band) {
  profiles_wide |>
    rowwise() |>
    mutate(
      time_s = list(parse_listcol(profile_timestamps)),
      power  = list(parse_listcol(.data[[paste0(band, "_profile_raw")]])),
      band   = band,
    ) |>
    ungroup() |>
    select(Subject, epoch, band, unit, time_s, power) |>
    tidyr::unnest_longer(c(time_s, power))
}))

# ---- ggplot: reproduce the Profiles tab ------------------------------
# Same colour palette spectHR uses (workspace bands.<band>.color):
band_colours <- c(
  "FullRange" = "gray40",
  "VLF"       = "blue",
  "LF"        = "darkgreen",
  "HF"        = "red"
)

ggplot(
  profiles_long |> filter(!is.na(power)),
  aes(x = time_s, y = power, colour = band)
) +
  geom_line(linewidth = 0.6, alpha = 0.85) +
  facet_wrap(~ epoch, scales = "free_y", ncol = 2) +
  scale_colour_manual(values = band_colours, drop = FALSE) +
  scale_y_continuous(labels = scales::comma) +
  labs(
    title    = paste(subject_id, "- band-power profiles"),
    subtitle = paste("PSD method:", unique(profiles_wide$method)),
    x        = "Time within epoch (s)",
    y        = paste0("Band power [", unique(profiles_wide$unit), "]"),
    colour   = "Band"
  ) +
  theme_minimal(base_size = 11) +
  theme(
    legend.position = "bottom",
    strip.background = element_rect(fill = "grey95", colour = NA),
    panel.grid.minor = element_blank()
  )

# ---- bonus: same idea for {basename}_psd.csv -------------------------
# Each row carries paired <band>_freqs / <band>_psd_raw cells, so we
# stack them per band and plot one PSD curve per epoch.
psd_wide <- read_csv(psd_path, show_col_types = FALSE)
psd_bands <- psd_wide |>
  names() |>
  (\(n) n[endsWith(n, "_freqs")])() |>
  sub("_freqs$", "", x = _)

psd_long <- bind_rows(lapply(psd_bands, function(band) {
  psd_wide |>
    rowwise() |>
    mutate(
      freq  = list(parse_listcol(.data[[paste0(band, "_freqs")]])),
      power = list(parse_listcol(.data[[paste0(band, "_psd_raw")]])),
      band  = band,
    ) |>
    ungroup() |>
    select(Subject, epoch, band, unit, freq, power) |>
    tidyr::unnest_longer(c(freq, power))
}))

ggplot(psd_long |> filter(!is.na(power)),
       aes(x = freq, y = power, colour = band)) +
  geom_area(aes(fill = band), alpha = 0.30, position = "identity",
            colour = NA) +
  geom_line(linewidth = 0.5) +
  facet_wrap(~ epoch, scales = "free_y", ncol = 2) +
  scale_colour_manual(values = band_colours) +
  scale_fill_manual(values = band_colours) +
  labs(
    x = "Frequency [Hz]",
    y = paste0("PSD [", unique(psd_wide$unit), "/Hz]"),
    colour = "Band", fill = "Band"
  ) +
  theme_minimal(base_size = 11)
```

The pattern is the same for any of the raw-array columns: pull the cell, hand it to `parse_listcol`, and pair it with the matching `_freqs` / `profile_timestamps` column inside a `rowwise()` `mutate`. The `unnest_longer` step then flattens the per-row vectors into a tidy frame that ggplot understands directly.

---

## Configuring the analysis

All parameters are stored in a JSON workspace file, editable through the application menus.

**WorkSpace → Edit Workspace** changes the three folder paths (data, cache, export).

**WorkSpace → Edit Parameters** is a tabbed dialog:

- **General Settings**: *IBI Classification* (window length, threshold multiplier, TL ceiling), *ECG Preprocessing* (high-pass filter), *Respiration Analysis* (per-epoch flag).
- **PSD Settings**: PSD method, band edges and colours, method-specific parameters, CI level (everything under `FrequencyAnalysis` in the workspace JSON).
- **Profile Settings**: which bands to plot in the Profiles tab (`bands` tick-box list), the sliding-window parameters (`window (sec)`, `step (sec)`), and the optional `smooth_for_display` time-axis smoother.

Changes take effect immediately and are saved to disk.

---

## Data Formats

### XDF (LabStreamingLayer)

spectHR reads `.xdf` files from [LabStreamingLayer](https://github.com/sccn/labstreaminglayer), designed for use with the [Polar H10](https://www.polar.com/en/sensors/h10-heart-rate-sensor) via [PolarBLE](https://github.com/markspan/PolarBLE). Streams are identified automatically. Epochs are derived in one of two ways:

- **Explicit markers**: if any marker stream contains labels beginning with `start <label>` / `stop <label>` (or `end <label>`), those are used to build named epochs in the usual way.
- **Keyboard stream fallback**: if no explicit start/stop markers are present but a stream named `Keyboard` exists, spectHR builds consecutive, non-overlapping epochs from every marker that ends with `" pressed"`. Each such marker starts a new epoch named by the key that was pressed (the marker text with `" pressed"` stripped). The epoch ends when the next key is pressed, or at the end of the recording for the final epoch. If the same key is pressed more than once its epochs are numbered (`a #1`, `a #2`, …).

### Polar .txt

The plain-text RR-interval export format from the Polar app. See `ExampleData/`.

### CARSPAN .evt / .nff

CARSPAN event files. If an `.nff` file with the same base name is present, spectHR loads the ECG channel from it. In that case the R-peak timestamps from the `.evt` file are authoritative: the ECG is filtered for display but R-peaks are **not** re-detected from it (the loader sets `rtops_locked` on the resulting `CardioSeries`).

---

## IBI Classification

After R-peak detection, each inter-beat interval is classified before any metrics are computed. The beat colour in the ECG plot reflects its label:

| Label | Meaning | Colour |
|-------|---------|--------|
| N | Normal, within the expected range | Blue |
| S | Short, below the lower threshold | Magenta |
| L | Long, above the upper threshold | Cyan |
| TL | Too Long, exceeds the absolute ceiling; excluded from all metrics | Orange |
| SL | Short followed immediately by Long | Turquoise |
| SNS | Short-Normal-Short triplet | Light sea green |
| T | Degenerate (NaN or zero duration); excluded from all metrics | – |

---

<details>
<summary>Classification algorithm</summary>

### Classification algorithm

Let $\text{IBI}_i$ denote the $i$-th inter-beat interval and let $\bar{\text{IBI}}$ and $\sigma$ denote the **local** mean and standard deviation over a centred rolling window of $W$ beats. Classification proceeds as follows:

| Condition | Label |
|-----------|-------|
| $`\text{IBI}_i > T_{\max}`$ | **TL** *(excluded from all statistics)* |
| $`\text{IBI}_i \leq 0`$ or NaN | **T** *(excluded from all statistics)* |
| $`\text{IBI}_i > \bar{\text{IBI}} + N \cdot \sigma`$ | **L** |
| $`\text{IBI}_i < \bar{\text{IBI}} - N \cdot \sigma`$ | **S** |
| beat $`i`$ is S and beat $`i+1`$ is L | **SL** |
| beat $`i`$ is S, beat $`i+1`$ is N, beat $`i+2`$ is S | **SNS** |
| otherwise | **N** |

**Default parameters** (all configurable in *Edit Parameters*):

| Parameter | Default | JSON key |
|-----------|---------|----------|
| Window length $`W`$ | 51 beats | `window_length` |
| Threshold $`N`$ | 4.0 std | `n_std` |
| TL ceiling $`T_{\max}`$ | 2.0 s | `max_ibi_sec` |

---
<details>

### Comparison with CARSPAN

Users familiar with CARSPAN will notice several differences in the classification approach. Each is a deliberate design choice.

#### 1. Refractory period, implemented at detection, not classification

CARSPAN enforces a hardware refractory period $T_\text{refr} = 300~\text{ms}$ at the classification stage, rejecting any detected interval shorter than this. spectHR implements the equivalent constraint earlier in the pipeline as the `min_peak_distance_ms` parameter passed to `scipy.signal.find_peaks`. Any two candidate peaks closer than 300 ms simply cannot both be detected. This approach prevents the false detection from entering the data in the first place. The effect on the classified IBI series is identical.

#### 2. Window type, centred rather than causal

CARSPAN computes its running statistics over a **causal** (backward-looking) window of $T_w = 60~\text{s}$. spectHR uses a **centred** window of $W$ beats, incorporating beats both before and after the current interval. A centred window produces more stable thresholds at condition boundaries, precisely where accurate classification is most important in psychophysiological research. A causal window adapts its threshold only *after* a heart rate change has occurred, which can flag the first beats of a new condition incorrectly.

#### 3. Window unit, beats rather than seconds

CARSPAN's window is defined in seconds; spectHR's in beats. For a resting heart rate of ~70 bpm, 51 beats ≈ 44 seconds, close to CARSPAN's default of 60 seconds. A beat-based window always contains the same number of statistical observations regardless of heart rate.

#### 4. Successive difference criterion, not implemented

CARSPAN also flags a beat if the *difference* between consecutive intervals ($`\text{IBI}_i - \text{IBI}_{i-1}`$) exceeds $`N_\text{SuD}`$ standard deviations of the successive difference series. spectHR does not implement this. The SL and SNS sequence labels already capture the most physiologically relevant abrupt patterns. Adding a separate threshold would introduce a second set of parameters that could conflict with the sequence labels in ambiguous cases.

#### 5. Min/Max SD clipping, not implemented

CARSPAN clips the standard deviation used for thresholding to a minimum of 5 % and a maximum of 15 % of the local mean IBI. spectHR relies instead on the user's choice of `n_std` and `max_ibi_sec`. The absolute ceiling guards the upper extreme; the 300 ms minimum peak distance guards the lower extreme.

#### 6. Automatic interpolation, not implemented

CARSPAN automatically corrects detected artefacts by linear interpolation, inserting estimated beats and adding normally-distributed noise to prevent variance reduction. spectHR does not perform automatic correction. Every flagged beat is shown in the Preprocessing tab and can be corrected manually. Intervals left uncorrected and labelled TL or T are excluded from all metric calculations. This reflects spectHR's core principle: **you**, not the algorithm, decide what to do with each artefact.

</details>
</details>

---

## Breathing Signal Extraction

When a Polar H10 accelerometer stream is present, spectHR derives a respiration surrogate from the 3-axis chest-belt movement data by removing the gravity component, bandpassing to 0.10–0.70 Hz, and applying PCA to extract the dominant axis of motion as a single 1-D signal. The result is z-score normalised and overlaid in green on the ECG and heart rate plots. Inhalation phases are shaded in light blue.

---

## Poincaré Metrics

**SD1**, beat-to-beat variability, equal to $\text{RMSSD}/\sqrt{2}$:

$$\text{SD1} = \sqrt{\tfrac{1}{2} \cdot \mathrm{Var}(\text{IBI}_{i+1} - \text{IBI}_i)}$$

**SD2**, longer-term variability, algebraically related to SDNN and RMSSD:

$$\text{SD2} = \sqrt{2 \cdot \mathrm{Var}(\text{IBI}_i) - \tfrac{1}{2} \mathrm{Var}(\text{IBI}_{i+1} - \text{IBI}_i)}$$

**SD1/SD2**, autonomic balance index.

**Ellipse area** $= \pi \cdot \text{SD1} \cdot \text{SD2}$, total HRV.

**Important:** SD1 and SD2 are fully determined by RMSSD and SDNN and therefore carry no additional statistical information ([van Roon et al., 2025](#ref-vanroon2025)). Including all four in a statistical model introduces redundancy.

---

## Power Spectral Density, method details

### Welch's method

The IBI series (in ms) is resampled onto a uniform time grid with cubic interpolation, divided into overlapping segments, windowed, Fourier-transformed, and averaged. Averaging across segments reduces variance at the cost of frequency resolution. Default output: **mMI²/Hz**; configurable to **ms²/Hz** via the `"units"` workspace key.

<details>
<summary>Welch, algorithm detail</summary>

### Welch, algorithm detail

Let $`x(t)`$ denote the IBI series (in ms), resampled at $`f_s`$ Hz. `scipy.signal.welch` is invoked with `scaling='density'` and returns a one-sided PSD in ms²/Hz.

Band power $B$ in $`[f_l, f_h]`$ is obtained by trapezoidal integration with endpoint interpolation:

$$B = \int_{f_l}^{f_h} \hat{S}(f) df \approx \sum_k \hat{S}(f_k) \Delta f$$

Because consecutive segments overlap, they are not statistically independent. The effective degrees of freedom are reduced accordingly (Percival & Walden, 1993):

$$\nu = \frac{2K}{1 + 2\!\left(1 - \tfrac{1}{K}\right)\rho^2}$$

$$CI(f) = \left[ \frac{\nu \cdot \hat{S}(f)}{\chi^2_{\nu, 1-\alpha/2}}, \quad \frac{\nu \cdot \hat{S}(f)}{\chi^2_{\nu, \alpha/2}} \right]$$

where:
- $K$: number of segments
- $\rho$: normalised window autocorrelation at lag equal to the segment step, computed numerically from the actual window samples: $\rho = \sum_n w[n]\, w[n + \text{step}] \;/\; \sum_n w[n]^2$
- $\chi^2_{\nu, p}$: chi-square quantile at probability $p$ with $\nu$ degrees of freedom
- $\alpha$: significance level (e.g. 0.05 for a 95% CI)

For non-overlapping segments $\rho = 0$ and $\nu = 2K$. For a Hann window at 50 % overlap $\rho \approx 1/6$, giving $\nu \approx 1.89\,K$, close to the value for fully independent segments.

**Default parameters** (configurable in *Edit Parameters*):

| Parameter | Default | JSON key |
|-----------|---------|----------|
| Resampling frequency | 4 Hz | `fs` |
| Segment length | 256 samples | `nperseg` |
| Overlap | 128 samples | `noverlap` |
| FFT length | 1024 | `nfft` |
| Window | Hann | `window` |
| Output units | mMI² | `units` |

**Note on resampling.** A 4 Hz resampling rate gives a frequency resolution of $f_s / \text{nperseg} = 4/256 = 0.0156~\text{Hz}$, which is adequate for the standard HRV bands. For short epochs where the available IBI samples are fewer than `nperseg`, the segment length is reduced to the available count and the overlap is halved automatically.

</details>

---

### CARSPAN method

CARSPAN takes a different approach. Instead of resampling the IBI series onto a uniform time grid, it operates directly on the R-peak times and computes the Fourier transform of those events. That is the algorithm Mulder [(1988)](#ref-mulder1988) developed for the original CARSPAN software. No resampling, no interpolation in time. The spectrum is computed on a native frequency grid $f_k = k/T$ (resolution $\Delta f = 1/T$), bin-averaged onto a fixed display grid for plotting, and band power is computed by direct summation following the manual's formula 3.28. Output units: **mMI²**.

spectHR has **one CARSPAN compute function** (`compute_carspan_psd`) with **two presets** of its `CarspanOptions` dataclass, exposed in the workspace as `method: "carspan"` (configurable) and `method: "carspan_strict"` (manual-faithful):

- **`carspan_strict`** is the preset bundle returned by `carspan_strict_options()`. Locks every knob the CARSPAN manual leaves implicit, including `signal: "ibi_amplitude"` which switches the DFT to the IBI-amplitude formula of manual Eq. 3.21 (Pascal `SOC` branch `IsRPDataCol=False`). Reproduces the manual's epoch #2 reference (`example1.EVT`, p. 121) within ~2 % on every band. Use this when you want to compare against published CARSPAN values.
- **`carspan`** is the configurable variant. By default it's the unit-impulse SOC of Eq. 3.19 (Pascal `IsRPDataCol=True`), with the window, amplitude correction, reference-grid DC subtraction, and skip-first-event all exposed as separate workspace fields. Use this when you want to explore the effect of any of those knobs.

Because both come from the same function, *every* setting `carspan_strict` uses is reachable from the configurable side too. The strict preset is exactly:

| `CarspanOptions` field | Strict value | Notes |
|---|---|---|
| `signal` | `"ibi_amplitude"` | flips the DFT from Eq. 3.19 → Eq. 3.21 |
| `taper` | `"carspan_index"` | Pascal's index taper (sample 0 has a small non-zero weight; scipy's tukey zeros it) |
| `alpha_taper` | `0.10` | 5 % cosine bell per side (Pascal `TaperPercent := 5`) |
| `freq_resolution` | `0.01` | display grid spacing (Pascal `NewRes`) |
| `amplitude_correction` | `false` | use the manual's flat `2/T` (no `N/S₂` variance-correction); *ignored on the `ibi_amplitude` branch* |
| `skip_first_event` | `true` | Pascal SOC loops over IBI indices `0..N_IBI-1`; *ignored on the `ibi_amplitude` branch* |
| `dc_removal` | `true` | reference-grid DC subtraction; *ignored on the `ibi_amplitude` branch* (mean subtraction handles DC) |
| `dc_grid` | `"carspan_strict"` | asymmetric reference grid; *ignored on the `ibi_amplitude` branch* |
| `smooth_for_display`, `f_max`, `plot_units` | caller's choice | not locked by the preset; defaults are `true`, `0.5`, `"mMI²/Hz"` |

The four "*ignored on the `ibi_amplitude` branch*" rows are kept on the preset only so a curious caller flipping `signal` back to `"events"` gets the Pascal-faithful unit-impulse SOC settings for comparison. In practice on the strict path only the top three rows do any work.

One last knob lives outside `CarspanOptions`: **`PsdMethod.mean_convention`**. `psd_method_from_workspace` sets it to `"arithmetic"` for `method: "carspan_strict"` (= harmonic mean of IBI, what Pascal's `SOC` uses) and to `"harmonic"` for `method: "carspan"` (= `T/N`, what the manual writes). That's the one setting you cannot reach from the workspace `carspan` section alone. To get full strict equivalence with `method: "carspan"` you'd have to construct a `PsdMethod` with `mean_convention="arithmetic"` from Python, or just use `method: "carspan_strict"`.

<details>
<summary>CARSPAN, algorithm detail</summary>

### CARSPAN, algorithm detail

#### Two views of the same signal

Mulder's manual gives two algebraically equivalent ways to write the CARSPAN spectrum, depending on what you treat as the "data" entering the DFT.

**Unit-impulse view (Eq. 3.19; used by `carspan`).** Following Rompelman (1975) and Mulder [(1988)](#ref-mulder1988), the heartbeat is modelled as a sequence of unit impulses at the R-peak times $t_i$:

$$x(t) = \sum_{i=1}^{N} \delta(t - t_i)$$

This is the *Integral Pulse Frequency Modulation* (IPFM) representation. Treating the signal outside the analysis window $[0, T]$ as a periodic continuation, the PSD at discrete frequencies $f_k = k/T$ is:

$$S_{xx}(f_k) = \frac{2}{T}\left|\sum_{i=1}^{N} w_i\, e^{-2\pi j f_k t_i}\right|^2$$

The $w_i$ are tapering-window weights. The output is in events²/Hz; conversion to mMI²/Hz is done by the mixin layer.

**IBI-amplitude view (Eq. 3.21; used by `carspan_strict`).** The same recording, expressed as a sum over IBI amplitudes weighted by their local interval $t_i$:

$$\tilde S_{xx}(f_k) = \frac{2}{T}\left|\sum_{i=1}^{N} t_i\, x_i\, e^{-2\pi j f_k T_i}\right|^2$$

where $x_i$ is the arithmetic-mean-subtracted IBI in ms, $t_i$ the local IBI duration in seconds, and $T_i = \sum_{j \le i} t_j$ the cumulative time of the $i$-th beat. The output is in ms²/Hz directly (variance per Hz), and the mixin layer normalises to mMI²/Hz by multiplying by $10^6 / \overline{\text{IBI}}_\text{ms}^2$, the milli-squared form of manual Eq. 3.20.

The two views describe the *same physical signal* and would integrate to the same total energy under continuous-signal idealisations. In the discrete sampled implementation they produce different magnitudes (per-bin scaling differs by ~ $\overline{\text{IBI}}^2$ ). The strict path is the one whose discrete output matches the manual's tabulated reference values.

**Which one matches the manual?** The strict path: verified against epoch #2 of `example1.EVT` (CARSPAN manual p. 121) to within ~2 % on every band, ~0.03 % on LF.

Internally, both variants run through the same `compute_carspan_psd` function in `CarspanPSD.py`; the `signal` field of `CarspanOptions` (`"events"` vs `"ibi_amplitude"`) selects the algorithm. The `carspan_strict_options()` helper builds the preset that locks in the manual-faithful choices for the IBI-amplitude path.

#### Differences between the two paths

| Behaviour | `carspan_strict` (Eq. 3.21) | `carspan` (Eq. 3.19, configurable) |
|---|---|---|
| `signal` field of `CarspanOptions` | `"ibi_amplitude"` | `"events"` (default) |
| What the DFT sees | IBI amplitude $(x_i - \bar x) \cdot t_i$ per beat | unit impulses, windowed |
| DC removal | mean-subtraction of the IBI amplitudes (built-in) | optional reference-grid subtraction (`dc_removal: true`) |
| Window function (default) | Pascal's index taper, `TaperPercent=5` (set by `carspan_strict_options()`) | any `scipy.signal.get_window` name (default `10% cosine bell` → Tukey α = 0.20) |
| Amplitude pre-factor | $2/T$ (fixed by Eq. 3.21) | $2N / (T \cdot S_2)$ by default (variance-correct); $2/T$ when `amplitude_correction: false` |
| First event | included (all $N$ IBIs participate; `skip_first_event` ignored on this branch) | included by default; `skip_first_event: true` drops the first R-peak |
| Native grid | $f_k = k/T$ for $k = 1..\lfloor f_\text{max}\,T\rfloor$ | same |
| Display resample | Pascal's `Resample_R` (fractional-coverage weighted mean) | same |
| 3-MA display smoothing | on by default (`smooth_for_display: true`) | on by default |
| mMI² mean convention | arithmetic mean of rate (= harmonic mean of IBI) | harmonic mean of rate (= $T/N$) |
| Workspace key | `method: "carspan_strict"` | `method: "carspan"` |

Two practical consequences:

1. To compare against CARSPAN's manual or any published `(IBI)`-prefixed CARSPAN output, use `carspan_strict`. To explore *what would happen if I had used a different window, or no DC subtraction, or amplitude correction*, use `carspan`.
2. `dc_removal`, `dc_grid`, `amplitude_correction`, and `skip_first_event` are **only meaningful when `signal == "events"`**. With `signal == "ibi_amplitude"` the compute layer ignores them: the manual's Eq. 3.21 fixes the amplitude at $2/T$, mean subtraction does the DC removal at the signal level, and all $N$ IBIs participate.

#### How do I make `carspan` perform like `carspan_strict`?

`carspan_strict` is, by design, the same code as `carspan` with the `carspan_strict_options()` preset applied. If you want to keep `method: "carspan"` in your workspace but flip the algorithm under the hood, **two settings in the Edit Parameters dialog do the job**:

| Setting | From-strict-equivalent value |
|---|---|
| `FrequencyAnalysis.carspan.signal` | **`ibi_amplitude`** |
| `FrequencyAnalysis.carspan.window` | **`5% cosine bell`** |

Or as JSON:

```json
"FrequencyAnalysis": {
  "method": "carspan",
  "carspan": {
    "signal": "ibi_amplitude",
    "window": "5% cosine bell",
    "freq_resolution": 0.01,
    "smooth_for_display": true,
    "plot_units": "mMI²/Hz",
    "dc_removal": false
  }
}
```

Two things to know:

1. **`signal: "ibi_amplitude"`** is the switch that selects the manual-faithful algorithm (manual Eq. 3.21, Pascal `SOC` branch `IsRPDataCol=False`). On this branch the other strict-bundle fields (`amplitude_correction`, `skip_first_event`, `dc_removal`, `dc_grid`) are **ignored** by the compute layer (the manual fixes their values), so they don't need to appear in the Edit Parameters dialog.
2. **`window: "5% cosine bell"`** matches Pascal's `TaperPercent := 5` (5 % cosine taper per side). The default of `"10% cosine bell"` is 10 % per side, which leaves ~3–5 % more energy on the table and is the single largest source of disagreement with strict if you only flip `signal`.

Verified on epoch #2 of `example1.EVT`: setting `signal: "ibi_amplitude"` + `window: "5% cosine bell"` on the configurable `carspan` path reproduces `carspan_strict` to within ~1 % on every band (and the CARSPAN manual reference to within ~1 %, actually closer than strict on some bands because the residuals from the two sub-percent effects partially cancel).

Two small residuals remain between `carspan + signal=ibi_amplitude` and pure `carspan_strict`:

* **Window taper variant.** With `window: "5% cosine bell"` the configurable path uses scipy's Tukey window, which zeros the first/last sample exactly; Pascal's index taper gives them a small non-zero weight. The strict preset (`carspan_strict_options()`) hard-codes `taper: "carspan_index"` to get the Pascal-faithful version. Difference: ≪ 1 % on band power. Not exposed in the Edit Parameters dialog because it would be a new "carspan_index" choice for the window dropdown that most users wouldn't recognise; if you need it, set it via the Python API.
* **Mean convention.** `psd_method_from_workspace` sets `mean_convention = "arithmetic"` (arithmetic mean of per-beat rate = harmonic mean of IBI) only when `method == "carspan_strict"`. With `method: "carspan"` you get the manual's `T/N` (harmonic mean of rate). For typical 5–8 % RR variability that's a ~0.3–0.8 % difference in the resulting mMI² values. Not exposed in the Edit Parameters dialog for the same reason. If you need full bit-equivalence to strict, just use `method: "carspan_strict"`.

The same answer in summary form:

| Goal | What to set in Edit Parameters |
|---|---|
| Match the manual exactly | `method: "carspan_strict"` (the dropdown choice does it all) |
| Use `method: "carspan"` but get strict-style numbers (within ~1 %) | `method: "carspan"`, `carspan.signal: "ibi_amplitude"`, `carspan.window: "5% cosine bell"` |
| Configurable unit-impulse SOC (default) | `method: "carspan"`, `carspan.signal: "events"` |

<details>
<summary>Note for developers using the Python API directly</summary>

Both variants go through the same `compute_carspan_psd` function. The `signal` field of `CarspanOptions` picks the algorithm:

```python
from spectHR.Tools.PSD.CarspanPSD import (
    CarspanOptions, compute_carspan_psd, carspan_strict_options,
)

# Manual-faithful (IBI-amplitude DFT, Eq. 3.21):
result = compute_carspan_psd(
    rpeak_times,
    options=carspan_strict_options(smooth_for_display=True, f_max=0.5),
)
# result.power is in ms²/Hz on the 0.01 Hz display grid; the mixin
# layer applies the × 10⁶ / mean² conversion for mMI²/Hz.

# Configurable unit-impulse SOC (Eq. 3.19):
result = compute_carspan_psd(
    rpeak_times,
    options=CarspanOptions(
        signal="events",                # default
        taper="carspan_index",
        alpha_taper=0.10,
        amplitude_correction=False,
        skip_first_event=True,
        dc_removal=True,
        dc_grid="carspan_strict",
    ),
)
```

The convenience function `compute_carspan_psd_strict(...)` is a thin wrapper around the first form above (with a rename of the result's `method` field from `"carspan"` to `"carspan_strict"` so downstream code can tell the two apart). `carspan_strict_options()` is the single place that locks in the manual's choices for the IBI-amplitude path (5 % index taper, etc.); if you want a Pascal-faithful preset with one knob flipped (e.g. no 3-MA smoothing), call `replace(carspan_strict_options(), smooth_for_display=False)`.

The mixin's `PsdMethod.mean_convention` is `"arithmetic"` for `carspan_strict` and `"harmonic"` everywhere else, picked automatically by `psd_method_from_workspace` based on the algorithm name. Library callers can override it by constructing a `PsdMethod` themselves and setting `series.psd_method = …`.

</details>

#### Reference-grid DC removal (configurable mode only)

The Pascal `SOC` branch for unit impulses (`IsRPDataCol=True`) does one extra trick the manual doesn't flag: before squaring, it subtracts the DFT of a perfectly periodic impulse train at the mean rate. At $f = 0$ both DFTs equal 1, so their difference is exactly zero and DC is removed. Beyond DC, the subtraction also cancels the spectral leakage that a mean-rate impulse train would otherwise contribute to the VLF region. For an approximately regular rhythm the correction is small at LF and HF but dominant at VLF.

In spectHR this is `FrequencyAnalysis.carspan.dc_removal` (also editable in *Edit Parameters*), only applicable to the configurable `carspan` variant. It defaults to `false` to preserve historical behaviour; turn it on when you need the VLF cleanup while retaining a custom window or the variance-correct amplitude. The IBI-amplitude `carspan_strict` path does **not** use this mechanism; its mean-subtraction step does the DC removal at the signal level (manual Eq. 3.21).

#### Native frequency grid

The grid runs from $f_1 = 1/T$ to $f_{k_\text{max}} = \lceil f_\text{max} \cdot T \rceil / T$, with spacing $\Delta f = 1/T$. The DC bin ($k = 0$) is excluded; it carries no HRV information.

#### Display grid and smoothing

The compute layer always returns the **un-smoothed** resampled spectrum (Pascal's `PDSin_BCK`); the 3-point moving-average smoother lives in the plot widget (`spectUI.PSDPlotWidget._fetch`), applied only when the active CARSPAN method has `smooth_for_display = True`. This split lets the *same* `series.psd()` call drive both the on-screen curve and the band-power integration, without `smooth=True/False` bookkeeping at the compute level.

**Compute layer (`series.psd()`, `compute_carspan_psd`).** Native spectrum → bin-averaged onto the `freq_resolution` display grid (Pascal's `Resample`, default 0.01 Hz). That's it: no MA. This mirrors Pascal's `PDSin_BCK`, the array the manual reads when computing band powers (§3.2):

> *"No smoothing of the spectra is carried out on the spectra before computing the spectral band values"*

**Plot widget (`PSDPlotWidget._fetch`).** Pulls the un-smoothed spectrum from `series.psd()`, then applies a 3-point moving average to `power`, `ci_lower`, and `ci_upper` when the active CARSPAN method requests it. From the manual (§3.3):

> *"a moving average window over three frequency points (0.03 Hz bandwidth) is applied before plotting the spectral functions"*

The MA kernel is mean-preserving (each output bin is the arithmetic mean of three neighbours), so the area under the curve is unchanged; the smoothing only affects visual peak height. Welch and Lomb-Scargle results are never smoothed by the plot widget; the `smooth_for_display` knob lives on `CarspanOptions` and the plot widget consults it only for CARSPAN methods.

**Integration path (`band_power`, `band_powers`).** Runs on the *same* un-smoothed spectrum that `psd()` returns. No second back-end call, no smoothing toggle to remember.

#### Band power (formula 3.28)

Band power in $[f_l, f_h]$ is computed by rectangular summation on the resampled, unsmoothed display-grid spectrum:

$$B(f_l, f_h) = \sum_{f_k = f_l}^{f_h} S_{xx}(f_k)\, \Delta f_\text{disp}$$

where $\Delta f_\text{disp}$ is the workspace `freq_resolution` setting (default 0.01 Hz).

The manual writes this on the native grid (Δf = 1/T); spectHR uses the resampled grid because that is what the reference CARSPAN implementation integrates. The two values agree to within edge-bin rounding, since the resample step is energy-conservative.

Welch band power uses trapezoidal integration; only the CARSPAN back-end uses this rectangular summation.

**Practical consequences.** Toggling `smooth_for_display` does not affect band power; integration runs on a separately computed unsmoothed copy. Changing `freq_resolution` *does* shift Δf_disp and the bin boundaries, so it has a small effect on band power: energy is preserved overall, but edge-bin rounding shifts slightly. For typical band definitions the difference remains below 1 %. To reproduce CARSPAN's reported values exactly, leave `freq_resolution` at `0.01`.

#### Normalisation to mMI² (formulae 3.20 and 3.29)

To make spectra independent of mean heart rate, both CARSPAN variants are reported in **milli-Modulation-Index squared** (mMI²/Hz for the spectrum, mMI² for band power), but the conversion from each variant's native unit is different.

**Strict (IBI-amplitude DFT, Eq. 3.21).** The raw spectrum is already in ms²/Hz (variance of the IBI per Hz). Eq. 3.20 normalises by $\bar x^2$ and the milli² convention adds a factor of $10^6$, giving:

$$B'(f_l, f_h) = \frac{10^6}{\overline{\text{IBI}}_\text{ms}^2}\, B(f_l, f_h) \quad [\text{mMI}^2]$$

The mean IBI here is the **harmonic mean** of IBI (= arithmetic mean of the per-beat instantaneous rate); that's what Pascal's `SOC` uses inside `IsRPDataCol=False`. It differs from $T/N$ by ~0.3–0.8 % at typical resting HRV.

**Configurable (unit-impulse SOC, Eq. 3.19).** The raw spectrum is in events²/Hz. Eq. 3.20 divides by the squared mean rate $\bar x = 1/\overline{\text{IBI}}_\text{sec}$ to get a dimensionless modulation index, which the implementation re-expresses as a multiply-by-$\overline{\text{IBI}}_\text{ms}^2$ on the events²/Hz spectrum (legacy mapping kept for back-compat):

$$B'(f_l, f_h) = \overline{\text{IBI}}_\text{ms}^2 \cdot B(f_l, f_h) \quad [\text{mMI}^2]$$

Here the mean IBI is the manual's $T/N$ (harmonic mean of rate), not the arithmetic-mean-of-rate flavour. Reason: the configurable path predates the careful Pascal audit and is kept for back-compat; if you need the manual-faithful answer, use `carspan_strict`.

In both cases the factor $10^6$ (explicit above for strict, implicit in the events²/Hz scaling for configurable) is the "milli" prefix squared: it puts typical resting mMI² values into the ~10–10 000 range rather than the ~10⁻⁵–10⁻² range that raw MI² would give. A consequence is that mMI² band powers are largely independent of mean heart rate, allowing direct comparison across subjects with different resting heart rates.

**Bottom line.** The two CARSPAN paths share the same band-power *idea* (variance of IBI in a frequency band, normalised by mean), but get there by different routes and with slightly different mean conventions. For numerical agreement with the CARSPAN manual or any `(IBI)`-prefixed CARSPAN output, use `carspan_strict`. The `PsdMethod.mean_convention` field (`"arithmetic"` vs `"harmonic"`) selects between the two; `psd_method_from_workspace` picks the right one automatically based on the algorithm name.

**Default parameters** (configurable in *Edit Parameters*):

| Parameter | Default | JSON key | Effect |
|-----------|---------|----------|--------|
| Display grid resolution | 0.01 Hz | `freq_resolution` | Smoothness of displayed curve; does not affect band power |
| Tapering window | `10% cosine bell` | `window` | Any `scipy.signal.get_window` name, or `"X% cosine bell"` → Tukey α = X/50 |
| 3-point display smoothing | `true` | `smooth_for_display` | Matches CARSPAN plot convention |
| Regular-grid DC removal (configurable mode) | `false` | `dc_removal` | Subtract the DFT of a mean-rate impulse train before squaring; cleans up VLF. Strict mode applies this unconditionally. |

</details>

---

### Spectral profiles

A **profile** is the time-resolved evolution of band power *within* one epoch (CARSPAN manual §3.3.5, Eq. 3.34 / 3.35). The PSD tab collapses time and gives you one spectrum per epoch; the Profiles tab does the opposite: collapses frequency *inside* each band and gives you one curve per band per epoch, drawn against time.

#### Algorithm

For each epoch view, the same compute that powers `series.psd()` runs inside a sliding window:

1. Number of windows: $N = \lfloor (T - W) / S \rfloor + 1$, with epoch duration $T$, window length $W$, and step size $S$. Matches the Delphi `GetNrOfProfiles` exactly (`T_AnaFunctions.pas:1164`).
2. For window $i = 0, 1, \dots, N-1$:
   - Window span: $[t_0 + i S,\ t_0 + i S + W]$ where $t_0$ is the epoch's first R-peak.
   - Take the sub-view of R-peaks in that span.
   - Call `band_powers(psd_method=method)` on the sub-view, yielding one band-power value per configured band.
3. The result is an `(n_bands × N)` matrix plus a 1-D timestamps array of window centres.

Because step 2 dispatches through the same `band_powers()` call the PSD tab uses, the profile inherits the active PSD method automatically: switching between Welch, Lomb-Scargle, CARSPAN or CARSPAN-strict in PSD Settings changes the profile too without any additional configuration.

#### Window-centre time convention

Each profile dot is plotted at the **centre** of the window that produced it, $t = i S + W/2$ from the epoch start. The reference Delphi implementation does the same (`T_AnaFunctions.pas:1521`, `index*StepSize + RPDataCol[0] + WindowLength/2`). Plotting at the window centre is the standard signal-processing convention for sliding-window estimates: it's where a piecewise constant approximation of the underlying time-varying band power would put the midpoint of each step.

A consequence is that the first dot is offset by $W/2$ from the epoch's left edge, not by 0; the data from $t \in [0, W/2]$ has been used (it's part of the first window) but its band-power estimate is attributed to the centre of that window, not its left edge.

#### Algorithm-agnostic dispatch

Worth flagging: in the reference Delphi implementation, profiles are only available for the CARSPAN SOC path. In spectHR the per-window compute goes through `view.band_powers(...)` which works equally for Welch and Lomb-Scargle, so the Profiles tab works with whichever PSD method PSD Settings has selected. This is a spectHR addition.

---

### Confidence intervals

CARSPAN itself does not report confidence intervals; this is a spectHR addition. The CI reflects the variability of the spectral estimate that would be expected if the measurement were repeated under identical conditions. Both methods use a chi-square CI of the form:

$$\frac{\nu \cdot \hat{S}(f)}{\chi^2_{1-\alpha/2, \nu}} \leq S(f) \leq \frac{\nu \cdot \hat{S}(f)}{\chi^2_{\alpha/2, \nu}}$$

The methods differ in how the degrees of freedom $\nu$ are determined.

---

### Frequency bands

All methods share the same configurable band definitions:

| Band | Default range | Reflects |
|------|--------------|---------| 
| FullRange | 0.02–0.50 Hz | Total spectral power across the HRV range |
| VLF | 0.02–0.06 Hz | Slow regulatory processes; requires long recordings |
| LF | 0.07–0.14 Hz | Baroreceptor reflex, mixed sympathetic/parasympathetic |
| HF | 0.15–0.40 Hz | Respiratory sinus arrhythmia, parasympathetic tone |

Band edges are configurable in *Edit Parameters*. If your participants breathe slowly, you may need to extend the HF band to lower frequencies.

---

### Units and normalisation

| Method | PSD unit (default) | Band power unit (default) | Configurable? | Normalised by mean HR? |
|--------|-------------------|--------------------------|---------------|----------------------|
| Welch | mMI²/Hz | mMI² | Yes (`units`: `"mMI²"` or `"ms²"`) | Yes (default) |
| CARSPAN | mMI²/Hz | mMI² | No | Yes, $`\times \bar{\text{IBI}}_\text{sec}^{-2} \times 10^{-6}`$ |

Both methods output mMI² by default, which is dimensionless and largely heart-rate independent, enabling valid comparisons across groups or conditions that differ in resting heart rate. Output of the Welch method can be switched to raw ms² output via the `units` workspace key; CARSPAN always outputs mMI².

---

## Installation

Releases are compiled using *Nuitka*. They are fully self-contained.
### Windows

Download `spectHR-Windows-vX.Y.Z.zip` from the [Releases](https://github.com/markspan/spectHR/releases) page, extract, and run `spectHR.exe`. No Python installation is required.

### Linux

Download `spectHR-Linux-vX.Y.Z.zip` from the [Releases](https://github.com/markspan/spectHR/releases) page, extract, and run `spectHR`. No Python installation is required.

### macOS

Download `spectHR-macOS-vX.Y.Z.zip` from the [Releases](https://github.com/markspan/spectHR/releases) page and extract `spectHR.app`. Drag it to `/Applications`. Because the app is not signed by Apple, macOS will block it the first time. Right-click `spectHR.app` in Finder, choose **Open**, and click **Open** in the dialog. Alternatively run `xattr -dr com.apple.quarantine /Applications/spectHR.app` in a Terminal.

---

## Contributing

spectHR is written in pure Python. The analysis library (`src/spectHR/`) and the GUI (`src/spectUI/`) are kept separate so the library can be used independently in scripts.

New HRV metrics can be added by decorating a method with `@hrv_metric` in `CardioSeries`, it will appear in the Parameters table and CSV automatically.

New file formats can be added by registering a loader function with `@register_loader(".ext")` in `src/spectHR/DataSet/loaders/`.

Fork the repository and open a pull request with a clear description of the change.

---

## License

spectHR is released under the GNU LGPL-2.1 license. See the [LICENSE](LICENSE) file for details.

---

## References

<a id="ref-arutyunova2024"></a>
Arutyunova, K.R., Bakhchina, A.V., Konovalov, D.I., Margaryan, M., Filimonov, A.V., & Shishalov, I.S. (2024). Heart rate dynamics for cognitive load estimation in a driving simulation task. *Scientific Reports*, 14, 31656. https://doi.org/10.1038/s41598-024-79728-x

<a id="ref-billman2013"></a>
Billman, G.E. (2013). The LF/HF ratio does not accurately measure cardiac sympatho-vagal balance. *Frontiers in Physiology*, 4, 26. https://doi.org/10.3389/fphys.2013.00026

<a id="ref-degeus2019"></a>
de Geus, E.J.C., Gianaros, P.J., Brindle, R.C., Jennings, J.R., & Berntson, G.G. (2019). Should heart rate variability be "corrected" for heart rate? Biological, quantitative, and interpretive considerations. *Psychophysiology*, 56(2), e13287. https://doi.org/10.1111/psyp.13287

<a id="ref-mulder1980"></a>
Mulder, G. (1980). *The heart of mental effort*. Ph.D. Thesis, University of Groningen.

<a id="ref-mulder1985"></a>
Mulder, L.J.M. (1985). Mental load, mental effort and attention. In A.W.K. Gaillard & W. Ritter (Eds.), *Tutorials in Event Related Potential Research: Endogenous Components*. Amsterdam: North Holland.

<a id="ref-mulder1988"></a>
Mulder, L.J.M. (1988). *Assessment of cardiovascular reactivity by means of spectral analysis*. Ph.D. Thesis, University of Groningen.

<a id="ref-mulder1992"></a>
Mulder, L.J.M. (1992). Measurement and analysis methods of heart rate and respiration for use in applied environments. *Biological Psychology*, 34, 205–236. https://doi.org/10.1016/0301-0511(92)90016-N

<a id="ref-mulder1989"></a>
Mulder, L.J.M. (1989). Cardiovascular reactivity and mental workload. *International Journal of Psychophysiology*, 7, 321.

<a id="ref-mulder2004"></a>
Mulder, L.J.M., de Waard, D., & Brookhuis, K.A. (2004). Estimating mental effort using heart rate and heart rate variability. In N.A. Stanton, A. Hedge, K. Brookhuis, E. Salas, & H. Hendrick (Eds.), *Handbook of Human Factors and Ergonomics Methods* (pp. 20.1–20.8). Boca Raton: CRC Press.

<a id="ref-peabody2023"></a>
Peabody, J.E., Ryznar, R., Ziesmann, M.T., & Gillman, L. (2023). A systematic review of heart rate variability as a measure of stress in medical professionals. *Cureus*, 15(1), e34345. https://doi.org/10.7759/cureus.34345

<a id="ref-derivecourt2008"></a>
De Rivecourt, M., Kuperus, M.N., Post, W.J., & Mulder, L.J.M. (2008). Cardiovascular and eye activity measures as indices for momentary changes in mental effort during simulated flight. *Ergonomics*, 51, 1295–1319. https://doi.org/10.1080/00140130802120267

<a id="ref-rompelman1980"></a>
Rompelman, O. (1980). Heart rate variability and the assessment of mental workload. In B.K.P. Horn (Ed.), *Methods of Information in Medicine*. Stuttgart: Schattauer.

<a id="ref-rompelman1977"></a>
Rompelman, O., Coenen, A.J.R.M., & Kitney, R.I. (1977). Measurement of heart-rate variability: Part 1 - Comparative study of heart-rate variability analysis methods. *Medical and Biological Engineering and Computing*, 15, 233–239. https://doi.org/10.1007/BF02441043

<a id="ref-stuiver2014"></a>
Stuiver, A., & Mulder, L.J.M. (2014). Cardiovascular state changes in simulated work environments. *Frontiers in Neuroscience*, 8, 399. https://doi.org/10.3389/fnins.2014.00399

<a id="ref-taskforce1996"></a>
Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology (1996). Heart rate variability: standards of measurement, physiological interpretation and clinical use. *Circulation*, 93(5), 1043–1065. https://doi.org/10.1161/01.CIR.93.5.1043

<a id="ref-tegegne2018"></a>
Tegegne, B., Man, T., van Roon, A., Riese, H., & Snieder, H. (2019). To the Editor: 10-second ECG-based RMSSD as valid measure of HRV. *Heart Rhythm*, 16(3), e35. https://doi.org/10.1016/j.hrthm.2018.10.038

<a id="ref-vanroon2025"></a>
van Roon, A.M., Span, M.M., Lefrandt, J.D., & Riese, H. (2025). Overview of mathematical relations between Poincaré plot measures and time and frequency domain measures of heart rate variability. *Entropy*, 27(8), 861. https://doi.org/10.3390/e27080861

<a id="ref-dewaard1996"></a>
de Waard, D. (1996). *The measurement of drivers' mental workload*. Ph.D. Thesis, University of Groningen.
