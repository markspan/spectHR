<details>
<summary>⚠️ CAUTION</summary>
This project is a work in progress. Blood pressure analysis is not yet implemented. Breathing signal extraction and visualisation are functional but should be treated as experimental.
</details>

---

- [What is spectHR?](#what-is-specthr)
- [Theoretical background](#theoretical-background)
  - [Mental effort, not stress](#mental-effort-not-stress)
  - [Frequency bands](#frequency-bands-1)
  - [Practical considerations](#practical-considerations)
- [Getting started](#getting-started)
- [The interface at a glance](#the-interface-at-a-glance)
- [Step 1, Check and clean the ECG](#step-1-check-and-clean-the-ecg-preprocessing-tab)
- [Step 2, Inspect the heart rate series](#step-2-inspect-the-heart-rate-series-ibi-series-tab)
- [Step 3, Define your analysis segments](#step-3-define-your-analysis-segments-epochs-tab)
- [Step 4, Explore autonomic dynamics (Poincaré tab)](#step-4-explore-autonomic-dynamics-poincaré-tab)
- [Step 5, Examine frequency-domain HRV (PSD tab)](#step-5-examine-frequency-domain-hrv-psd-tab)
- [Step 6, Export your results](#step-6-export-your-results-parameters-tab)
- [Configuring the analysis](#configuring-the-analysis)
- [Data Formats](#data-formats)
- [IBI Classification](#ibi-classification)
- [Breathing Signal Extraction](#breathing-signal-extraction)
- [Poincaré Metrics](#poincaré-metrics)
- [Power Spectral Density, method details](#power-spectral-density-method-details)
  - [Welch's method](#welchs-method)
  - [Lomb-Scargle periodogram](#lomb-scargle-periodogram)
  - [CARSPAN method](#carspan-method)
  - [Frequency bands](#frequency-bands)
  - [Units and normalisation](#units-and-normalisation)
- [Installation](#installation)
- [Contributing](#contributing)
- [License](#license)

---

# spectHR: An Interactive HRV Analysis Tool

## What is spectHR?

![spectHR](images/MainWindow.PNG)

**spectHR** is a free, open-source desktop application for Heart Rate Variability (HRV) analysis. It is built for researchers and students who want to move from a raw cardiovascular recording to interpretable HRV metrics without writing any code, and without trusting a black box.

Heart rate variability reflects the beat-to-beat fluctuations in the time between heartbeats. These fluctuations are regulated by the autonomic nervous system: higher HRV generally indicates flexible, healthy regulation; lower HRV is associated with stress, disease, or fatigue. By analysing the power in different frequency bands of the IBI series, spectHR lets you separate the parasympathetic (HF) and sympathetic/parasympathetic (LF) contributions to heart rate control in each named epoch of your recording.

The key principle behind spectHR is that **you have to check data quality**. Every step that could go wrong, R-peak detection, noisy intervals, epoch boundaries, is shown to you visually and can be corrected before any metrics are computed.

---

## Theoretical background

Generally, heart rate variability (HRV) reflects the continuous interplay between the two branches of the autonomic nervous system (ANS). The **parasympathetic** branch, acting via the vagus nerve, produces rapid beat-to-beat fluctuations — including respiratory sinus arrhythmia (RSA). The **sympathetic** branch exerts slower influences, mainly through vasomotor tone and blood pressure regulation. Because the two branches operate at different speeds, spectral analysis separates their contributions by frequency. ([Mulder, 1989](#ref-mulder1989); [Task Force of the European Society of Cardiology, 1996](#ref-taskforce1996)).

A note on the two-branch picture: both branches can be simultaneously active or withdrawn. HRV does not directly reveal what the sympathetic branch is doing. Broader conclusions about autonomic balance require additional signals such as blood pressure, breathing patterns or pre-ejection period.

### Mental effort, not stress

The CARSPAN tradition, which spectHR inherits, uses *mental effort* and *mental workload* rather than *stress*. Mental effort is defined as the resources invested in response to task demands - a construct that can be experimentally manipulated and whose physiological cost can be measured independently of the subjective experience of strain.

Mulder [(1980)](#ref-mulder1980) showed that task performance suppresses HRV, particularly in the mid-frequency band (~0.10 Hz) that reflects baroreceptor-driven blood pressure oscillations. Mulder [(1989)](#ref-mulder1989) formalised the framework: the suppression reflects invested effort, not task difficulty. A person who disengages from a hard task shows little HRV change; one working hard at an easy task shows a marked decrease ([Mulder, 1992](#ref-mulder1992)). The pattern generalises across driving ([de Waard, 1996](#ref-dewaard1996); [Mulder et al., 2004](#ref-mulder2004)), aviation ([De Rivecourt et al., 2008](#ref-derivecourt2008)), clinical work ([Peabody et al., 2023](#ref-peabody2023)), and driving simulation studies ([Arutyunova et al., 2024](#ref-arutyunova2024)).

HRV does not measure perceived stress. It measures a physiological state: the cost of effort investment that may or may not correspond to what a person calls "feeling stressed." The gap between the two is where individual differences and coping strategies operate. Treating HRV as a direct readout of stress conflates distinct levels of analysis.

### Frequency bands

spectHR computes power in three bands ([Mulder, 1989](#ref-mulder1989); [Mulder, 1988](#ref-mulder1988)), following the CARSPAN convention. Band boundaries are **user-configurable** to accommodate different research traditions.

| Band | Default range | Reflects |
|------|--------------|---------| 
| VLF | 0.02–0.06 Hz | Thermoregulation, hormonal rhythms; requires ≥ 5 min epochs |
| MF | 0.06–0.14 Hz | Baroreceptor-driven vasomotor oscillations; most sensitive to mental effort |
| HF | 0.14–0.40 Hz | Respiratory sinus arrhythmia; parasympathetically mediated but confounded by breathing pattern |

The **LF/HF ratio** as a sympatho-vagal balance index is contested ([Billman, 2013](#ref-billman2013)); the CARSPAN tradition prefers absolute band power normalised by mean heart rate (mMI²).

### Practical considerations

**Recording length.** Frequency resolution is $\Delta f = 1/T$. A 5-minute epoch gives $\Delta f \approx 0.003$ Hz, enough to resolve MF and HF cleanly. Shorter epochs give coarser resolution and wider confidence intervals — visible in spectHR's shaded CI band. Note that this applies to spectral measures only: [Tegegne et al. (2019)](#ref-tegegne2018) showed that a 10-second ECG yields a valid RMSSD estimate in large samples.

**Artefacts are critical.** A single missed or spurious R-peak introduces broadband spectral energy that can swamp the genuine HRV signal ([Mulder, 1988](#ref-mulder1988)). This is why spectHR requires the user to inspect and verify the IBI series before computing any metrics.

**Normalisation.** Absolute spectral power in ms² scales with mean IBI squared, increasing at lower heart rates. The CARSPAN mMI² normalisation corrects for this automatically. For the Welch and Lomb-Scargle methods normalisation is not applied automatically: whether and how to correct HRV for mean heart rate is genuinely unresolved ([de Geus et al., 2019](#ref-degeus2019)), and no single recommendation fits all research questions. We have made both corrected and uncorrected approaches available so researchers can choose.

**spectHR operates on IBI time series.** The core analyses - time-domain HRV, spectral band power, Poincaré geometry - require only inter-beat intervals. Simultaneous blood pressure or respiration recordings are not needed. That said, the most reliable conclusions about mental effort come from converging evidence across heart rate, HRV, and when available, blood pressure and baroreflex sensitivity. Stuiver and Mulder [(2014)](#ref-stuiver2014) showed that the full cardiovascular pattern was more diagnostically informative than any single measure in isolation.

---

## Getting started

1. Launch the application. On first run it creates a default workspace pointing to your Documents folder.
2. Open **WorkSpace → Edit Workspace** to point spectHR at the folder where your data files live.
3. Your files appear in the tree on the left. Click one to load it.
4. Work through the tabs from left to right: clean the ECG, define your epochs, then read the results.

---

## The interface at a glance

The window is divided into two areas. On the left is a narrow **file tree** listing all datasets in your configured data folder. On the right is the main **analysis area**, organised into six tabs:

| Tab | What you do there |
|-----|------------------|
| **Preprocessing** | Verify and correct R-peak detection |
| **IBI Series** | Review the heart rate time course |
| **Poincaré** | Explore beat-to-beat dynamics visually |
| **Epochs** | Draw and adjust your analysis segments |
| **PSD** | Read the frequency-domain power spectrum per epoch |
| **Parameters** | See all HRV metrics in a table and export to CSV |

---

## Step 1, Check and clean the ECG (Preprocessing tab)

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

## Step 2, Inspect the heart rate series (IBI Series tab)

Once the peaks look correct, switch to the **IBI Series tab** to see heart rate over time in beats per minute. If a breathing signal is available it is shown as a faint green overlay.

---

## Step 3, Define your analysis segments (Epochs tab)

HRV metrics are always computed within named segments. The **Epochs tab** shows a Gantt-style chart. If your recording contains marker events, epochs are built automatically. You can also add epochs manually via **Actions → Add Epoch** and trim them by dragging their edges. Any change here immediately updates the Poincaré plot, the PSD plots, and the metrics table.

---

## Step 4, Explore autonomic dynamics (Poincaré tab)

The **Poincaré tab** shows a scatter plot where each point represents one heartbeat: its IBI on the x-axis and the following IBI on the y-axis. A healthy autonomic system produces a characteristic elliptical cloud elongated along the diagonal. The short axis (SD1) reflects rapid, beat-to-beat variability; the long axis (SD2) reflects slower variability. Each active epoch is drawn in a different colour with its own ellipse overlaid.

<details>
<summary>A note on SD1 and SD2</summary>

SD1 and SD2 carry no statistical information beyond RMSSD and SDNN respectively. Van Roon et al. (2025) demonstrate this rigorously: SD1 $= \text{RMSSD}/\sqrt{2}$ by definition, and SD2 follows algebraically from SDNN and RMSSD. spectHR reports them because they are widely expected in the literature and because the Poincaré plot is a useful visual summary, but users should not treat SD1 and SD2 as independent metrics alongside RMSSD and SDNN in statistical analyses.

*van Roon, A.M., Span, M.M., Lefrandt, J.D., & Riese, H. (2025). Overview of mathematical relations between Poincaré plot measures and time and frequency domain measures of heart rate variability. Entropy, 27(8), 861.* https://doi.org/10.3390/e27080861

</details>

---

## Step 5, Examine frequency-domain HRV (PSD tab)

![spectHR](images/PSDWindow.PNG)

The **PSD tab** shows one power spectrum per active epoch, stacked vertically. Three frequency bands are shaded:

- **VLF (0.02–0.06 Hz)**, slow regulatory processes; requires long recordings.
- **LF (0.06–0.14 Hz)**, baroreflex, mixed sympathetic/parasympathetic.
- **HF (0.14–0.40 Hz)**, respiratory sinus arrhythmia, parasympathetic tone.

The shaded grey band is the **confidence interval**. Three PSD methods are available, selected in **WorkSpace → Edit Parameters**. The method takes effect immediately without restarting.

---

## Step 6, Export your results (Parameters tab)

The **Parameters tab** shows a table with one row per epoch:

- **Time-domain:** count, mean, median, min, max, std, RMSSD, SDNN, SDSD
- **Poincaré:** SD1, SD2, SD2/SD1, ellipse area
- **Frequency-domain:** VLF, LF, HF power and LF/HF ratio
  - **ms²** when using Welch or Lomb-Scargle
  - **mMI²** when using the CARSPAN method

Click **Save** to export to CSV.

---

## Configuring the analysis

All parameters are stored in a JSON workspace file, editable through the application menus.

**WorkSpace → Edit Workspace** changes the three folder paths (data, cache, export).

**WorkSpace → Edit Parameters** covers:
- *Frequency Analysis*, PSD method, band edges and colours, method-specific parameters, CI level.
- *IBI Classification*, window length, threshold multiplier, TL ceiling.
- *ECG Preprocessing*, high-pass filter settings.

Changes take effect immediately and are saved to disk.

---

## Data Formats

### XDF (LabStreamingLayer)

spectHR reads `.xdf` files from [LabStreamingLayer](https://github.com/sccn/labstreaminglayer), designed for use with the [Polar H10](https://www.polar.com/en/sensors/h10-heart-rate-sensor) via [PolarBLE](https://github.com/markspan/PolarBLE). Streams are identified automatically. Epoch markers follow `start <label>` / `stop <label>` or `end <label>` conventions.

### Polar .txt

The plain-text RR-interval export format from the Polar app. See `ExampleData/`.

### CARSPAN .evt / .nff

CARSPAN event files. If an `.nff` file with the same base name is present, spectHR loads the ECG channel from it.

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
| T | Degenerate (NaN or zero duration); excluded from all metrics | — |

<details>
<summary>Terminology</summary>

**Terminology:** The CARSPAN documentation occasionally uses the term *Energy* where *Power* is the correct term. spectHR uses *Power* consistently throughout.

</details>

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

</details>

---

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

---

## Breathing Signal Extraction

When a Polar H10 accelerometer stream is present, spectHR derives a respiration surrogate from the 3-axis chest-belt movement data by removing the gravity component, bandpassing to 0.10–0.70 Hz, and applying PCA to extract the dominant axis of motion as a single 1-D signal. The result is z-score normalised and overlaid in green on the ECG and heart rate plots. Inhalation phases are shaded in light blue.

---

## Poincaré Metrics

**SD1**, beat-to-beat variability, equal to $\text{RMSSD}/\sqrt{2}$:

$$\text{SD1} = \sqrt{\tfrac{1}{2} \cdot \mathrm{Var}(\text{IBI}_{i+1} - \text{IBI}_i)}$$

**SD2**, longer-term variability, algebraically related to SDNN and RMSSD:

$$\text{SD2} = \sqrt{2 \cdot \mathrm{Var}(\text{IBI}_i) - \tfrac{1}{2} \mathrm{Var}(\text{IBI}_{i+1} - \text{IBI}_i)}$$

**SD2/SD1**, autonomic balance index.

**Ellipse area** $= \pi \cdot \text{SD1} \cdot \text{SD2}$, total HRV.

**Important:** SD1 and SD2 are fully determined by RMSSD and SDNN and therefore carry no additional statistical information ([van Roon et al., 2025](#ref-vanroon2025)). Including all four in a statistical model introduces redundancy.

---

## Power Spectral Density, method details

### Welch's method

The IBI series (in ms) is resampled onto a uniform grid using linear interpolation, divided into overlapping segments, windowed, Fourier-transformed, and averaged. Averaging over segments reduces variance at the cost of frequency resolution. Output units: **ms²/Hz**; band power in **ms²**.

<details>
<summary>Welch, algorithm detail</summary>

### Welch, algorithm detail

Let $`x(t)`$ denote the IBI series (ms) resampled at $`f_s`$ Hz. `scipy.signal.welch` is called with `scaling='density'`, returning the one-sided PSD in ms²/Hz.

Band power $B$ in $`[f_l, f_h]`$ is computed by trapezoidal integration with endpoint interpolation:

$$B = \int_{f_l}^{f_h} \hat{S}(f) df \approx \sum_k \hat{S}(f_k) \Delta f$$

For $K$ non-overlapping segments the degrees of freedom are $\nu = 2K$, giving chi-square confidence intervals:

$$CI(f) = \left[ \frac{\nu \cdot \hat{S}(f)}{\chi^2_{\nu, 1-\alpha/2}}, \quad \frac{\nu \cdot \hat{S}(f)}{\chi^2_{\nu, \alpha/2}} \right]$$

where

$$\nu = \frac{2 \cdot K \cdot W_{\text{eff}}}{1 + 2\sum_{k=1}^{K-1}\left(1 - \frac{k}{K}\right)\rho^2(k)}$$

where:
- $K$ — number of segments
- $W_{\text{eff}}$ — effective noise bandwidth of the window (e.g. 1.5 for Hann, 1.36 for Hamming)
- $\rho(k)$ — correlation between segments $k$ steps apart (depends on overlap fraction)
- $\chi^2_{\nu, p}$ — chi-square quantile at probability $p$ with $\nu$ degrees of freedom
- $\alpha$ — significance level (e.g. 0.05 for a 95% CI)

For the common case of a Hann window with 50% overlap, this simplifies to approximately:

$$\nu \approx \frac{8 \cdot K}{3}$$

**Default parameters** (configurable in *Edit Parameters*):

| Parameter | Default | JSON key |
|-----------|---------|----------|
| Resampling frequency | 4 Hz | `fs` |
| Segment length | 256 samples | `nperseg` |
| Overlap | 128 samples | `noverlap` |
| FFT length | same as `nperseg` | `nfft` |
| Window | Hann | `window` |

**Note on resampling:** The 4 Hz resampling rate gives a frequency resolution of $f_s / \text{nperseg} = 4/256 = 0.0156~\text{Hz}$, which is adequate for the HRV bands. At short epochs where the number of IBI samples is less than `nperseg`, the segment length is reduced to the number of available samples and overlap is halved automatically.

</details>

---

### Lomb-Scargle periodogram

The Lomb-Scargle method evaluates the spectrum directly at the original, irregularly-spaced beat timestamps, no resampling required. The mean IBI is subtracted before estimation to suppress the DC component. Output units: **ms²/Hz**; band power in **ms²**.

<details>
<summary>Lomb-Scargle, algorithm detail</summary>

### Lomb-Scargle, algorithm detail

Let $`t_i`$ denote the R-peak times (s) and $`x_i = \text{IBI}_i - \bar{\text{IBI}}`$ (ms) the mean-subtracted IBIs. The angular frequency grid $`\omega = 2\pi f`$ is evaluated over $`[f_\text{min}, f_\text{max}]`$ at `nfreqs` equally spaced points. The periodogram $`P(\omega)`$ is computed by `scipy.signal.lombscargle` with `normalize=False` and scaled to a power density:

$$\hat{S}(f_k) = \frac{2T}{N^2} P(\omega_k)$$

where $`T = t_N - t_1`$ is the recording duration and $N$ the number of beats. Band power is computed by trapezoidal integration of the output grid. Confidence intervals use the Scargle (1982) effective degrees of freedom:

$$\nu = 2 \cdot \lfloor 2(f_\text{max} - f_\text{min}) T \rceil$$

This accounts for the adaptive frequency resolution of Lomb-Scargle compared to the regular DFT grid.

**Default parameters** (configurable in *Edit Parameters*):

| Parameter | Default | JSON key |
|-----------|---------|----------|
| Number of frequency points | 1000 | `nfreqs` |
| Lower frequency floor | 0.0001 Hz | `fmin_floor` |

</details>

---

### CARSPAN method

The CARSPAN method implements the direct Discrete Fourier Transform on R-peak event times, following the algorithm described by Mulder [(1988)](#ref-mulder1988) and used in the CARSPAN software package. No resampling is performed. The spectrum is computed on the native frequency grid $f_k = k/T$ (resolution $\Delta f = 1/T$), then interpolated onto a fixed display grid. Band power is computed on the native grid following CARSPAN formula 3.28. Output units: **mMI²**.

<details>
<summary>CARSPAN, algorithm detail</summary>

### CARSPAN, algorithm detail

#### The R-peak event series

Following Rompelman (1975) and Mulder [(1988)](#ref-mulder1988), the heart rate signal is represented as a series of unit impulses at the R-peak occurrence times $t_i$ (in seconds):

$$x(t) = \sum_{i=1}^{N} \delta(t - t_i)$$

This is the *Integral Pulse Frequency Modulation* (IPFM) model representation. The spectrum of this series reflects **heart rate** variability, not IBI variability directly. CARSPAN normalises out the mean heart rate afterwards (formula 3.20) to make the two equivalent.

#### Power spectral density (formula 3.19)

Assuming periodicity outside the analysis segment $[0, T]$, the power spectral density at discrete frequencies $f_k = k/T$ is:

$$S_{xx}(f_k) = \frac{2}{T}\left|\sum_{i=1}^{N} w_i e^{-2\pi j f_k t_i}\right|^2 = \frac{2}{T}\left[\left(\sum_{i=1}^{N} w_i \cos(2\pi f_k t_i)\right)^2 + \left(\sum_{i=1}^{N} w_i \sin(2\pi f_k t_i)\right)^2\right]$$

where $w_i$ is the $i$-th coefficient of a tapering window (default: Hanning, as used in CARSPAN; configurable). The window is applied to suppress spectral leakage at the segment boundaries.

**Deviation from CARSPAN:** In CARSPAN, formula 3.19 uses $w_i = 1$ (no window) for the analytical formula, and a 5 % cosine taper is applied separately. spectHR applies a full-length configurable window to each $w_i$ directly in formula 3.19. The practical effect is similar: both suppress leakage at the segment edges.

#### Native frequency grid

The native grid runs from $f_1 = 1/T$ to $f_{k_\text{max}} = \lceil f_\text{max} \cdot T \rceil / T$, with spacing $\Delta f = 1/T$. The DC component ($k = 0$) is excluded because it carries no HRV information.

#### Display grid and smoothing

The native spectrum is interpolated onto a fixed display grid with step `freq_resolution` (default 0.01 Hz). A finer value produces a smoother curve; a coarser value shows the raw native lines more directly. **Band power values are never affected by `freq_resolution`.**

Following the CARSPAN manual (§3.3, pre-algorithm choices):

> *"a moving average window over three frequency points (0.03 Hz bandwidth) is applied before plotting the spectral functions"*

When `smooth_for_display = True` (the default), a 3-point unweighted moving average is applied to the interpolated display spectrum before it is shown. The same passage also states:

> *"No smoothing of the spectra is carried out on the spectra before computing the spectral band values"*

Accordingly, smoothing is applied only in the display path; band power is always computed from the unsmoothed native grid.

#### Band power (formula 3.28)

Band power in $[f_l, f_h]$ is computed by direct summation on the native grid:

$$B(f_l, f_h) = \sum_{f_k = f_l}^{f_h} S_{xx}(f_k) \Delta f, \qquad \Delta f = \frac{1}{T}$$

This is a rectangular (Riemann) summation, matching CARSPAN exactly. spectHR uses trapezoidal integration for Welch and Lomb-Scargle band power; only the CARSPAN back-end uses rectangular summation to match formula 3.28.

**Important:** Because $\Delta f = 1/T$ is fixed by the recording duration, not by `freq_resolution`, band power values are completely independent of the display resolution setting.

#### Normalisation to mMI² (formulae 3.20 and 3.29)

The raw spectrum is in units of events²/Hz. To make it dimensionless and independent of mean heart rate, it is normalised by the squared mean of the R-peak event series. For the unit-impulse representation, the mean equals the mean heart rate $\bar{x} = 1 / \bar{\text{IBI}}_\text{sec}$. The normalised band power is:

$$B'(f_l, f_h) = \frac{B(f_l, f_h)}{\bar{x}^2} \times 10^6 = B(f_l, f_h) \times \bar{\text{IBI}}_\text{sec}^2 \times 10^6 \quad [\text{mMI}^2]$$

Multiplication by $10^6$ scales the result into a convenient numeric range (milli-Modulation-Index squared, mMI²), consistent with CARSPAN output convention. An important consequence of this normalisation is that mMI² values are largely independent of mean heart rate, making them directly comparable between subjects and sessions.

**Implementation note on units:** The normalisation formula divides by $`\bar{x}^2 = (1/\bar{\text{IBI}}_\text{sec})^2`$, which is equivalent to multiplying by $\bar{\text{IBI}}_\text{sec}^2$. Since IBI values are stored internally in seconds, the code computes `mean_ibi_sec = mean(ibi_ms) / 1000` and then applies `power_raw * mean_ibi_sec² * 1e6`. A common error is to use `mean_ibi_ms²` instead, which would make the result $10^6$ times too small.

**Default parameters** (configurable in *Edit Parameters*):

| Parameter | Default | JSON key | Effect |
|-----------|---------|----------|--------|
| Display grid resolution | 0.01 Hz | `freq_resolution` | Smoothness of displayed curve; does not affect band power |
| Tapering window | `hann` | `window` | Any `scipy.signal.get_window` name |
| 3-point display smoothing | `true` | `smooth_for_display` | Matches CARSPAN plot convention |

</details>

---

### Confidence intervals

spectHR adds confidence intervals to all three PSD methods. CARSPAN itself does not compute CIs, this is a spectHR extension. The CI reflects how much the spectral estimate would vary if the measurement were repeated under identical conditions. All three methods use a chi-square CI of the form:

$$\frac{\nu \cdot \hat{S}(f)}{\chi^2_{1-\alpha/2, \nu}} \leq S(f) \leq \frac{\nu \cdot \hat{S}(f)}{\chi^2_{\alpha/2, \nu}}$$

The difference lies in how the degrees of freedom $\nu$ are determined.

---

### Frequency bands

All three methods share the same configurable band definitions:

| Band | Default range | Reflects |
|------|--------------|---------| 
| VLF | 0.02–0.06 Hz | Slow regulatory processes; requires long recordings |
| LF | 0.06–0.14 Hz | Baroreceptor reflex, mixed sympathetic/parasympathetic |
| HF | 0.14–0.40 Hz | Respiratory sinus arrhythmia, parasympathetic tone |

Band edges are configurable in *Edit Parameters*. If your participants breathe slowly, you may need to extend the HF band to lower frequencies.

---

### Units and normalisation

| Method | PSD unit | Band power unit | Normalised by mean HR? |
|--------|----------|-----------------|----------------------|
| Welch | ms²/Hz | ms² | No |
| Lomb-Scargle | ms²/Hz | ms² | No |
| CARSPAN | mMI²/Hz | mMI² | Yes, $`\times \bar{\text{IBI}}_\text{sec}^2 \times 10^6`$ |

Welch and Lomb-Scargle ms² values scale with mean IBI and should be treated with caution when comparing groups or conditions that differ in resting heart rate. CARSPAN mMI² values are dimensionless and largely heart-rate independent.

---

## Installation

### Windows

Download `spectHR-Windows-vX.Y.Z.zip` from the [Releases](https://github.com/markspan/spectHR/releases) page, extract, and run `spectHR.exe`. No Python installation is required.

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
Rompelman, O., Coenen, A.J.R.M., & Kitney, R.I. (1977). Measurement of heart-rate variability: Part 1 — Comparative study of heart-rate variability analysis methods. *Medical and Biological Engineering and Computing*, 15, 233–239. https://doi.org/10.1007/BF02441043

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
