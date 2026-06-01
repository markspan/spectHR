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
- [Step 7, Examine respiration -> HR coupling (Transfer tab)](#step-7-examine-respiration--hr-coupling-transfer-tab)
- [Step 8, Export your results (Parameters tab)](#step-8-export-your-results-parameters-tab)

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
- [Adaptive bands](#adaptive-bands)
- [Transfer functions](#transfer-functions)
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

The CARSPAN tradition, which spectHR inherits, uses the constructs *mental effort* and *mental workload* rather than *stress*. Mental effort is defined as the resources invested in response to task demands - a construct that can be experimentally manipulated and whose physiological cost can be measured independently of the subjective experience of strain.

Mulder [(1980)](#ref-mulder1980) showed that task performance suppresses HRV, particularly in the mid-frequency band (~0.10 Hz) that reflects baroreceptor-driven blood pressure oscillations. Mulder [(1989)](#ref-mulder1989) formalised the framework: the suppression reflects invested effort, not task difficulty. A person who disengages from a hard task shows little HRV change; one working hard at an easy task shows a marked decrease ([Mulder, 1992](#ref-mulder1992)). The pattern generalises across driving ([de Waard, 1996](#ref-dewaard1996); [Mulder et al., 2004](#ref-mulder2004)), aviation ([De Rivecourt et al., 2008](#ref-derivecourt2008)), clinical work ([Peabody et al., 2023](#ref-peabody2023)), and driving simulation studies ([Arutyunova et al., 2024](#ref-arutyunova2024)).

HRV does not measure perceived stress. It measures a physiological state: the cost of effort investment that may or may not correspond to what a person calls "feeling stressed." The gap between the two is where individual differences and coping strategies operate. Treating HRV as a direct readout of stress conflates distinct levels of analysis.

### Frequency bands

spectHR follows the CARSPAN band convention. Band boundaries are **user-configurable**.

| Band | Default range | Reflects |
|------|--------------|------|
| VLF | 0.02–0.06 Hz | Slow regulatory processes |
| LF | 0.07–0.14 Hz | Baroreceptor reflex, mixed sympathetic/parasympathetic |
| HF | 0.15–0.40 Hz | Respiratory sinus arrhythmia, parasympathetic tone |

See [Mulder (1989)](#ref-mulder1989) and [Mulder (1988)](#ref-mulder1988) for background.

### Practical considerations

**Recording length.** Frequency resolution is $\Delta f = 1/T$. A 5-minute epoch gives $\Delta f \approx 0.003$ Hz, enough to resolve MF and HF cleanly. Shorter epochs give coarser resolution and wider confidence intervals (visible in spectHR's shaded CI band). Note that this applies to spectral measures only: [Tegegne et al. (2019)](#ref-tegegne2019) showed that a 10-second ECG can yield a valid RMSSD estimate in large samples.

**Artefacts are critical.** A single missed or spurious R-peak introduces broadband spectral energy that can swamp the genuine HRV signal ([Mulder, 1988](#ref-mulder1988)). This is why spectHR requires the user to inspect and verify the IBI series before computing any metrics.

**Normalisation.** Absolute spectral power in ms² scales with mean IBI squared, increasing at lower heart rates. The CARSPAN mMI² normalisation corrects for this automatically. For the Welch method the output unit is configurable: the default is **mMI²** (normalised, heart-rate-independent) but can be switched to **ms²** (raw IBI power, not normalised) via the `"units"` key in *Edit Parameters*. Whether to normalise HRV for mean heart rate is genuinely unresolved ([de Geus et al., 2019](#ref-degeus2019)), and no single recommendation fits all research questions.

<details>
<summary>mMI²/Hz vs ms²/Hz: which unit to use?</summary>

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
| **Transfer** | Bode plot of how the breathing rhythm drives HRV: modulus, phase, and coherence over frequency for each epoch |
| **Transfer profile** | Sliding-window time course of the same modulus / phase / coherence summaries per band |
| **Parameters** | See all HRV metrics in a table and export five CSVs (time-domain, PSD, profile summaries, transfer band summaries, transfer-profile time series) |

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

The **PSD tab** shows one power spectrum per active epoch. Four frequency bands are shaded (default ranges in brackets):

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

Configure it under **WorkSpace → Edit Parameters → Profile Settings** (see [Spectral profiles](#spectral-profiles) for the full parameter table).

Each profile dot is plotted at the **centre of the window that produced it**, not at the window's left edge. So the first dot for a 30 s window lands at `t = 15 s` within the epoch; the apparent "gap" at the left of each plot is the half-window that the first window's centre is offset from `t = 0`.


#### Alternative: Spectrogram

An alternative to the profiles plot is the 'spectrogram', where the x-axis is time in the epoch, the y-axis is the frequency, and the z-axis (color) depicts the power in that frequency, at that timepoint.

![spectHR](images/SpectrogramWindow.png)
---

### Step 7, Examine respiration -> HR coupling (Transfer tab)

![spectHR](images/TransferWindow.png)

The **Transfer tab** answers a different question from the PSD and Profiles tabs: not *"how much power is there in band X"*, but *"how much of the heart-rate fluctuation at frequency f can be predicted from the breathing signal at that frequency"*. The tab is only enabled when the recording carries a respiration channel; without one, the View-menu entry is greyed out and trying to open it pops a message explaining why.

Each active epoch gets one **Bode tile** with three stacked panels sharing the frequency x-axis:

- **Modulus** $|H(f)|$, how strongly breathing drives heart-rate variability at frequency $f$. Plotted as a black line with PSD-style under-curve fills coloured by band, and a legend showing the coherence-gated mean $|H|$ per band (the same number the export carries as `<band>_modulus`).
- **Phase** $\angle H(f)$ in radians, the delay between breathing and the HRV response. Drawn as a dot scatter where bins with coherence $\ge$ `min_coherence` are solid and bins below the gate fade to `coherence_mask_alpha` (default 0.20), so the eye can tell at a glance which dots the band-mean phase actually used. Toggle wrapped / unwrapped in Settings.
- **Coherence** $|C(f)|^2 \in [0, 1]$, the linear predictability of HRV from breathing at each frequency. A red dashed line at `min_coherence` marks the integrator's cutoff so the visual reference always tracks the statistical gate. When the recording's peak coherence is below 0.2 the y-axis auto-rescales so a weak curve stays visible.

![spectHR](images/TransferProfile.png)

A sibling **Transfer profile tab** shows the same modulus / phase / coherence summaries as time series. Inside each epoch a fixed window slides at a fixed step (same parameters used by the Profiles tab) and the per-band BandTransfer summary (mean modulus, mean phase, weighted coherence) is collected per window. One coloured line per band on a time axis. Tile y-axes are linked to the same modulus scale on first draw; Up / Down arrows then act per tile (the one your mouse hovers over) so you can zoom into a quiet epoch without disturbing the rest.

Both views share Settings, configurable under **WorkSpace -> Edit Parameters -> Transfer Settings**:

| Setting | Default | What it does |
|---|---|---|
| `window (sec)` / `step (sec)` | 30 / 5 | Sliding-window length and step used by the Transfer-profile view. Same sizing rules as the Profiles tab. |
| `min_coherence` | 0.5 | Squared-coherence gate. In compute, only bins clearing this threshold contribute to band-mean modulus / phase. In the per-epoch plot, the red dashed reference line sits at this value and the phase mask fades bins below it. |
| `f_min` / `f_max` | 0 / 0.5 Hz | Frequency-axis range for the per-epoch Bode plot. `f_max` also caps the native DFT grid. |
| `smooth` | `true` | Apply a 3-point triangular smoother to the auto- and cross-spectra before computing $H$ and coherence. Required for meaningful per-epoch coherence; the manual-faithful CARSPAN single-block path used `smooth=false`, which collapses coherence to $1$ at every bin and is left here as an opt-out. |
| `phase_view` | `wrapped` | Switch between wrapped (in $[-\pi, \pi]$) and unwrapped phase in the middle panel. |
| `show_coherence_threshold` | `true` | Draw the red reference line at `min_coherence` on the coherence panel. |
| `coherence_mask_alpha` | 0.20 | Opacity (0..1) applied to phase points where coherence is below `min_coherence`. Set to 0 to hide them entirely. |

Shift+Ctrl+P exports every Transfer (and Transfer-profile) tile as PNG + PDF to the configured Output folder, alongside the existing PSD and Profile exports.

---

### Step 8, Export your results (Parameters tab)

The **Parameters tab** shows a table with one row per epoch:

- **Time-domain:** count, mean, median, min, max, std, RMSSD, SDNN, SDSD
- **Poincaré:** SD1, SD2, SD2/SD1, ellipse area
- **Frequency-domain:** FullRange, VLF, LF, HF power and LF/HF ratio, in **mMI²** by default; Welch can be switched to **ms²** via *Edit Parameters*

Click **Save** to export. Up to five CSV files are written to the configured **Output** folder (see [Configuring the analysis](#configuring-the-analysis)). All are one-row-per-epoch and use `epoch` as the natural join key, so they merge as standard data frames in R, JASP, or SPSS. The four spectral / transfer files also carry **raw-array columns** alongside the scalar summaries; those columns hold comma-separated numbers inside a single cell. Each such cell is quoted on write (RFC 4180), so any compliant CSV reader treats it as a single field, and downstream code unpacks the list with one `strsplit` (R) or `split` (Python) call.

| File | Per-row contents |
| --- | --- |
| `{basename}.csv` | The table shown on screen, time-domain + Poincaré + integrated band powers. Scalars only. |
| `{basename}_psd.csv` | Per band: scalar `<band>_power` plus the raw spectrum slice as two equal-length lists, `<band>_freqs` (Hz) and `<band>_psd_raw` (PSD values in mMI²/Hz by default). |
| `{basename}_profiles.csv` | A shared `profile_timestamps` list (epoch-relative window-centre seconds) and, per band: the five summary statistics (`<band>_mean / _std / _min / _max / _t_max`) plus the raw band-power-per-window list `<band>_profile_raw`. |
| `{basename}_transfer.csv` | The settings used (`smooth`, `min_coherence`, `f_max`) and, per band: `<band>_modulus`, `<band>_phase_wrapped`, `<band>_phase_unwrapped`, `<band>_weighted_coherence`, `<band>_n_points`, `<band>_n_coherent`. Scalars only; FullRange is skipped (a 0.02 -- 0.5 Hz integration is a near-duplicate of the underlying curve). Written only when the recording has a respiration channel. |
| `{basename}_transfer_profile.csv` | The sliding-window settings (`window_s`, `step_s`, `smooth`, `min_coherence`, `f_max`), a shared `timestamps` list (epoch-relative window-centre seconds), and per band the five time series (`<band>_modulus`, `<band>_phase`, `<band>_phase_unwrapped`, `<band>_weighted_coherence`, `<band>_n_coherent`) as comma-separated arrays of length equal to `timestamps`. Written only when the recording has a respiration channel. |

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

<details>

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
</details>

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

See the note in Step 4 above: SD1 and SD2 add no statistical information beyond RMSSD and SDNN ([van Roon et al., 2025](#ref-vanroon2025)).

---

## Power Spectral Density, method details

### Welch's method

The IBI series (in ms) is resampled onto a uniform time grid with cubic interpolation, divided into overlapping segments, windowed, Fourier-transformed, and averaged. Averaging across segments reduces variance at the cost of frequency resolution. Default output: **mMI²/Hz**; configurable to **ms²/Hz** via the `"units"` workspace key.

<details>
<summary>Welch, algorithm detail</summary>

### Welch, algorithm detail

Let $`x(t)`$ denote the IBI series (in ms), resampled at $`f_s`$ Hz. `scipy.signal.welch` is invoked with `scaling='density'` and returns a one-sided PSD in ms²/Hz.

Band power $B$ in $`[f_l, f_h]`$ is obtained by trapezoidal integration with endpoint interpolation:

<div align="center">

$$B = \int_{f_l}^{f_h} \hat{S}(f) df \approx \sum_k \hat{S}(f_k) \Delta f$$

</div>

Because consecutive segments overlap, they are not statistically independent. The effective degrees of freedom are reduced accordingly (Percival & Walden, 1993):

<div align="center">

$$\nu = \frac{2K}{1 + 2\!\left(1 - \tfrac{1}{K}\right)\rho^2}$$

</div>

<div align="center">

$$CI(f) = \left[ \frac{\nu \cdot \hat{S}(f)}{\chi^2_{\nu, 1-\alpha/2}}, \quad \frac{\nu \cdot \hat{S}(f)}{\chi^2_{\nu, \alpha/2}} \right]$$

</div>

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

- **`carspan_strict`** is the preset bundle returned by `carspan_strict_options()`. Locks every setting the [CARSPAN manual](#ref-carspan-manual) leaves implicit, including `signal: "ibi_amplitude"` which switches the DFT to the IBI-amplitude formula of Eq. 3.21 of the [CARSPAN manual](#ref-carspan-manual). Reproduces the manual's reference epoch within ~2 % on every band. Use this when you want to compare against published CARSPAN values.
- **`carspan`** is the configurable variant. By default it's the unit-impulse SOC of Eq. 3.19, with the window, amplitude correction, reference-grid DC subtraction, and skip-first-event all exposed as separate workspace fields. Use this when you want to explore the effect of any of those settings.

Because both come from the same function, *every* setting `carspan_strict` uses is reachable from the configurable side too. The strict preset is exactly:

| `CarspanOptions` field | Strict value | Notes |
|---|---|---|
| `signal` | `"ibi_amplitude"` | flips the DFT from Eq. 3.19 → Eq. 3.21 |
| `taper` | `"carspan_index"` | Index taper (sample 0 has a small non-zero weight; scipy's tukey zeros it) |
| `alpha_taper` | `0.10` | 5 % cosine bell per side (`TaperPercent := 5`) |
| `freq_resolution` | `0.01` | display grid spacing (`NewRes`) |
| `amplitude_correction` | `false` | use the manual's flat `2/T` (no `N/S₂` variance-correction); *ignored on the `ibi_amplitude` branch* |
| `dc_removal` | `true` | reference-grid DC subtraction; *ignored on the `ibi_amplitude` branch* (mean subtraction handles DC) |
| `dc_grid` | `"carspan_strict"` | asymmetric reference grid; *ignored on the `ibi_amplitude` branch* |
| `smooth_for_display`, `f_max`, `plot_units` | caller's choice | not locked by the preset; defaults are `true`, `0.5`, `"mMI²/Hz"` |

The four "*ignored on the `ibi_amplitude` branch*" rows are kept on the preset only so a curious caller flipping `signal` back to `"events"` gets the CARSPAN-faithful unit-impulse SOC settings for comparison. In practice on the strict path only the top three rows do any work.


<details>
<summary>CARSPAN, algorithm detail</summary>

### CARSPAN, algorithm detail

#### Two views of the same signal

Mulder's manual gives two algebraically equivalent ways to write the CARSPAN spectrum, depending on what you treat as the "data" entering the DFT.

**Unit-impulse view (Eq. 3.19; used by `carspan`).** Following Rompelman [(1985)](#ref-rompelman1985) and Mulder [(1988)](#ref-mulder1988), the heartbeat is modelled as a sequence of unit impulses at the R-peak times $t_i$:

<div align="center">

$$x(t) = \sum_{i=1}^{N} \delta(t - t_i)$$

</div>

This is the *Integral Pulse Frequency Modulation* (IPFM) representation. Treating the signal outside the analysis window $[0, T]$ as a periodic continuation, the PSD at discrete frequencies $f_k = k/T$ is:

<div align="center">

$$S_{xx}(f_k) = \frac{2}{T}\left|\sum_{i=1}^{N} w_i\, e^{-2\pi j f_k t_i}\right|^2$$

</div>

The $w_i$ are tapering-window weights. The output is in events²/Hz; conversion to mMI²/Hz is done by the mixin layer.

**IBI-amplitude view (Eq. 3.21; used by `carspan_strict`).** The same recording, expressed as a sum over IBI amplitudes weighted by their local interval $t_i$:

<div align="center">

$$\tilde S_{xx}(f_k) = \frac{2}{T}\left|\sum_{i=1}^{N} t_i\, x_i\, e^{-2\pi j f_k T_i}\right|^2$$

</div>

where $x_i$ is the arithmetic-mean-subtracted IBI in ms, $t_i$ the local IBI duration in seconds, and $T_i = \sum_{j \le i} t_j$ the cumulative time of the $i$-th beat. The output is in ms²/Hz directly (variance per Hz), and the mixin layer normalises to mMI²/Hz by multiplying by $`10^6 / \overline{\text{IBI}}_{\text{ms}}^2`$, the milli-squared form of manual Eq. 3.20.

The two views describe the *same physical signal* and would integrate to the same total energy under continuous-signal idealisations. In the discrete sampled implementation they produce different magnitudes (per-bin scaling differs by ~ $\overline{\text{IBI}}^2$ ). The strict path is the one whose discrete output matches the manual's tabulated reference values.

**Which one matches the manual?** The strict path: verified against the manual's reference epoch to within ~2 % on every band, ~0.03 % on LF.

Internally, both variants run through the same `compute_carspan_psd` function in `CarspanPSD.py`; the `signal` field of `CarspanOptions` (`"events"` vs `"ibi_amplitude"`) selects the algorithm. The `carspan_strict_options()` helper builds the preset that locks in the manual-faithful choices for the IBI-amplitude path.

#### Differences between the two paths

| Behaviour | `carspan_strict` (Eq. 3.21) | `carspan` (Eq. 3.19, configurable) |
|---|---|---|
| `signal` field of `CarspanOptions` | `"ibi_amplitude"` | `"events"` (default) |
| What the DFT sees | IBI amplitude $(x_i - \bar x) \cdot t_i$ per beat | unit impulses, windowed |
| DC removal | mean-subtraction of the IBI amplitudes (built-in) | optional reference-grid subtraction (`dc_removal: true`) |
| Window function (default) | Index taper, `TaperPercent=5` (set by `carspan_strict_options()`) | any `scipy.signal.get_window` name (default `10% cosine bell` → Tukey α = 0.20) |
| Amplitude pre-factor | $2/T$ (fixed by Eq. 3.21) | $2N / (T \cdot S_2)$ by default (variance-correct); $2/T$ when `amplitude_correction: false` |
| First event | included (all $N$ IBIs participate; `skip_first_event` ignored on this branch) | included by default; `skip_first_event: true` drops the first R-peak |
| Native grid | $f_k = k/T$ for $k = 1..\lfloor f_\text{max}\,T\rfloor$ | same |
| Display resample | `Resample_R` (fractional-coverage weighted mean) | same |
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

1. **`signal: "ibi_amplitude"`** is the switch that selects the manual-faithful algorithm ([CARSPAN manual](#ref-carspan-manual) Eq. 3.21). On this branch the other strict-bundle fields (`amplitude_correction`, `skip_first_event`, `dc_removal`, `dc_grid`) are **ignored** by the compute layer (the manual fixes their values), so they don't need to appear in the Edit Parameters dialog.
2. **`window: "5% cosine bell"`** matches `TaperPercent := 5` (5 % cosine taper per side). The default of `"10% cosine bell"` is 10 % per side, which leaves ~3–5 % more energy on the table and is the single largest source of disagreement with strict if you only flip `signal`.

Setting `signal: "ibi_amplitude"` + `window: "5% cosine bell"` on the configurable `carspan` path reproduces `carspan_strict` to within ~1 % on every band.

Two small residuals remain between `carspan + signal=ibi_amplitude` and pure `carspan_strict`:

* **Window taper variant.** With `window: "5% cosine bell"` the configurable path uses scipy's Tukey window, which zeros the first/last sample exactly; Index taper gives them a small non-zero weight. The strict preset (`carspan_strict_options()`) hard-codes `taper: "carspan_index"` to get the CARSPAN-faithful version. Difference: ≪ 1 % on band power. Not exposed in the Edit Parameters dialog because it would be a new "carspan_index" choice for the window dropdown that most users wouldn't recognise; if you need it, set it via the Python API.
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

The convenience function `compute_carspan_psd_strict(...)` is a thin wrapper around the first form above (with a rename of the result's `method` field from `"carspan"` to `"carspan_strict"` so downstream code can tell the two apart). `carspan_strict_options()` is the single place that locks in the manual's choices for the IBI-amplitude path (5 % index taper, etc.); if you want a CARSPAN-faithful preset with one setting changed (e.g. no 3-MA smoothing), call `replace(carspan_strict_options(), smooth_for_display=False)`.

The mixin's `PsdMethod.mean_convention` is `"arithmetic"` for `carspan_strict` and `"harmonic"` everywhere else, picked automatically by `psd_method_from_workspace` based on the algorithm name. Library callers can override it by constructing a `PsdMethod` themselves and setting `series.psd_method = …`.

</details>

#### Reference-grid DC removal (configurable mode only)

The configurable unit-impulse branch does one extra trick the manual doesn't flag: before squaring, it subtracts the DFT of a perfectly periodic impulse train at the mean rate. At $f = 0$ both DFTs equal 1, so their difference is exactly zero and DC is removed. Beyond DC, the subtraction also cancels the spectral leakage that a mean-rate impulse train would otherwise contribute to the VLF region. For an approximately regular rhythm the correction is small at LF and HF but dominant at VLF.

In spectHR this is `FrequencyAnalysis.carspan.dc_removal` (also editable in *Edit Parameters*), only applicable to the configurable `carspan` variant. It defaults to `false` to preserve historical behaviour; turn it on when you need the VLF cleanup while retaining a custom window or the variance-correct amplitude. The IBI-amplitude `carspan_strict` path does **not** use this mechanism; its mean-subtraction step does the DC removal at the signal level (manual Eq. 3.21).

#### Native frequency grid

The grid runs from $f_1 = 1/T$ to $f_{k_\text{max}} = \lceil f_\text{max} \cdot T \rceil / T$, with spacing $\Delta f = 1/T$. The DC bin ($k = 0$) is excluded; it carries no HRV information.

#### Display grid and smoothing

The compute layer always returns the **un-smoothed** resampled spectrum; the 3-point moving-average smoother lives in the plot widget (`spectUI.PSDPlotWidget._fetch`), applied only when the active CARSPAN method has `smooth_for_display = True`. This split lets the *same* `series.psd()` call drive both the on-screen curve and the band-power integration, without `smooth=True/False` bookkeeping at the compute level.

**Compute layer (`series.psd()`, `compute_carspan_psd`).** Native spectrum → bin-averaged onto the `freq_resolution` display grid (`Resample`, default 0.01 Hz). That's it: no MA. This mirrors the un-smoothed spectrum the manual integrates for band powers (§3.2):

> *"No smoothing of the spectra is carried out on the spectra before computing the spectral band values"*

**Plot widget (`PSDPlotWidget._fetch`).** Pulls the un-smoothed spectrum from `series.psd()`, then applies a 3-point moving average to `power`, `ci_lower`, and `ci_upper` when the active CARSPAN method requests it. From the manual (§3.3):

> *"a moving average window over three frequency points (0.03 Hz bandwidth) is applied before plotting the spectral functions"*

The MA kernel is mean-preserving (each output bin is the arithmetic mean of three neighbours), so the area under the curve is unchanged; the smoothing only affects visual peak height. Welch and Lomb-Scargle results are never smoothed by the plot widget; the `smooth_for_display` setting lives on `CarspanOptions` and the plot widget consults it only for CARSPAN methods.

**Integration path (`band_power`, `band_powers`).** Runs on the *same* un-smoothed spectrum that `psd()` returns. No second back-end call, no smoothing toggle to remember.

#### Band power (formula 3.28)

Band power in $[f_l, f_h]$ is computed by rectangular summation on the resampled, unsmoothed display-grid spectrum:

<div align="center">

$$B(f_l, f_h) = \sum_{f_k = f_l}^{f_h} S_{xx}(f_k)\, \Delta f_\text{disp}$$

</div>

where $\Delta f_\text{disp}$ is the workspace `freq_resolution` setting (default 0.01 Hz).

The manual writes this on the native grid (Δf = 1/T); spectHR uses the resampled grid because that is what the reference CARSPAN implementation integrates. The two values agree to within edge-bin rounding, since the resample step is energy-conservative.

Welch band power uses trapezoidal integration; only the CARSPAN back-end uses this rectangular summation.

**Practical consequences.** Toggling `smooth_for_display` does not affect band power; integration runs on a separately computed unsmoothed copy. Changing `freq_resolution` *does* shift Δf_disp and the bin boundaries, so it has a small effect on band power: energy is preserved overall, but edge-bin rounding shifts slightly. For typical band definitions the difference remains below 1 %. To reproduce CARSPAN's reported values exactly, leave `freq_resolution` at `0.01`.

#### Normalisation to mMI² (formulae 3.20 and 3.29)

To make spectra independent of mean heart rate, both CARSPAN variants are reported in **milli-Modulation-Index squared** (mMI²/Hz for the spectrum, mMI² for band power), but the conversion from each variant's native unit is different.

**Strict (IBI-amplitude DFT, Eq. 3.21).** The raw spectrum is already in ms²/Hz (variance of the IBI per Hz). Eq. 3.20 normalises by $\bar x^2$ and the milli² convention adds a factor of $10^6$, giving:

<div align="center">

$$B'(f_l, f_h) = \frac{10^6}{\overline{\text{IBI}}_{\text{ms}}^2}\, B(f_l, f_h) \quad [\text{mMI}^2]$$

</div>

The mean IBI here is the **harmonic mean** of IBI (= arithmetic mean of the per-beat instantaneous rate); It differs from $T/N$ by ~0.3–0.8 % at typical resting HRV.

**Configurable (unit-impulse SOC, Eq. 3.19).** The raw spectrum is in events²/Hz. Eq. 3.20 divides by the squared mean rate $`\bar x = 1/\overline{\text{IBI}}_{\text{sec}}`$ to get a dimensionless modulation index, which the implementation re-expresses as a multiply-by-$`\overline{\text{IBI}}_{\text{ms}}^2`$ on the events²/Hz spectrum:

<div align="center">

$$B'(f_l, f_h) = \overline{\text{IBI}}_{\text{ms}}^2 \cdot B(f_l, f_h) \quad [\text{mMI}^2]$$

</div>

Here the mean IBI is the manual's $T/N$ (harmonic mean of rate), not the arithmetic-mean-of-rate flavour.If you need the manual-faithful answer, use `carspan_strict`.

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

A **spectral profile** is the time-resolved evolution of band power within one epoch ([CARSPAN manual](#ref-carspan-manual) §3.3.5). Where the PSD tab collapses time and gives one spectrum per epoch, the Profiles tab does the opposite: it collapses *frequency* inside each band and gives one curve per band drawn against time, answering *"how did this band's power rise and fall over the recording?"* rather than *"how is power distributed across frequency?"*

Configure profiles under **WorkSpace → Edit Parameters → Profile Settings**:

| Setting | Default | What it does |
|---|---|---|
| `bands` | `["LF", "HF"]` | Band names to plot. Must match names under PSD Settings; stale names are dropped automatically. Ignored when an adaptive band is active. |
| `window_s` | 30 s | Window length $W$ in seconds. For the LF band (lower edge 0.06 Hz) the [CARSPAN manual](#ref-carspan-manual) recommends $W \ge 50$ s; see algorithm detail for the general criterion. |
| `step_s` | 5 s | Step $S$ in seconds. Must be strictly less than $W$ so that consecutive windows overlap. |
| `smooth_for_display` | `false` | Apply a 3-point moving average along each band's time series for display only.|
| `adaptive_band` | *(none)* | One band whose edges follow the per-window breathing frequency rather than fixed Hz limits. When set, only that band is plotted and a right-hand y-axis shows the breathing frequency trace. |
| `adaptive_source` | `respiration channel` | Where per-window breathing frequency comes from. `respiration channel` uses the accelerometer-derived signal (CARSPAN-faithful). `psd peak` finds the spectral peak inside the band's static search range; no dedicated respiration channel is required. |
| `smooth_breath_freq` | `false` | Apply a 3-point moving average to the per-window breathing-frequency sequence before using it to set adaptive band edges. |

<details>
<summary>Algorithm detail</summary>

The implementation is `CardioMetricsMixin.band_power_profile`.

**spectHR extension: multiple PSD back-ends.** CARSPAN supports profiles only for the SOC spectral path. spectHR runs the same sliding-window scheme for all four methods (Welch, Lomb-Scargle, CARSPAN, and CARSPAN-strict), dispatching through the same `band_powers()` call used by the PSD tab. The active PSD method in *Edit Parameters → PSD Settings* applies immediately to profiles.

#### Step 1: Window enumeration

The [CARSPAN manual](#ref-carspan-manual) (§3.3.5, Eq. 3.34) defines the profile time series as a weighted sum of per-window band values $B_{x,i}(f_l, f_h)$:

<div align="center">

$$x(t) = S \cdot \sum_{i=1}^{N} B_{x,i}(f_l, f_h)\, \delta(t - t_i)$$

</div>

Each sample is attributed to the **centre** of its analysis window:

<div align="center">

$$t_i = t_0 + \tfrac{W}{2} + (i - 1) \cdot S, \qquad i = 1, 2, \dots, N$$

</div>

where $W$ is the window length, $S$ is the step size, and $t_0$ is the epoch's first R-peak time. The first profile sample therefore lands at $W/2$ into the epoch. With $T = t_\text{end} - t_0$ the epoch span, the window count is:

<div align="center">

$$N = \left\lfloor \frac{T - W}{S} \right\rfloor + 1$$

</div>


**Sizing criteria.** For the window: the lowest band frequency $f_l$ must satisfy $f_l > 1/W$; for reliability $W$ should be at least three times that minimum ($W \ge 3/f_{l,\min}$). The number of frequency points in band $[f_l, f_h]$ at window length $W$ is:

<div align="center">

$$n = \lfloor f_h \cdot W \rfloor - \lfloor f_l \cdot W \rfloor$$

</div>

For the step: the temporal resolution must be at least two samples per cycle of the slowest feature of interest. Computation cost scales as $W^2 / S$, so shorter windows and longer steps reduce cost at the expense of spectral and temporal resolution respectively.

A window with fewer than four R-peaks cannot yield a reliable PSD (CARSPAN's minimum-N gate). spectHR stores `NaN` for the entire column rather than CARSPAN's *skip-and-don't-store*, keeping the output matrix rectangular and time-aligned with `timestamps`.

#### Step 2: Per-window PSD (§3.3.4, no 0.01 Hz interpolation)

The manual (§3.3.5) explicitly states that the fixed 0.01 Hz frequency-grid interpolation applied for single-epoch spectral functions is *not* applied for profiles. spectHR follows this: the per-window PSD is computed by `_psd_for_band_power` on the R-peaks inside each window without resampling beyond what the chosen back-end itself performs. For `carspan_strict` this is the standard SOC → auto-spectrum pipeline without display smoothing: *"No smoothing is carried out before computing the spectral band values."* For Welch and Lomb-Scargle the standard IBI-based spectrum is used.

#### Step 3: Band-power integration

For each window and each band $[f_l, f_h]$, the band power is the rectangular sum over in-band frequency bins:

<div align="center">

$$B_{x,i}(f_l, f_h) = \sum_{f_l \le f_k \le f_h} S_{xx}(f_k)\, \Delta f$$

</div>

CARSPAN takes a fixed $\Delta f = 0.01\,\text{Hz}$ and identifies in-band bins by `round(F/FreqRes) − 1`. spectHR instead uses a **centred neighbour-spacing** bin width $\Delta f_k = (f_{k+1} - f_{k-1})/2$ (endpoints fall back to one-sided spacing). This adapts correctly to CARSPAN's resampled grid as well as the non-uniform grids produced by Welch and Lomb-Scargle. The mMI² conversion is applied upstream in `_carspan_display`, so no per-band rescaling is needed here.

#### Adaptive bands

CARSPAN supports one band that tracks the breathing frequency per window. spectHR exposes this through the `adaptive_band` setting and extends it with a configurable frequency source and optional smoothing.

A static band uses its configured $[f_l, f_h]$ unchanged for every window. An **adaptive** band re-centres on the per-window breathing frequency $f_b^{(i)}$; two per-band parameters, `resp_low` ($\Delta f_\text{lo}$) and `resp_high` ($\Delta f_\text{hi}$), define the half-widths around that centre:

<div align="center">

$$f_\text{low}^{(i)} = \max\!\bigl(0.01,\ f_b^{(i)} - \Delta f_\text{lo}\bigr)$$

$$f_\text{high}^{(i)} = \min\!\bigl(f_{\max}^{(i)},\ f_b^{(i)} + \Delta f_\text{hi}\bigr)$$

</div>

where $f_{\max}^{(i)}$ is the top of that window's PSD grid. A 0.01 Hz floor and an $f_{\max}$ cap are applied; if the clamps invert the band ($f_\text{high} \le f_\text{low}$), that window is NaN.

**Breathing-frequency sources** (`adaptive_source`):

*`respiration_channel`* (CARSPAN-faithful default). The accelerometer-derived respiration signal is sliced to the window and `mean_breath_frequency_hz()` is called. With alternating breath phases of starts $s_j$ and ends $e_j$, the breathing frequency is the reciprocal of the mean adjacent-phase cycle duration:

<div align="center">

$$f_b = \frac{1}{\bar{c}}, \qquad \bar{c} = \frac{1}{M}\sum_{j=1}^{M}(e_{j+1} - s_j), \quad c_j > 0$$

</div>

When fewer than two phases fall within the window, or when no respiration channel is loaded, the window falls back to `psd_peak` (a warning is logged once).

*`psd_peak`* (no respiration channel required; also the automatic per-window fallback). The breathing frequency is taken as the largest spectral peak inside the band's static search range:

<div align="center">

$$f_b^{(i)} = \arg\max_{f_l \le f_k \le f_h} S_{xx}^{(i)}(f_k)$$

</div>

read from the same per-window PSD computed in Step 2.

**Optional breathing-frequency smoothing.** When `smooth_breath_freq` is on, the full sequence $\{f_b^{(i)}\}$ is smoothed before any band edge is placed, using the same 3-point kernel as the display smoother:

<div align="center">

$$\tilde{f}_b[i] = \frac{f_b[i-1] + f_b[i] + f_b[i+1]}{3}$$

</div>

with asymmetric boundary weights $\tilde{f}_b[0] = \tfrac{3}{8}f_b[0] + \tfrac{5}{8}f_b[1]$ and $\tilde{f}_b[N-1] = \tfrac{5}{8}f_b[N-2] + \tfrac{3}{8}f_b[N-1]$. Because the complete sequence must be available before edges are placed, smoothing requires **two passes**: pass A collects breathing frequencies and caches per-window PSDs; the sequence is then smoothed; pass B re-integrates band power from the cached PSDs using the smoothed edges. Without smoothing a single pass suffices.

#### Result structure

`band_power_profile` returns a `ProfileResult` containing `timestamps` ($N$ window centres in seconds), `band_names`, a `band_power` matrix of shape $(n_\text{bands} \times N)$ in `unit` (a band-power unit, no `/Hz` suffix), the `method` name, `window_s`, `step_s`, and `resp_freqs` (per-window breathing frequency, shape $(N,)$, NaN where unavailable, or `None` when no band is adaptive).

#### Plot-only smoothing

`smooth_for_display` applies the same 3-point moving average **along each band's time axis**, purely at the display stage; it never affects stored band powers or integration. 

</details>

---

### Transfer functions

The PSD, Profiles and Spectrogram views describe heart-rate variability **on its own**. The Transfer view describes how HRV is **driven by breathing**: a frequency-by-frequency answer to "how much of the heart-rate fluctuation at $f$ is linearly predictable from the breathing signal at $f$, and what is the gain and the phase delay of that prediction?". The implementation is `spectHR.analysis.transfer.compute_transfer` (single-block, one Bode plot per epoch) and `compute_transfer_profile` (sliding-window, one time series per band). Both follow CARSPAN's transfer-function algorithm with one deliberate change documented below.

#### Reading the plots

Both transfer views render as **three-row tiles per epoch**, all sharing the same x-axis. The Bode tile (per-epoch view) plots against frequency; the Transfer-profile tile plots against time within the epoch.

| Row | Bode tile (per epoch) | Transfer-profile tile (sliding window) |
|---|---|---|
| **Top: modulus** | $\|H(f)\|$, a black line with PSD-style under-curve fills coloured by band. A peak at the breathing frequency means heart rate tracks breathing strongly there. The legend reports the coherence-gated mean $\|H\|$ per band (the same number that lands in `<band>_modulus`). Up / Down arrows shrink / grow the y-axis. | One coloured line per band: how the band-mean modulus changes window by window. Tiles start linked (same y-top across epochs) so cross-epoch reading works; Up / Down on a hovered tile unlinks just that one for a closer look. |
| **Middle: phase** | $\angle H(f)$ as a dot scatter (radians on the y-axis). Solid dots are bins whose coherence cleared `min_coherence`; faded dots (opacity = `coherence_mask_alpha`) are bins below the gate, shown so you can see where phase becomes noisy. Toggle wrapped (default, $[-\pi, \pi]$) or unwrapped in Settings. A near-zero phase at the breathing frequency means heart rate follows breathing without delay; a non-zero phase reflects a respiratory-sinus-arrhythmia time lag. | One coloured line per band over time. Same wrapped / unwrapped toggle. Watch for sustained drifts away from the band's resting-state phase; those flag breathing-pattern changes that are reshaping the coupling. |
| **Bottom: coherence** | $\|C(f)\|^2 \in [0, 1]$, the linear predictability of heart rate from breathing per bin. A red dashed line sits at `min_coherence` so the visual gate always matches the integrator's gate. If the recording's peak coherence falls below 0.2 the y-axis auto-rescales (with the peak value annotated on the y-label) so a faint trace stays visible instead of hugging the bottom spine. | Weighted-coherence per band as a time series, one coloured line per band. Same auto-rescale rule. Drops here mark windows where breathing stopped driving HRV cleanly. |

Vertical band-coloured shading on the phase and coherence panels marks the configured frequency bands so a peak at, say, 0.25 Hz reads immediately as "inside HF". The modulus panel uses PSD-style **under-curve** fills instead of vertical bars so the area visually scales with $\|H\|$ in that band. FullRange is intentionally not drawn on either view: a 0.02 -- 0.5 Hz overlay would blanket the secondary panels, and the integrated $|H|$ over that whole range is rarely meaningful.

Settings for both tiles (frequency range, smoothing, gate threshold, threshold-line toggle, mask alpha, phase view) live on a single **Transfer Settings** tab in *Edit Parameters*, paired horizontally where the keys go together so the dialog reads as a short list of related groups rather than a long ladder of fields.

<details>
<summary>Transfer, algorithm detail</summary>

#### Inputs

Two aligned signals: the IBI series from the heart and a continuous respiration signal (chest-belt accelerometer, thermistor, or any other 1-D breathing trace). Both are mean-subtracted, tapered with the CARSPAN 5 % index cosine bell (`TaperPercent := 5`), and IBI-amplitude weighted ($A_i = (x_i - \bar x) \cdot t_i$ in ms $\cdot$ s). The respiration signal is linearly interpolated at the R-peak times so the two channels share the same DFT evaluation grid (the cumulative R-peak times $T_i = \sum_{j \le i} t_j$).

The native frequency grid is $f_k = k/T$ from $k = 1$ to $\lfloor f_\text{max} \cdot T \rfloor$, with $T$ the epoch span. The grid excludes DC and goes up to `f_max` (default 0.5 Hz).

#### Auto and cross-spectra

Two complex DFTs are computed on the same grid, $X_\text{rsp}(f_k)$ and $X_\text{ibi}(f_k)$. From those:

<div align="center">

$$S_{xx}(f_k) = \tfrac{2 \cdot 10^6}{T} \, |X_\text{rsp}|^2, \qquad S_{yy}(f_k) = \tfrac{2 \cdot 10^6}{T} \, |X_\text{ibi}|^2$$

$$S_{xy}(f_k) = \tfrac{2 \cdot 10^6}{T} \, \overline{X_\text{rsp}} \cdot X_\text{ibi}$$

</div>

The $10^6$ factor is the $milli^2$ scaling that makes the rest of the pipeline read in $mMI^2$, matching the PSD section above.

#### The smoother (single deliberate divergence from CARSPAN)

The transfer formula

<div align="center">

$$|C(f)|^2 = \frac{|S_{xy}(f)|^2}{S_{xx}(f) \cdot S_{yy}(f)}$$

</div>

is algebraically identically $1$ at every frequency when the two spectra come from a single un-averaged periodogram. There is no actual statistical content. To get coherence values that mean anything, the cross- and auto-spectra must be averaged in some way before the ratio is taken. CARSPAN applies a 3-point triangular smoother on the profile branch only; the single-epoch view uses no smoothing and would render a flat `coherence=1` panel that's only useful as a sanity check. spectHR exposes the smoother as a single `smooth` Settings toggle defaulting to **true** on both paths, so the per-epoch Bode plot is informative out of the box. Set `smooth=false` to reproduce the CARSPAN-strict numbers.

#### Transfer function, modulus, phase, coherence

After the optional 3-point smoother:

<div align="center">

$$H(f) = \frac{S_{xy}(f)}{S_{xx}(f)}, \qquad |H(f)| = \sqrt{\Re\{H\}^2 + \Im\{H\}^2}, \qquad \angle H(f) = \arctan_2(\Im H, \Re H)$$

$$|C(f)|^2 = \frac{|S_{xy}(f)|^2}{S_{xx}(f) \cdot S_{yy}(f)}$$

</div>

Phase is kept twice: the wrapped form $\angle H(f) \in (-\pi, \pi]$ for visual structure and a separately unwrapped copy where 2$`\pi`$ jumps are removed via the CARSPAN counter (`UnwrapPhase`, threshold $\pi$, step $2\pi$). The Settings dropdown switches between them in the plot; both go to the CSV.

#### Band integrators

Three band summaries are computed per band $[f_l, f_h]$ on the spectra above, using the manual's $\lfloor f / \Delta f \rceil - 1$ edge-bin rounding. For each band:

<div align="center">

$`\bar M = \frac{1}{N_\text{coh}} \sum_{f_k \in [f_l, f_h],\ |C(f_k)|^2 \ge c_{\min}} |H(f_k)|`$

</div>

<div align="center">

$`\bar \varphi = \frac{1}{N_\text{coh}} \sum_{f_k \in [f_l, f_h],\ |C(f_k)|^2 \ge c_{\min}} \angle H(f_k)`$

</div>

<div align="center">

$`\bar C = \frac{\sum_{f_l \le f_k \le f_h} |C(f_k)|^2 \cdot S_{xx}(f_k)}{\sum_{f_l \le f_k \le f_h} S_{xx}(f_k)}`$

</div>

where $`c_{\min}`$ is the `min_coherence` setting. Modulus and phase are gated by `min_coherence` (only bins whose coherence clears the threshold contribute); weighted coherence is power-weighted by the respiration spectrum and uses every in-band bin. `n_points` is the total number of in-band bins; `n_coherent` is how many of them cleared the gate. All four numbers go to `{basename}_transfer.csv`.

#### Profile path

`compute_transfer_profile` does the same arithmetic in a sliding window: a fixed `window_s` length, fixed `step_s` step, the per-window band summaries collected into a `(n_bands x n_windows)` array. The window-centre times go to the `timestamps` column. Windows with fewer than 4 R-peaks are skipped and their column is NaN, exactly like the Profiles path. The CSV row carries the same band fields as the single-block CSV, but as comma-separated arrays of length `len(timestamps)`.

#### What survives, what changes

All per-bin formulas (taper, DFT, auto / cross spectrum scaling, $|H|$, $\angle H$, $|C|^2$, phase unwrapping), the three band integrators, and the bin-index rounding match CARSPAN's algorithm exactly. Smoothing is the one knob the user can flip: on by default in spectHR (both paths), originally off in CARSPAN on the single-block path. The CSV's `smooth` column records which setting produced each row.

</details>

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
| CARSPAN | mMI²/Hz | mMI² | No | Yes, $`\times \bar{\text{IBI}}_{\text{sec}}^{-2} \times 10^{-6}`$ |

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

New HRV metrics can be added by decorating a standalone function with `@hrv_metric` (from `spectHR.analysis.registry`) and placing it in `src/spectHR/analysis/`. It will appear in the Parameters table and CSV export automatically, with no changes to `CardioSeries` or any other class.

New file formats can be added by registering a loader function with `@register_loader(".ext")` in `src/spectHR/DataSet/loaders/`.

Fork the repository and open a pull request with a clear description of the change.

---

## Acknowledgements

The core HRV and spectral analysis algorithms in spectHR are derived from
CARSPAN, a cardiovascular
analysis package developed at the University of Groningen. We are grateful to the
authors of CARSPAN -- Ben Mulder and Arie van Roon -- for their work. Which is actually all the hard work.
The [CARSPAN manual](#ref-carspan-manual) was written by Ben Mulder, Arie van Roon and Hedwig Hofstetter.

LLM's were used in the creation of the documentation and the (re-)structuring of the code. All edits were checked by a human.

---

## License

spectHR is released under the GNU GPL-3.0 license. See the [LICENSE](LICENSE) file for details.

---

## References

<a id="ref-arutyunova2024"></a>
Arutyunova, K.R., Bakhchina, A.V., Konovalov, D.I., Margaryan, M., Filimonov, A.V., & Shishalov, I.S. (2024). Heart rate dynamics for cognitive load estimation in a driving simulation task. *Scientific Reports*, 14, 31656. https://doi.org/10.1038/s41598-024-79728-x

<a id="ref-degeus2019"></a>
de Geus, E.J.C., Gianaros, P.J., Brindle, R.C., Jennings, J.R., & Berntson, G.G. (2019). Should heart rate variability be "corrected" for heart rate? Biological, quantitative, and interpretive considerations. *Psychophysiology*, 56(2), e13287. https://doi.org/10.1111/psyp.13287

<a id="ref-carspan-manual"></a>
Mulder, B., Hofstetter, H., & van Roon, A. (2009). *CARSPAN for Windows: User's manual* (Version 0.0.1.36). University of Groningen. [docs/Carspan_Manual_VERSION_36.pdf](docs/Carspan_Manual_VERSION_36.pdf)

<a id="ref-mulder1980"></a>
Mulder, G. (1980). *The heart of mental effort*. Ph.D. Thesis, University of Groningen. [Ref](https://research.rug.nl/en/publications/the-heart-of-mental-effort/)

<a id="ref-mulder1988"></a>
Mulder, L.J.M. (1988). *Assessment of cardiovascular reactivity by means of spectral analysis*. Ph.D. Thesis, University of Groningen. [Ref](https://research.rug.nl/en/publications/assessment-of-cardiovascular-reactivity-by-means-of-spectral-anal/)

<a id="ref-mulder1992"></a>
Mulder, L.J.M. (1992). Measurement and analysis methods of heart rate and respiration for use in applied environments. *Biological Psychology*, 34, 205–236. https://doi.org/10.1016/0301-0511(92)90016-N

<a id="ref-mulder1989"></a>
Mulder, L.J.M. (1989). Cardiovascular reactivity and mental workload. *International Journal of Psychophysiology*, 7, 321. https://doi.org/10.1016/0167-8760(89)90258-4

<a id="ref-mulder2004"></a>
Mulder, L.J.M., de Waard, D., & Brookhuis, K.A. (2004). Estimating mental effort using heart rate and heart rate variability. In N.A. Stanton, A. Hedge, K. Brookhuis, E. Salas, & H. Hendrick (Eds.), *Handbook of Human Factors and Ergonomics Methods* (pp. 20.1–20.8). Boca Raton: CRC Press. https://doi.org/10.1201/9780203489925.ch20

<a id="ref-peabody2023"></a>
Peabody, J.E., Ryznar, R., Ziesmann, M.T., & Gillman, L. (2023). A systematic review of heart rate variability as a measure of stress in medical professionals. *Cureus*, 15(1), e34345. https://doi.org/10.7759/cureus.34345

<a id="ref-derivecourt2008"></a>
De Rivecourt, M., Kuperus, M.N., Post, W.J., & Mulder, L.J.M. (2008). Cardiovascular and eye activity measures as indices for momentary changes in mental effort during simulated flight. *Ergonomics*, 51, 1295–1319. https://doi.org/10.1080/00140130802120267

<a id="ref-rompelman1985"></a>
Rompelman, O. (1985). Spectral analysis of heart-rate variability. In J.F. Orlebeke, G. Mulder, & L.J.P. van Doornen (Eds.), *Psychophysiology of Cardiovascular Control* (pp. 315–331). New York: Plenum Press.

<a id="ref-stuiver2014"></a>
Stuiver, A., & Mulder, L.J.M. (2014). Cardiovascular state changes in simulated work environments. *Frontiers in Neuroscience*, 8, 399. https://doi.org/10.3389/fnins.2014.00399

<a id="ref-taskforce1996"></a>
Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology (1996). Heart rate variability: standards of measurement, physiological interpretation and clinical use. *Circulation*, 93(5), 1043–1065. https://doi.org/10.1161/01.CIR.93.5.1043

<a id="ref-tegegne2019"></a>
Tegegne, B., Man, T., van Roon, A., Riese, H., & Snieder, H. (2019). To the Editor: 10-second ECG-based RMSSD as valid measure of HRV. *Heart Rhythm*, 16(3), e35. https://doi.org/10.1016/j.hrthm.2018.10.038

<a id="ref-vanroon2025"></a>
van Roon, A.M., Span, M.M., Lefrandt, J.D., & Riese, H. (2025). Overview of mathematical relations between Poincaré plot measures and time and frequency domain measures of heart rate variability. *Entropy*, 27(8), 861. https://doi.org/10.3390/e27080861

<a id="ref-dewaard1996"></a>
de Waard, D. (1996). *The measurement of drivers' mental workload*. Ph.D. Thesis, University of Groningen. https://www.researchgate.net/publication/237132452_The_Measurement_of_Drivers'_Mental_Workload
