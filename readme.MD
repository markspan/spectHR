# ⚠️ CAUTION:

> **This project is a work in progress. It is not yet suitable for data analysis. Breathing and blood pressure data are untested or not yet implemented.**

# spectHR: An Interactive Heart Rate Variability (HRV) Analysis Tool

## Overview

**spectHR** is an interactive graphical tool for analyzing heart rate variability (HRV) data. It features a Qt-based GUI with multiple analysis tabs, allowing users to preprocess, visualize, and explore HRV datasets intuitively.

This documentation serves as a foundation for developers and researchers who wish to extend or contribute to the project.

## Features

### 1. PreProcessing Tab

* Interactive tools for inspecting and cleaning inter-beat interval (IBI) data.
* GUI-based operations to manipulate and review the dataset.

### 2. IBI Series View

* Plots inter-beat intervals (IBIs) as a time series.
* Useful for spotting trends, outliers, and potential artifacts.
* Supports zooming and interactive inspection.
* Displays epoch labels and classification markers when available.

### 3. Poincare Tab

* Generates Poincaré plots to assess nonlinear heart rate dynamics.
* Highlights relationships between successive IBIs.

### 4. Descriptives Tab

* Computes descriptive statistics by epoch, including:

  * Mean, SDNN, RMSSD
  * SD1, SD2, and more
* Integrates spectral features when available.

### 5. PSD Tab

* Calculates power spectral density (PSD) using Welch's method.
* Presents frequency-domain metrics grouped by epochs.

### 6. Epochs Tab

* Displays HRV epochs in a Gantt chart format.
* Provides an intuitive overview of time-segmented analysis.

## How It Works

### Inputs

* **Dataset**: Requires time-series HRV data (e.g., IBIs and epoch labels). Data must support operations defined in the `spectHR` library.

### Workflow

1. **Launch the Application**
2. **Navigate Tabs**: Move through tabs to explore different analyses.

   * Preprocessing
   * Visualization (Poincaré, Epochs)
   * Statistical analysis (Descriptives, PSD)
3. **Live Interactions**: Edits and analysis update visualizations and summaries in real time.
4. **Data Saving**: Modified datasets and computed results are saved automatically.

### Outputs

* Visual and numerical summaries of HRV data.
* Annotated and cleaned datasets for further analysis.

## Audience

* Researchers, clinicians, and students working with HRV data who need a robust, GUI-driven workflow.

---

# spectHR Python Library: Cardiovascular Spectral Analysis Toolkit

`spectHR` is a Python library that powers the GUI application and can also be used independently. It supports analysis of ECG signals and related metrics.

## Key Features

* **XDF File Support**: Reads LabStreamingLayer `.xdf` files.

  * Detects ECG streams with labels like "polar" (e.g., Polar H10).
  * Reads marker streams with `start label` / `end label` patterns for epoching.

* **Text and EVT File Support**:

  * Loads `.txt` files from Polar apps.
  * Supports `.evt` and `.nff` files from CARSPAN (loads ECG channel).

* **ECG Peak Detection**:

  * Detects R-top peaks in ECG data.

* **Interactive Plotting**:

  * Visualize and adjust R-top locations.
  * Tools for zooming and epoch selection.

* **Spectral Analysis**:

  * Analyze HRV and respiratory metrics using PSD.

## Breathing Signal Estimation

From raw 3-axis accelerometer data (e.g., Polar H10), the library estimates a breathing signal using the following steps:

1. **Gravity Removal**: Apply a 0.04 Hz low-pass Butterworth filter to each axis to isolate and subtract gravity.
2. **Dynamic Acceleration Norm**: Compute the norm of the detrended vector.
3. **Respiratory Filtering**: Filter the norm with a 0.5 Hz low-pass filter to extract the breathing-related component.

### Assumptions

* Sampling rate: 200 Hz
* Input shape: `(N, 3)` for `[X, Y, Z]`
* Device worn on torso in a stable position

## Requirements

* Python 3.7+
* **Note**: The standalone executable works only on Windows.

---

## Inter-Beat Interval (IBI) Classification

The function `calcPeaks()` analyzes and classifies IBIs based on temporal thresholds and patterns.

```python
DataSet = cs.calcPeaks(DataSet)
```

### Labels

* **N**: Normal (within dynamic threshold)
* **S**: Short (below threshold)
* **L**: Long (above threshold)
* **TL**: Too Long (exceeds Tmax)
* **SL**: Short followed by Long
* **SNS**: Short-Normal-Short sequence

### Method

* A moving average and standard deviation are computed using a sliding window (Tw).
* Dynamic thresholds:

```
(lower, upper) = mean_IBI ± Nsd * std_IBI
```

* The algorithm then:

  * Classifies IBIs individually
  * Detects multi-interval patterns

### Parameters

* **Tw (Window Size)**: Controls smoothing of thresholds.

  * Default: 51 beats

* **Nsd (Standard Deviation Multiplier)**:

  * Controls sensitivity of dynamic range
  * Default: 4

* **Tmax**: Absolute upper bound for IBI duration (in seconds)

  * Default: 5

---

## Summary

spectHR is a dual-purpose tool: a user-friendly GUI application and a versatile Python library for HRV analysis. It supports preprocessing, visualization, peak detection, spectral analysis, and basic respiratory signal extraction, with plans for future expansion to validated blood pressure and respiratory support.
