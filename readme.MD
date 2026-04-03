> **⚠️ CAUTION:** This project is a work in progress. Blood pressure analysis is not yet implemented. Breathing signal extraction and visualisation are functional but should be treated as experimental.

---

- [spectHR: An Interactive HRV Analysis Tool](#specthr-an-interactive-hrv-analysis-tool)
- [What is spectHR?](#what-is-specthr)
- [Getting started](#getting-started)
- [The interface at a glance](#the-interface-at-a-glance)
- [Step 1 — Check and clean the ECG (Preprocessing tab)](#step-1--check-and-clean-the-ecg-preprocessing-tab)
- [Step 2 — Inspect the heart rate series (IBI Series tab)](#step-2--inspect-the-heart-rate-series-ibi-series-tab)
- [Step 3 — Define your analysis segments (Epochs tab)](#step-3--define-your-analysis-segments-epochs-tab)
- [Step 4 — Explore autonomic dynamics (Poincaré tab)](#step-4--explore-autonomic-dynamics-poincaré-tab)
- [Step 5 — Examine frequency-domain HRV (PSD tab)](#step-5--examine-frequency-domain-hrv-psd-tab)
- [Step 6 — Export your results (Parameters tab)](#step-6--export-your-results-parameters-tab)
- [Configuring the analysis](#configuring-the-analysis)
- [Data Formats](#data-formats)
- [IBI Classification](#ibi-classification)
- [Breathing Signal Extraction](#breathing-signal-extraction)
- [Poincaré Metrics](#poincaré-metrics)
- [Power Spectral Density — method details](#power-spectral-density--method-details)
- [Installation](#installation)
- [Contributing](#contributing)
- [License](#license)

---

# spectHR: An Interactive HRV Analysis Tool

## What is spectHR?

![spectHR](images/MainWindow.PNG)

**spectHR** is a free, open-source desktop application for Heart Rate Variability (HRV) analysis. It is built for researchers and students who want to move from a raw ECG recording to interpretable HRV metrics without writing any code — and without trusting a black box.

Heart rate variability reflects the beat-to-beat fluctuations in the time between heartbeats. These fluctuations are regulated by the autonomic nervous system: higher HRV generally indicates flexible, healthy regulation; lower HRV is associated with stress, disease, or fatigue. By analysing the power in different frequency bands of the IBI series, spectHR lets you separate the parasympathetic (HF) and sympathetic/parasympathetic (LF) contributions to heart rate control in each named epoch of your recording.

The key principle behind spectHR is that **you remain in control of data quality**. Every step that could go wrong — R-peak detection, noisy intervals, epoch boundaries — is shown to you visually and can be corrected before any metrics are computed.

---

## Getting started

1. Launch the application. On first run it creates a default workspace pointing to your Documents folder.
2. Open **WorkSpace → Edit Workspace** to point spectHR at the folder where your data files live.
3. Your files appear in the tree on the left. Click one to load it.
4. Work through the tabs from left to right: clean the ECG, define your epochs, then read the results.

---

## The interface at a glance

The window is divided into two areas. On the left is a narrow **file tree** listing all datasets in your configured data folder. On the right is the main **analysis area**, organised into six tabs that take you from raw data to publishable metrics:

| Tab | What you do there |
|-----|------------------|
| **Preprocessing** | Verify and correct R-peak detection |
| **IBI Series** | Review the heart rate time course |
| **Poincaré** | Explore beat-to-beat dynamics visually |
| **Epochs** | Draw and adjust your analysis segments |
| **PSD** | Read the frequency-domain power spectrum per epoch |
| **Parameters** | See all HRV metrics in a table and export to CSV |

---

## Step 1 — Check and clean the ECG (Preprocessing tab)

This is the most important step. The quality of every metric downstream depends entirely on whether the R-peaks have been detected correctly.

When you select a file, spectHR loads the ECG, finds R-peaks automatically, and displays everything in the Preprocessing tab. The **main plot** shows the raw ECG signal in red. Every detected R-peak is marked with a vertical coloured line, and the IBI (in milliseconds) is printed as an arrow between consecutive peaks. A **colour code** immediately tells you which beats look suspicious: normal beats are blue, unexpectedly short beats are magenta, unexpectedly long beats are cyan, and beats far outside any plausible range are orange.

If a breathing signal is available from the device's accelerometer, it appears as a **green curve** overlaid on the ECG. Light-blue shading marks inhalation phases, giving you a direct view of how breathing patterns relate to heart rate.

Below the main ECG is a **thumbnail strip** showing the entire recording at once. A shaded rectangle marks what the main plot is currently showing. Drag it left or right to navigate.

Along the bottom is a **navigation bar**:
- The outer arrows jump to the very start or end of the recording.
- The double arrows pan left or right by one screen width.
- The single arrows jump directly to the **next or previous abnormal beat** — a quick way to review every flagged interval without scrolling manually.
- The magnifier buttons zoom in and out.

When you spot a problem, use the **mode selector** at the top of the plot:
- **Drag** — click and drag a peak line to shift it to its correct position.
- **Add** — click anywhere on the ECG to insert a missing peak.
- **Remove** — click a peak line to delete a spurious detection.

All changes are saved automatically to the cache file when you leave the tab.

> **Tip:** Right-clicking a file in the tree gives you three extra options: *Reload Raw* discards all your edits and starts fresh from the original file; *Invert ECG Polarity* flips the signal vertically and re-runs peak detection, useful if the device was worn upside-down; *Retrigger ECG* re-runs the detector on the current signal without reloading.

---

## Step 2 — Inspect the heart rate series (IBI Series tab)

Once the peaks look correct, switch to the **IBI Series tab** to see heart rate over time in beats per minute. This gives you an intuitive view of how the participant's heart rate changed across the session — responses to tasks, slow recovery phases, artefact-free periods. If a breathing signal is available it is shown here too as a faint green overlay. The same navigation bar from the Preprocessing tab is available for zooming and panning.

---

## Step 3 — Define your analysis segments (Epochs tab)

HRV metrics are nearly always computed within named segments of a recording rather than over the entire session. The **Epochs tab** shows a Gantt-style chart with one horizontal bar per epoch.

If your recording was made with a marker stream (e.g. from LabStreamingLayer), epochs named from those markers appear automatically. You can also add epochs manually via **Actions → Add Epoch**, type a name, and a bar spanning the whole recording appears. Then drag either edge of the bar to trim it to the segment you want. To rename an epoch, click its label on the y-axis. To delete one, rename it to an empty string.

Any change here immediately updates all other tabs — the Poincaré plot, the PSD plots, and the metrics table all recalculate for the new epoch boundaries.

---

## Step 4 — Explore autonomic dynamics (Poincaré tab)

The **Poincaré tab** shows a scatter plot where each point represents one heartbeat: its IBI on the x-axis and the following IBI on the y-axis. This map reveals the *structure* of heart rate variability that a time-series plot conceals. A healthy autonomic system produces a characteristic elliptical cloud elongated along the diagonal.

The short axis of this ellipse (SD1) reflects rapid, beat-to-beat variability driven mainly by the parasympathetic system and by breathing. The long axis (SD2) reflects slower, longer-term variability. The ratio between them is often interpreted as an index of autonomic balance.

Each active epoch is drawn in a different colour with its own SD1/SD2 ellipse overlaid, so you can compare conditions directly. Epoch visibility can be toggled with the checkboxes on the right. Hovering over any point shows the two IBI values and the timestamp, making it easy to trace an outlier back to its location in the raw ECG.

> **A note on SD1 and SD2:** Although these parameters are widely reported, it is important to be aware that SD1 and SD2 carry no statistical information beyond what is already present in RMSSD and SDNN respectively. SD1 equals RMSSD / √2 by definition, and SD2 is fully determined by SDNN and RMSSD through a fixed algebraic identity. Van Roon et al. (2025) provide a comprehensive mathematical overview and conclude that all Poincaré ellipse parameters are redundant with established time-domain measures. spectHR reports them because they are widely expected in the literature and because the Poincaré plot itself remains a useful **visual** summary of data structure — but users are encouraged not to treat SD1 and SD2 as independent metrics in statistical analyses that already include RMSSD and SDNN.
>
> *Reference:* van Roon, A.M., Mulder, L.J.M., Althaus, M., & Mulder, G. (2025). Overview of mathematical relations between Poincaré plot measures and time and frequency domain measures of heart rate variability. *Entropy*, 27(8), 861. https://doi.org/10.3390/e27080861

---

## Step 5 — Examine frequency-domain HRV (PSD tab)

The **PSD tab** shows one power spectrum per active epoch, stacked vertically so you can compare epochs at a consistent y-axis scale. Each plot shows how the total variability in the IBI series is distributed across frequencies. Three frequency bands are shaded in different colours:

- **VLF (Very Low Frequency, ~0.02–0.06 Hz)** — slow fluctuations over minutes, often linked to thermoregulation and hormonal influences. Short recordings may not capture this band reliably.
- **LF (Low Frequency, ~0.06–0.14 Hz)** — fluctuations over roughly 7–25 seconds, reflecting a mix of sympathetic and parasympathetic activity as well as baroreflex function.
- **HF (High Frequency, ~0.14–0.40 Hz)** — fluctuations at breathing rate, driven almost entirely by the parasympathetic system via respiratory sinus arrhythmia. Higher HF power means stronger parasympathetic tone.

The **LF/HF ratio** is often used as an index of sympathovagal balance, though its interpretation is debated — a higher ratio suggests relatively more sympathetic activity.

The shaded grey band around the spectrum is the **confidence interval**: it tells you how much the estimate would vary if you repeated the measurement under the same conditions. A wider band means less certainty — this happens with short recordings. The label in the legend shows the exact confidence level (e.g. "95 % CI").

spectHR offers three methods for estimating the power spectrum, selectable in **WorkSpace → Edit Parameters**:

- **Welch's method** resamples the irregularly-spaced IBI series onto a uniform time grid and then applies a standard FFT-based spectral estimator. It is the conventional choice and works well for recordings of five minutes or longer.
- **Lomb-Scargle** works directly on the original beat timestamps without any resampling. This matters when recordings are short, when many beats have been removed as artefacts, or when the IBI series is highly irregular.
- **CARSPAN** implements a direct Discrete Fourier Transform on the R-peak event times, following the approach described by Mulder (1988) and used in the CARSPAN software package. Band-power values are expressed in milli-Modulation-Index squared (mMI²), directly comparable to CARSPAN output.

The active method and the confidence level take effect immediately without restarting.

---

## Step 6 — Export your results (Parameters tab)

The **Parameters tab** displays a table with one row per epoch, showing every HRV metric spectHR computes:

- **Time-domain:** beat count, mean IBI, median, minimum, maximum, standard deviation, RMSSD, SDNN, SDSD
- **Poincaré:** SD1, SD2, SD2/SD1 ratio, ellipse area
- **Frequency-domain:** VLF power, LF power, HF power, LF/HF ratio
  - Units are **ms²** when using Welch or Lomb-Scargle
  - Units are **mMI²** when using the CARSPAN method

Click **Save** to export this table as a CSV file to the output folder configured in your workspace.

---

## Configuring the analysis

All analysis parameters are stored in a JSON workspace file. You can view and edit them at any time through the application menus without touching the file directly.

**WorkSpace → Edit Workspace** lets you change the three folder paths: where spectHR looks for data files, where it stores cached processed files, and where it writes CSV exports.

**WorkSpace → Edit Parameters** opens a panel-based form covering all analysis settings:

*Frequency Analysis* — choose the PSD method (Welch, Lomb-Scargle, or CARSPAN), define the frequency band edges and colours, tune the method-specific parameters, and set the confidence interval level. Changing any of these and clicking OK immediately updates the PSD plots for the currently loaded file.

*IBI Classification* — these thresholds determine how beats are labelled as normal, short, long, or too long. The rolling window length controls how locally or globally the thresholds adapt to the rhythm. The number of standard deviations and the absolute TL ceiling can also be adjusted.

*ECG Preprocessing* — the high-pass filter settings used to remove baseline wander from the ECG before peak detection.

All changes are saved back to the workspace file immediately so they persist across sessions.

---

## Data Formats

### XDF (LabStreamingLayer)

spectHR reads `.xdf` files produced by the [LabStreamingLayer](https://github.com/sccn/labstreaminglayer) framework, designed for use with the [Polar H10](https://www.polar.com/en/sensors/h10-heart-rate-sensor) via the [PolarBLE](https://github.com/markspan/PolarBLE) companion application. It identifies streams automatically: ECG by stream type `ECG`, accelerometer by stream type `ACCELEROMETER`, and markers by stream type containing `marker` or `event`. Epoch markers follow the convention `start <label>` / `stop <label>` or `end <label>`. If a stop marker is missing the epoch runs to the end of the recording. When two Polar H10 units are recorded simultaneously their data appears as separate band nodes in the file tree.

### Polar .txt

The plain-text RR-interval export format from the Polar app. Refer to the example file in `ExampleData/`.

### CARSPAN .evt / .nff

CARSPAN event files are supported. If an `.nff` file with the same base name is present spectHR loads the `ECG` channel from it.

---

## IBI Classification

After R-peak detection, each inter-beat interval is classified automatically before any metrics are computed. Beats are coloured in the ECG plot according to their label:

| Label | Meaning | Colour |
|-------|---------|--------|
| N | Normal — within the expected range | Blue |
| S | Short — below the lower threshold | Magenta |
| L | Long — above the upper threshold | Cyan |
| TL | Too Long — exceeds the absolute ceiling | Orange |
| SL | Short followed immediately by Long | Turquoise |
| SNS | Short-Normal-Short pattern | Light sea green |
| T | Degenerate (NaN or zero duration) | — |

### How classification works in spectHR

Classification is performed by a centred rolling window that computes a local mean and standard deviation over the surrounding beats. An interval is flagged as short or long when it falls outside `mean ± n_std × std`. Intervals above an absolute ceiling T_max are always flagged as TL, regardless of the local statistics, and are excluded from all subsequent metric calculations.

> **Classification algorithm**
>
> Let IBI_i denote the *i*-th inter-beat interval and let IBI&#772; and σ denote the local mean and standard deviation computed over a centred window of *W* beats. Classification proceeds as follows:
>
> | Condition | Label |
> |-----------|-------|
> | IBI_i > T_max | TL — excluded from all metrics |
> | IBI_i ≤ 0 or NaN | T — degenerate, excluded |
> | IBI_i > IBI&#772; + N · σ | L — long interval |
> | IBI_i < IBI&#772; − N · σ | S — short interval |
> | label_i = S and label_{i+1} = L | SL — short-long pair |
> | label_i = S, label_{i+1} = N, label_{i+2} = S | SNS — short-normal-short triplet |
> | otherwise | N — normal |
>
> Default parameters: *W* = 51 beats, *N* = 4.0, T_max = 2.0 s. All three are configurable in **Edit Parameters**.

### Comparison with CARSPAN

Users familiar with CARSPAN will notice several differences in the classification approach. These are deliberate design choices, each with a specific rationale.

#### 1. Refractory period: implemented at detection, not classification

CARSPAN enforces a hardware refractory period T_refr = 300 ms at the classification stage, rejecting any interval shorter than this as a spurious trigger. spectHR implements the equivalent constraint earlier in the pipeline, as a minimum peak-distance parameter passed directly to the R-peak detector. Any two candidate peaks closer than 300 ms simply cannot both be detected.

This approach is preferable because it prevents the false detection from entering the data in the first place, rather than flagging it after the fact. The practical effect on the classified IBI series is identical.

#### 2. Window type: centred rather than causal

CARSPAN computes its running statistics over a **causal** (backward-looking) window of T_w = 60 seconds, using only beats that have already been observed. spectHR uses a **centred** window of fixed length (default 51 beats), incorporating beats both before and after the current interval.

The centred window produces more stable thresholds around transient events such as task onsets. A causal window adapts its threshold only *after* a heart rate change has occurred, which can cause the first few beats of a new condition to be incorrectly flagged. In psychophysiological research — the primary application of both CARSPAN and spectHR — this matters, because condition boundaries are precisely where accurate classification is most important.

#### 3. Window unit: beats rather than seconds

CARSPAN's window is defined in seconds (T_w); spectHR's window is defined in beats (*W*). For a resting heart rate of approximately 70 bpm, 51 beats corresponds to roughly 44 seconds, close to CARSPAN's default of 60 seconds. The beat-based definition ensures that the window always contains the same number of statistical observations regardless of heart rate, giving equal estimation quality at rest and during exercise.

#### 4. Successive difference criterion: not implemented

CARSPAN applies a second, independent criterion: an interval is also flagged if the *difference* between consecutive intervals (IBI_i − IBI_{i−1}) exceeds N_SuD standard deviations of the successive difference series. This catches abrupt transitions that remain within the absolute amplitude boundaries.

spectHR does not implement this criterion. The SL and SNS sequence labels already capture the most physiologically relevant abrupt patterns — a short interval immediately followed by a long one (typical of an ectopic beat) and a short-normal-short triplet. Adding a separate successive-difference threshold would introduce a second set of parameters to tune and could conflict with the sequence-based labels in ambiguous cases. Users working with data that contains subtle gradual-onset artefacts may wish to apply additional pre-processing before loading their files into spectHR.

#### 5. Min/Max SD clipping: not implemented

CARSPAN clips the standard deviation used for thresholding to a minimum of 5 % and a maximum of 15 % of the local mean IBI. This prevents detection boundaries from becoming unrealistically narrow in very regular rhythms or unrealistically wide in very irregular ones.

spectHR relies instead on the user's choice of `n_std` and `T_max`. The absolute ceiling `T_max` guards against the upper extreme; the minimum peak distance in the detector (300 ms) provides a hard lower floor. If your participant has an unusually regular or irregular rhythm, adjusting `n_std` in **Edit Parameters** achieves a similar effect to CARSPAN's SD clipping.

#### 6. Automatic interpolation: not implemented

CARSPAN automatically corrects detected artefacts by linear interpolation, inserting one or more estimated beats to fill a gap, and adds a small amount of normally-distributed noise to prevent excessive variance reduction.

spectHR does not perform automatic correction. Instead, every flagged beat is shown to you in the Preprocessing tab and can be corrected manually using the Drag, Add, and Remove tools. This is a deliberate choice: automatic interpolation, however carefully designed, introduces synthetic data into the IBI series. In spectHR the principle is that you — not the algorithm — decide what to do with each artefact. Intervals that are left uncorrected and flagged as TL or T are excluded from all metric calculations.

---

## Breathing Signal Extraction

When a Polar H10 accelerometer stream is present, spectHR derives a respiration surrogate from the 3-axis chest-belt movement data. The chest wall expands and contracts with each breath, producing a characteristic low-frequency oscillation in the accelerometer signal. spectHR isolates this by removing the gravity component, bandpassing to the respiratory frequency range (0.10–0.70 Hz), and applying PCA to extract the dominant axis of motion as a single 1-D breathing signal. The result is z-score normalised and overlaid in green on the ECG and heart rate plots. Inhalation phases are shaded in light blue.

Having the breathing trace visible alongside the ECG and IBI series helps you understand which HF power peaks correspond to breathing and whether any anomalies in the IBI series are coupled to the breathing cycle.

---

## Poincaré Metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| SD1 | sqrt(Var(IBI_{i+1} − IBI_i) / 2) | Short-term variability. Equal to RMSSD / √2. |
| SD2 | sqrt(2·Var(IBI_i) − Var(IBI_{i+1} − IBI_i) / 2) | Longer-term variability. Algebraically related to SDNN and RMSSD. |
| SD2/SD1 | — | Autonomic balance index. Values above 1 indicate relatively more long-term than short-term variability. |
| Ellipse area | π · SD1 · SD2 | Total HRV. Larger ellipse = more variability overall. |

> **Important:** SD1 and SD2 are mathematically fully determined by RMSSD and SDNN and therefore carry no additional statistical information. Van Roon et al. (2025) demonstrate this rigorously, showing that all Poincaré ellipse parameters can be derived from standard time-domain measures without loss. spectHR reports SD1 and SD2 because they are widely expected in the literature and because the Poincaré plot itself remains a valuable visual tool, but users should be aware that including SD1 and SD2 alongside RMSSD and SDNN in a statistical model introduces redundancy.
>
> *Reference:* van Roon, A.M., Mulder, L.J.M., Althaus, M., & Mulder, G. (2025). Overview of mathematical relations between Poincaré plot measures and time and frequency domain measures of heart rate variability. *Entropy*, 27(8), 861. https://doi.org/10.3390/e27080861

---

## Power Spectral Density — method details

### Welch's method

The IBI series is resampled onto a uniform 4 Hz grid using linear interpolation, then divided into overlapping segments. Each segment is windowed and Fourier-transformed; the results are averaged to produce the final power estimate. Averaging over segments reduces variance at the cost of frequency resolution — more segments gives a smoother estimate, which is why short recordings produce noisier spectra. Output units: **ms²/Hz**; band power in **ms²**.

Default parameters (editable in **Edit Parameters**):

| Parameter | Default |
|-----------|---------|
| Resampling frequency | 4 Hz |
| Segment length | 256 samples |
| Overlap | 128 samples |
| Window | Hamming |

> **Technical detail — Welch estimation**
>
> Let x(t) denote the IBI series (ms) resampled at rate f_s. spectHR calls `scipy.signal.welch` with `scaling='density'`, which returns the one-sided power spectral density in ms²/Hz. Band power B in [f_l, f_h] is obtained by trapezoidal integration. Confidence intervals are chi-square based: for *K* non-overlapping segments the degrees of freedom are ν = 2K, giving:
>
>     CI: [ν·Ŝ(f) / χ²_{1−α/2,ν} , ν·Ŝ(f) / χ²_{α/2,ν}]

### Lomb-Scargle periodogram

The Lomb-Scargle method evaluates the spectrum directly at the original, irregularly-spaced beat timestamps. This avoids the interpolation step that can distort Welch estimates when many beats have been removed or when heart rate is changing rapidly. The mean IBI is subtracted before estimation to suppress the DC component. Confidence interval width scales with recording duration. Output units: **ms²/Hz**; band power in **ms²**.

> **Technical detail — Lomb-Scargle estimation**
>
> Let t_i denote the R-peak times (s) and x_i = IBI_i − IBI&#772; (ms) the mean-subtracted intervals. The periodogram P(ω) is computed by `scipy.signal.lombscargle` with `normalize=False` and scaled to a power density:
>
>     S(f_k) = (2T / N²) · P(ω_k)
>
> where T = t_N − t_1 and N is the number of beats. Confidence intervals use effective degrees of freedom ν = 2 · round(2·(f_max − f_min)·T).

### CARSPAN method

The CARSPAN method implements the direct Discrete Fourier Transform on R-peak event times, following the algorithm described by Mulder (1988) and used in the CARSPAN software package. It requires no resampling. Because spectral resolution is 1/T Hz — determined entirely by the recording duration T — spectra from recordings of different lengths are interpolated onto a fixed output grid of 0.01 Hz before display, ensuring visual comparability across conditions and subjects. Output units: **mMI²/Hz**; band power in **mMI²**.

> **Technical detail — CARSPAN direct DFT**
>
> The R-peak event series is represented as a series of unit impulses at the R-peak occurrence times t_i (Rompelman, 1975; Mulder, 1988):
>
>     x(t) = Σ δ(t − t_i)
>
> The power spectral density at discrete frequencies f_k = k/T (k = 1, 2, …) is (CARSPAN manual, formula 3.19):
>
>     S_xx(f_k) = (2/T) · |Σ_i w_i · exp(−2πj·f_k·t_i)|²
>              = (2/T) · [(Σ_i w_i·cos(2π·f_k·t_i))² + (Σ_i w_i·sin(2π·f_k·t_i))²]
>
> where w_i is the i-th coefficient of a tapering window applied to suppress spectral leakage (default: Hanning, as used in CARSPAN; configurable in **Edit Parameters**).
>
> **Normalisation to mMI²** (CARSPAN manual, formulae 3.20 and 3.29)
>
> The raw spectrum is in units of events²/Hz. To make it dimensionless and independent of mean heart rate, it is normalised by the squared mean of the R-peak event series. The mean of the unit-impulse event series equals the mean heart rate: x&#772; = 1 / IBI&#772;_sec. Band power B′ in [f_l, f_h] is then:
>
>     B′ = (Σ_{f_k=f_l}^{f_h} S_xx(f_k) · Δf) / x&#772;²  ×  10⁶
>        = (Σ_{f_k=f_l}^{f_h} S_xx(f_k) · Δf) × IBI&#772;_sec²  ×  10⁶    [mMI²]
>
> Multiplication by 10⁶ scales the result into a convenient numeric range (milli-Modulation-Index squared, mMI²), consistent with CARSPAN output convention. An important practical consequence of this normalisation is that mMI² values are largely independent of mean heart rate, making them directly comparable between subjects and sessions without further correction (De Boer et al., 1985; Van Dellen et al., 1985).
>
> **Note on terminology:** The CARSPAN documentation occasionally uses the term *Energy* in band descriptions where *Power* is the physically correct term. spectHR consistently uses *Power* throughout.

### Frequency bands

All three methods share the same configurable band definitions:

| Band | Default range | Reflects |
|------|--------------|---------|
| VLF | 0.02–0.06 Hz | Slow regulatory processes; requires long recordings |
| LF | 0.06–0.14 Hz | Baroreceptor reflex, mixed sympathetic/parasympathetic |
| HF | 0.14–0.40 Hz | Respiratory sinus arrhythmia, parasympathetic tone |

Band edges can be adjusted in **Edit Parameters** to suit your paradigm (e.g. if your participants breathe slowly, the HF band may need to extend to lower frequencies).

### Units and normalisation

| Method | PSD unit | Band power unit | Normalised? |
|--------|----------|-----------------|-------------|
| Welch | ms²/Hz | ms² | No |
| Lomb-Scargle | ms²/Hz | ms² | No |
| CARSPAN | mMI²/Hz | mMI² | Yes — by mean HR² × 10⁶ |

Welch and Lomb-Scargle ms² values scale with mean IBI and should be treated with caution when comparing groups or conditions that differ in resting heart rate.

---

## Installation

### Windows

Download `spectHR-Windows-vX.Y.Z.zip` from the [Releases](https://github.com/markspan/spectHR/releases) page, extract, and run `spectHR.exe`. No Python installation is required.

### macOS

Download `spectHR-macOS-vX.Y.Z.zip` from the [Releases](https://github.com/markspan/spectHR/releases) page and extract `spectHR.app`. Drag it to `/Applications`. Because the app is not signed by Apple, macOS will block it the first time. Right-click `spectHR.app` in Finder, choose **Open**, and click **Open** in the dialog. After this first launch it will open normally. Alternatively, in **System Settings → Privacy & Security** click **Open Anyway**, or run `xattr -dr com.apple.quarantine /Applications/spectHR.app` in a Terminal.

---

## Contributing

spectHR is written in pure Python. The analysis library (`src/spectHR/`) and the GUI (`src/spectUI/`) are kept separate so the library can be used independently in scripts.

New HRV metrics can be added by decorating a method with `@hrv_metric` in `CardioSeries` — it will appear in the Parameters table and CSV automatically.

New file formats can be added by registering a loader function with `@register_loader(".ext")` in `src/spectHR/DataSet/loaders/`.

Fork the repository and open a pull request with a clear description of the change.

---

## License

spectHR is released under the GNU LGPL-2.1 license. See the [LICENSE](LICENSE) file for details.