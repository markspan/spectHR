> **⚠️ CAUTION:**
> This project is a work in progress. Blood pressure analysis is not yet implemented. Breathing signal extraction and visualization are functional but should be treated as experimental.

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
    - [XDF (LabStreamingLayer)](#xdf-labstreaminglayer)
    - [Polar .txt](#polar-txt)
    - [CARSPAN .evt / .nff](#carspan-evt--nff)
  - [IBI Classification](#ibi-classification)
  - [Breathing Signal Extraction](#breathing-signal-extraction)
  - [Poincaré Metrics](#poincaré-metrics)
  - [Power Spectral Density — method details](#power-spectral-density--method-details)
    - [Welch's method (default)](#welchs-method-default)
    - [Lomb-Scargle periodogram](#lomb-scargle-periodogram)
    - [Frequency bands](#frequency-bands)
  - [Installation](#installation)
    - [Windows](#windows)
    - [macOS](#macos)
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

When you select a file, spectHR loads the ECG, finds R-peaks automatically, and displays everything in the Preprocessing tab. The **main plot** shows the raw ECG signal in red. Every detected R-peak is marked with a vertical coloured line, and the IBI (in milliseconds) is printed as an arrow between consecutive peaks. A **colour code** immediately tells you which beats look suspicious: normal beats are blue, unexpectedly short beats are magenta, unexpectedly long beats are cyan, and beats far outside any plausible range are orange. At a glance you can see where the algorithm may have made a mistake.

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

Once the peaks look correct, switch to the **IBI Series tab** to see heart rate over time in beats per minute. This gives you an intuitive view of how the participant's heart rate changed across the session — responses to tasks, slow recovery phases, artefact-free periods. If a breathing signal is available it is shown here too as a faint green overlay.

The same navigation bar from the Preprocessing tab is available for zooming and panning.

---

## Step 3 — Define your analysis segments (Epochs tab)

HRV metrics are nearly always computed within named segments of a recording rather than over the entire session. The **Epochs tab** shows a Gantt-style chart with one horizontal bar per epoch.

If your recording was made with a marker stream (e.g. from LabStreamingLayer), epochs named from those markers appear automatically. You can also add epochs manually via **Actions → Add Epoch**, type a name, and a bar spanning the whole recording appears. Then drag either edge of the bar to trim it to the segment you want.

To rename an epoch, click its label on the y-axis. To delete one, rename it to an empty string.

Any change here immediately updates all other tabs — the Poincaré plot, the PSD plots, and the metrics table all recalculate for the new epoch boundaries.

---

## Step 4 — Explore autonomic dynamics (Poincaré tab)

The **Poincaré tab** shows a scatter plot where each point represents one heartbeat: its IBI on the x-axis and the following IBI on the y-axis. This map reveals the *structure* of heart rate variability that a time-series plot conceals.

A healthy autonomic system produces a characteristic elliptical cloud elongated along the diagonal. The short axis of this ellipse (SD1) reflects rapid, beat-to-beat variability driven mainly by the parasympathetic system and by breathing. The long axis (SD2) reflects slower, longer-term variability. The ratio between them describes how autonomic balance shifts across conditions.

Each active epoch is drawn in a different colour with its own SD1/SD2 ellipse overlaid, so you can compare conditions directly. Epoch visibility can be toggled with the checkboxes on the right. Hovering over any point shows the two IBI values and the timestamp, making it easy to trace an outlier back to its location in the raw ECG.

---

## Step 5 — Examine frequency-domain HRV (PSD tab)

The **PSD tab** shows one power spectrum per active epoch, stacked vertically so you can compare epochs at a consistent y-axis scale.

Each plot shows how the total variability in the IBI series is distributed across frequencies. Three frequency bands are shaded in different colours:

- **VLF (Very Low Frequency, ~0.02–0.06 Hz)** — slow fluctuations over minutes, often linked to thermoregulation and hormonal influences. Short recordings may not capture this band reliably.
- **LF (Low Frequency, ~0.06–0.14 Hz)** — fluctuations over roughly 7–25 seconds, reflecting a mix of sympathetic and parasympathetic activity as well as baroreflex function.
- **HF (High Frequency, ~0.14–0.40 Hz)** — fluctuations at breathing rate, driven almost entirely by the parasympathetic system via respiratory sinus arrhythmia. Higher HF power means stronger parasympathetic tone.

The **LF/HF ratio** is often used as an index of sympathovagal balance, though its interpretation is debated — a higher ratio suggests relatively more sympathetic activity.

The shaded grey band around the spectrum is the **confidence interval**: it tells you how much the estimate would vary if you repeated the measurement under the same conditions. A wider band means less certainty — this happens with short recordings. The label in the legend shows the exact confidence level being used (e.g. "95 % CI").

spectHR offers two methods for estimating the power spectrum:

- **Welch's method** resamples the irregularly-spaced IBI series onto a uniform time grid and then applies a standard FFT-based spectral estimator. It is the conventional choice and works well for recordings of five minutes or longer where the resampling introduces negligible distortion.
- **Lomb-Scargle** works directly on the original beat timestamps without any resampling. This matters when recordings are short, when many beats have been removed as artefacts, or when the IBI series is highly irregular — situations where resampling can distort the spectrum. The confidence intervals for Lomb-Scargle scale with the recording length: a longer recording gives a tighter, more reliable estimate.

The active method and the confidence level are set in **WorkSpace → Edit Parameters** and take effect immediately without restarting.

---

## Step 6 — Export your results (Parameters tab)

The **Parameters tab** displays a table with one row per epoch, showing every HRV metric spectHR computes:

- **Time-domain:** beat count, mean IBI, median, minimum, maximum, standard deviation, RMSSD, SDNN, SDSD
- **Poincaré:** SD1, SD2, SD2/SD1 ratio, ellipse area
- **Frequency-domain:** VLF power, LF power, HF power, LF/HF ratio (all in ms²)

Click **Save** to export this table as a CSV file to the output folder configured in your workspace.

---

## Configuring the analysis

All analysis parameters are stored in a JSON workspace file. You can view and edit them at any time through the application menus without touching the file directly.

**WorkSpace → Edit Workspace** lets you change the three folder paths: where spectHR looks for data files, where it stores cached processed files, and where it writes CSV exports.

**WorkSpace → Edit Parameters** opens a panel-based form covering all analysis settings:

*Frequency Analysis* — here you choose the PSD method (Welch or Lomb-Scargle), define the frequency band edges and colours, tune the Welch segment length and overlap or the Lomb-Scargle frequency grid, and set the confidence interval level. Changing any of these and clicking OK immediately updates the PSD plots for the currently loaded file.

*IBI Classification* — these thresholds determine how beats are labelled as normal, short, long, or too long. The rolling window length controls how locally or globally the thresholds adapt to the rhythm. A narrower window adapts quickly to changes in mean heart rate; a wider window gives more stable thresholds that are less affected by a single unusual beat.

*ECG Preprocessing* — the high-pass filter settings used to remove baseline wander from the ECG before peak detection.

All changes are saved back to the workspace file immediately so they persist across sessions.

---

## Data Formats

### XDF (LabStreamingLayer)

spectHR reads `.xdf` files produced by the [LabStreamingLayer](https://github.com/sccn/labstreaminglayer) framework, designed for use with the [Polar H10](https://www.polar.com/en/sensors/h10-heart-rate-sensor) via the [PolarBLE](https://github.com/markspan/PolarBLE) companion application.

It identifies streams automatically: ECG by stream type `ECG`, accelerometer by stream type `ACCELEROMETER`, and markers by stream type containing `marker` or `event`.

Epoch markers follow the convention `start <label>` / `stop <label>` or `end <label>`. If a stop marker is missing the epoch runs to the end of the recording. When two Polar H10 units are recorded simultaneously their data appears as separate band nodes in the file tree.

### Polar .txt

The plain-text RR-interval export format from the Polar app. Refer to the example file in `ExampleData/`.

### CARSPAN .evt / .nff

CARSPAN event files are supported. If an `.nff` file with the same base name is present spectHR loads the `ECG` channel from it.

---

## IBI Classification

After detection, each inter-beat interval is classified automatically using a centered rolling window that computes a local mean and standard deviation. Beats are coloured in the ECG plot according to their label:

| Label | Meaning | Colour |
|-------|---------|--------|
| N | Normal — within the expected range | Blue |
| S | Short — below the lower threshold | Magenta |
| L | Long — above the upper threshold | Cyan |
| TL | Too Long — exceeds the absolute ceiling | Orange |
| SL | Short followed immediately by Long | Turquoise |
| SNS | Short-Normal-Short pattern | Light sea green |
| T | Degenerate (NaN or zero duration) | — |

The thresholds are set relative to the rolling mean ± n standard deviations, making them adaptive to slow drifts in heart rate. The window length, the number of standard deviations, and the absolute TL ceiling can all be adjusted in **Edit Parameters**.

---

## Breathing Signal Extraction

When a Polar H10 accelerometer stream is present, spectHR derives a respiration surrogate from the 3-axis chest-belt movement data. The chest wall expands and contracts with each breath, producing a characteristic low-frequency oscillation in the accelerometer signal. spectHR isolates this by removing the gravity component, bandpassing to the respiratory frequency range (0.10–0.70 Hz), and applying PCA to extract the dominant axis of motion as a single 1-D breathing signal.

The result is z-score normalised and overlaid in green on the ECG and heart rate plots. Inhalation phases are shaded in light blue. Having the breathing trace visible alongside the ECG and IBI series helps you understand which HF power peaks correspond to breathing and whether any anomalies in the IBI series are coupled to the breathing cycle.

---

## Poincaré Metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| SD1 | $\sqrt{\frac{1}{2}\text{Var}(\text{IBI}_{i+1} - \text{IBI}_i)}$ | Short-term, beat-to-beat variability. Closely related to RMSSD and parasympathetic activity. |
| SD2 | $\sqrt{2\,\text{Var}(\text{IBI}_i) - \frac{1}{2}\text{Var}(\text{IBI}_{i+1} - \text{IBI}_i)}$ | Longer-term variability. Related to SDNN and overall autonomic modulation. |
| SD2/SD1 | — | Autonomic balance index. Values above 1 indicate relatively more long-term than short-term variability. |
| Ellipse area | $\pi \cdot \text{SD1} \cdot \text{SD2}$ | Total HRV. Larger ellipse = more variability overall. |

Note: SD1 and SD2 are mathematically related to RMSSD and SDNN and therefore do not add independent information [(van Roon et al., 2025)](https://www.mdpi.com/1099-4300/27/8/861), but the Poincaré plot provides a useful visual summary of the data structure.

---

## Power Spectral Density — method details

### Welch's method (default)

The IBI series is resampled onto a uniform 4 Hz grid using linear interpolation, then divided into overlapping segments. Each segment is windowed and Fourier-transformed; the results are averaged to produce the final power estimate. Averaging over segments reduces variance at the cost of frequency resolution — more segments gives a smoother, more reliable estimate, which is why short recordings produce noisier spectra.

Default parameters (editable in **Edit Parameters**):

| Parameter | Default |
|-----------|---------|
| Resampling frequency | 4 Hz |
| Segment length | 256 samples |
| Overlap | 128 samples |
| Window | Hamming |

### Lomb-Scargle periodogram

The Lomb-Scargle method evaluates the spectrum directly at the original, irregularly-spaced beat timestamps. This avoids the interpolation step that can distort Welch estimates when many beats have been removed or when the heart rate is changing rapidly. The mean IBI is subtracted before estimation to prevent the large DC value from leaking power into the HRV bands.

The confidence interval width scales with recording duration: for a 5-minute recording the CI is already quite tight; for shorter recordings it widens, correctly reflecting that less data means less certainty.

### Frequency bands

Both methods share the same configurable band definitions. The defaults match common HRV conventions but can be adjusted to suit your paradigm (e.g. if your participants breathe slowly, HF extends to lower frequencies):

| Band | Default range | Reflects |
|------|--------------|---------|
| VLF | 0.02–0.06 Hz | Slow regulatory processes; requires long recordings |
| LF | 0.06–0.14 Hz | Baroreceptor reflex, mixed sympathetic/parasympathetic |
| HF | 0.14–0.40 Hz | Respiratory sinus arrhythmia, parasympathetic tone |

---

## Installation

### Windows

Download `spectHR-Windows-vX.Y.Z.zip` from the [Releases](https://github.com/markspan/spectHR/releases) page, extract, and run `spectHR.exe`. No Python installation is required.

### macOS

Download `spectHR-macOS-vX.Y.Z.zip` from the [Releases](https://github.com/markspan/spectHR/releases) page and extract `spectHR.app`. Drag it to `/Applications`.

Because the app is not signed by Apple, macOS will block it the first time. Right-click `spectHR.app` in Finder, choose **Open**, and click **Open** in the dialog. After this first launch it will open normally. Alternatively, in **System Settings → Privacy & Security** click **Open Anyway**, or run `xattr -dr com.apple.quarantine /Applications/spectHR.app` in a Terminal.

---

## Contributing

spectHR is written in pure Python. The analysis library (`src/spectHR/`) and the GUI (`src/spectUI/`) are kept separate so the library can be used independently in scripts.

New HRV metrics can be added by decorating a method with `@hrv_metric` in `CardioSeries` — it will appear in the Parameters table and CSV automatically. New file formats can be added by registering a loader function with `@register_loader(".ext")` in `src/spectHR/DataSet/loaders/`.

Fork the repository and open a pull request with a clear description of the change.

---

## License

spectHR is released under the GNU LGPL-2.1 license. See the [LICENSE](LICENSE) file for details.