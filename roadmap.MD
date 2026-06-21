# spectHR roadmap: metrics and features for psychophysiology research

Candidate metrics and features that would bring spectHR closer to what
researchers expect from established HRV / cardiovascular psychophysiology tools
(Kubios HRV Scientific, NeuroKit2 / pyHRV, BIOPAC and Mindware impedance
workflows, the PhysioNet / RHRV ecosystem), prioritised by value to the target
user: a scientist doing psychophysiology research.

This is a living wish list with rationale, not a commitment. For the concrete,
ordered build plan of the next per-epoch metric columns (specs and formulae),
see [`src/spectHR/analysis/PLAN.md`](src/spectHR/analysis/PLAN.md).

## How to read this

* **Effort** is a rough size:
  * **S**: a few lines, a self-contained `@epoch_metric` (or a read of an
    already-cached value on the `EpochContext`).
  * **M**: a new calculator, a new `EpochContext` field, or a small UI surface.
  * **L**: a new preprocessing stage, a new dock / analysis mode, or work that
    needs external constants, calibration, or config.
* The analysis library is grouped by series (`ecg_metrics`, `bp_metrics`,
  `respiration_metrics`, `icg_metrics`, `transfer_metrics`; see
  [`src/spectHR/analysis/README.md`](src/spectHR/analysis/README.md)). Any new
  per-epoch scalar registered with `@epoch_metric` appears in the Results table
  and the CSV / HDF5 export automatically, so most **S** items are nearly free.
* **Guiding principle:** spectHR reports descriptively and leaves inference to
  the analyst's statistics package, the stance it already takes for LF/HF
  (Billman 2013). Every new composite or "balance" index inherits that caveat:
  ship the number, document the limits, do not imply a clean autonomic readout.

## Current state (implemented, so not on the roadmap)

* **Time-domain:** count, mean, median, min, max, RMSSD, SDNN, SDSD.
* **Poincaré:** SD1, SD2, SD2/SD1, ellipse area.
* **Non-linear:** DFA-alpha1; **PRSA** deceleration / acceleration capacity
  (DC/AC, Bauer 2006), which Kubios does not provide.
* **Stationarity:** linear drift correlation plus a reverse-arrangements
  z-score.
* **Frequency-domain:** CARSPAN / Welch / Lomb-Scargle PSD, per-band absolute
  powers, LF/HF; spectral profiles; 2-D and 3-D spectrogram.
* **Coupling:** input to HR transfer function with coherence (spectral
  baroreflex), per-band transfer profiles.
* **Respiration:** mean breathing frequency, an HF-in-band validity flag,
  respiratory volume (MVO/SVO), and **Grossman peak-to-valley RSA + RSA0** with
  the VU-DAMS artefact guards.
* **Blood pressure:** beat-by-beat SBP / DBP / PP / MAP (CARSPAN-faithful).
* **ICG:** pre-ejection period (PEP) with scored Q/B/C landmarks and a B-point
  guard.
* **ECG waveform:** `twave_amplitude` (mean T-wave amplitude per beat), the one
  metric computed directly on the ECG rather than the IBI series.
* **Workflow / architecture:** R-peak detection and manual editing; epochs
  (including from EVT event codes); per-series metric modules; lazy per-dock
  computation (closed docks cost nothing until opened); CSV + HDF5 export;
  dock-figure PDF export; single-file INI/JSON settings; persisted dock
  perspectives.

This is a strong, psychophysiology-oriented base: the ~0.10 Hz mental-effort
mid-band heritage, and BP, respiration and ICG analysed alongside HRV.

---

## Tier 1: high value for psychophysiology

### 1.1 Automatic artefact correction and trend removal *(foundational)*

Modern HRV pipelines do not rely on manual editing alone, and this is the one
item that changes every downstream number, so it comes first and is the
precondition for any credible cross-tool validation.

* **Automatic beat correction:** the Lipponen and Tarvainen (2019)
  dRR-distribution method (Kubios's graded low/medium/strong correction), with
  the **percentage of beats corrected reported per epoch**.
* **Smoothness-priors detrending** (Tarvainen et al. 2002) before spectral
  estimation; spectHR currently only high-passes the ECG.
* A per-epoch **data-quality column** (artefact %, count corrected, a usable
  flag) so analysts can screen or exclude epochs. Pairs with `stationarity_z`.

*Fit:* a `Session -> Session` stage in `spectHR/DataSet/preprocessing.py`, run
in `_LoadWorker`, plus a quality `@epoch_metric`. Correction must be a toggle
with its level recorded in the export (see Provenance below), since silent
beat-editing is a reproducibility hazard.
*Effort:* L. *Depends on:* nothing. *Validate by:* recover known artefacts in a
synthetic IBI series; reproduce Kubios's corrected RMSSD/SDNN within tolerance
on a shared recording. *Risk:* over-correction biases RMSSD downward, hence the
toggle and the reported correction fraction.

### 1.2 ICG hemodynamics beyond PEP

The ICG ensemble already scores Q, B and C, so the standard impedance panel
(Sherwood et al. 1990) is partly in reach, in increasing order of effort:

* **Heather index** = (dZ/dt)max / (Q-to-C interval), a contractility index. The
  C-point amplitude and the Q and C times are already in the ensemble, so this
  is essentially a read. *Effort:* S.
* **LVET** (left-ventricular ejection time, B to X). Needs **X-point** (aortic
  valve closure) detection, which the ensemble does not do yet. *Effort:* M.
* **Stroke volume** (Kubicek or Sramek-Bernstein), **cardiac output** (SV times
  HR), **total peripheral resistance** (needs MAP, which spectHR has from BP).
  SV needs LVET **and** thoracic constants (blood resistivity rho, electrode
  distance L, base impedance Z0); Z0 is not the same signal as dZ/dt, so the
  loader and config must surface it. *Effort:* L. *Risk:* SV/CO are only
  trustworthy with proper calibration inputs; expose them but document the
  assumptions, and blank them when Z0 / constants are unavailable.

*Fit:* extend `spectHR/analysis/icg_metrics.py` (X-point detection plus
calculators), new `@epoch_metric`s; constants live in the workspace.
*Validate by:* landmark timings against the VU-AMS reference on the example EDF;
Heather/LVET stability across epochs.

### 1.3 Event-related (phasic) cardiac response

The classic psychophysiology paradigm spectHR cannot currently do:
stimulus-locked, second-by-second HR/IBI averaging around event markers (the
deceleration then acceleration curve), with pre-stimulus baseline correction and
condition contrasts; extendable to evoked PEP and evoked T-wave amplitude.
spectHR already parses EVT event codes for epochs, so the event machinery exists.

*Fit:* a headless event-locked averaging module plus a new dock / analysis mode;
output is a time course per condition, not a single scalar, so it sits beside
the epoch table rather than inside it. *Effort:* L. *Depends on:* event markers
in the recording (EVT already; generalise to other loaders). *Validate by:* the
canonical evoked deceleration on a stimulus-locked synthetic series.

### 1.4 Frequency-domain reporting completeness

Reviewers expect these as default columns and they are cheap:

* **Normalised units** (LFn, HFn), **relative (%) band powers**, **peak
  frequency per band**, **total power**, **ln(HF)**.

*Fit:* new `@epoch_metric`s reading the PSD already cached on the
`EpochContext`. *Effort:* S. *Depends on:* nothing (values shift once 1.1 lands,
which is fine). *Validate by:* LFn + HFn approx 100 by construction; cross-check
against Kubios on a reference epoch.

---

## Tier 2: expected metrics, mostly small `@epoch_metric` additions

### 2.1 Time-domain staples
**pNN50 / NN50** (and pNN20), **mean HR and SD HR** (bpm), **CVNN / CVSD**, and
the geometric measures **HRV triangular index** and **TINN**. *Effort:* S.
*Validate by:* the standard definitions on a synthetic IBI series.

### 2.2 Non-linear / complexity family
* **DFA-alpha2** (long-term; spectHR has alpha1 only). *Effort:* S.
* **Sample Entropy**, **Approximate Entropy**, **Multiscale Entropy**.
  *Effort:* M (parameter choices m and r matter; fix sensible defaults and
  expose them, and require a minimum beat count).
* **CSI / CVI** (Cardiac Sympathetic / Vagal Index, Toichi 1997, Lorenz-plot
  based). *Effort:* S.
* **Heart-rate fragmentation** (PIP, IALS, PSS, PAS) and **heart-rate
  asymmetry** (Guzik / Porta). *Effort:* S.

*Risk:* entropy and fragmentation are sensitive to artefacts and series length,
so they depend on 1.1 for trustworthy values and should blank on short epochs.

### 2.3 Spontaneous baroreflex: sequence method
The time-domain complement to the existing spectral / transfer BRS: 3 or more
beats of concordant rising or falling SBP and IBI, slope in ms/mmHg, averaged
over up- and down-sequences. spectHR has beat-by-beat SBP and IBI already.
*Effort:* M. *Depends on:* a BP channel. *Validate by:* agreement with the
spectral alpha index on a recording with clear Mayer waves.

### 2.4 Blood-pressure variability (BPV)
Spectral analysis of the beat-to-beat SBP/DBP series (especially **LF-SBP** as a
vascular-sympathetic index), reusing the existing PSD engine on the per-beat BP
series. *Effort:* M. *Depends on:* a BP channel. *Validate by:* a known LF
oscillation injected into a synthetic SBP series.

---

## Tier 3: workflow and methodology (drives adoption)

### 3.1 Batch / group processing
Run a folder of recordings under one settings file, producing one long-format
results table (a row per participant by epoch). Often the deciding factor for
lab adoption; the headless `Session` / `EpochExporter` design is already most of
the way there. *Effort:* M.

### 3.2 PDF analysis report
A per-recording report (settings used, software version, artefact %, the metric
tables, key plots) for sharing and archiving, a notable Kubios selling point.
*Effort:* M. *Depends on:* 1.1 (the artefact figures) and Provenance below.

### 3.3 Respiration completeness
* **Respiration rate** as an explicit breaths/min column (alongside `resp_freq`
  in Hz). *Effort:* S.
* **Respiration-rate variability**. *Effort:* S.
* **ECG-derived respiration (EDR)** so RSA and `hf_resp_in_band` work on
  ECG-only recordings. *Effort:* M. *Risk:* EDR is a surrogate; label it as such
  and prefer a real respiration channel when present (spectHR already prefers
  native respiration over ICG/accelerometer).

### 3.4 Composite indices
Kubios's **PNS index** and **SNS index**, and **Baevsky's Stress Index (SI)**:
popular, simple, frequently requested. Report them with the same descriptive
caveats spectHR already applies to LF/HF. *Effort:* S.

---

## Cross-cutting: validation, provenance, units

These are not features so much as the discipline that makes a research tool
citeable; they should accompany the work above rather than follow it.

* **Validation harness.** Keep a small reference recording (the existing
  `ExampleData`, plus optionally a PhysioNet set) and a test that pins each new
  metric against an independently computed expected value (synthetic signal) and,
  where a standard exists, against Kubios / NeuroKit2 within a stated tolerance.
  Extend the pattern in [`docs/ALGORITHM_AUDIT.md`](docs/ALGORITHM_AUDIT.md).
* **Provenance in the export.** Write the software version, the settings used
  (PSD method, bands, artefact-correction level), and the per-epoch artefact %
  into the HDF5 / CSV, so a result is reproducible from the file alone.
* **Units discipline.** Every column carries its unit (the docstring tooltips
  already do this in the UI); normalised and dimensionless columns say so.

## Non-goals (out of scope, to keep the tool focused)

* Other modalities: EDA / skin conductance, EEG, EMG, pupillometry.
* Clinical diagnosis or risk scoring; spectHR is a research analyser.
* Real-time / streaming analysis and wearable-PPG-specific pipelines.
* A statistics engine: group inference stays in R / JASP / Python, by design.

---

## Dependency-ordered plan

Reasoning, not just sequence: the cheap, independent metric columns can land
immediately and in parallel, but the foundational artefact work gates trustworthy
validation, and the ICG and event-related work are the larger, higher-ceiling
investments.

1. **Quick wins, independent and low-risk:** frequency completeness (1.4),
   time-domain staples (2.1), DFA-alpha2 + CSI/CVI + fragmentation (parts of
   2.2), respiration rate (3.3). All **S**, all auto-surfaced in the export.
2. **Foundational:** automatic artefact correction + smoothness-priors
   detrending + per-epoch quality column (1.1). Revalidate the Tier-1/2 metrics
   against Kubios once this lands.
3. **ICG, in landmark order:** Heather index (S) now, then X-point and LVET (M),
   then SV/CO/TPR (L, needs Z0 and constants).
4. **Coupling and BP:** sequence-method BRS (2.3) and BP variability (2.4).
5. **Higher-ceiling:** event-related phasic response (1.3); entropy family
   completion (2.2).
6. **Adoption:** batch processing (3.1), PDF report (3.2), EDR (3.3), composite
   indices (3.4).

Provenance and the validation harness ride alongside steps 1 and 2 rather than
waiting for the end.

---

## References

Tarvainen, M. P., et al. (2014). *Kubios HRV, heart rate variability analysis
software.* Computer Methods and Programs in Biomedicine, 113(1), 210-220.
Lipponen, J. A., and Tarvainen, M. P. (2019). *A robust algorithm for heart
rate variability time series artefact correction using novel beat
classification.* Journal of Medical Engineering and Technology, 43(3), 173-181.
Tarvainen, M. P., Ranta-aho, P. O., and Karjalainen, P. A. (2002). *An advanced
detrending method with application to HRV analysis.* IEEE TBME, 49(2), 172-175.
Makowski, D., et al. (2021). *NeuroKit2: A Python toolbox for neurophysiological
signal processing.* Behavior Research Methods, 53, 1689-1696.
Sherwood, A., et al. (1990). *Methodological guidelines for impedance
cardiography.* Psychophysiology, 27(1), 1-23.
Grossman, P., and Taylor, E. W. (2007). *Toward understanding respiratory sinus
arrhythmia.* Biological Psychology, 74(2), 263-285.
La Rovere, M. T., Pinna, G. D., and Raczak, G. (2008). *Baroreflex sensitivity:
measurement and clinical implications.* Annals of Noninvasive Electrocardiology,
13(2), 191-207.
Toichi, M., et al. (1997). *A new method of assessing cardiac autonomic
function.* Journal of the Autonomic Nervous System, 62(1-2), 79-84.
Billman, G. E. (2013). *The LF/HF ratio does not accurately measure cardiac
sympatho-vagal balance.* Frontiers in Physiology, 4, 26.

(See also the bibliography in [`readme.MD` References](readme.MD#references).)
