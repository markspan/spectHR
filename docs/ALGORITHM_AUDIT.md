# spectHR Algorithm Audit

**Scope.** A review of the analysis algorithms in spectHR against current
practice in **non-clinical cardiovascular psychophysiology** (mental effort /
mental workload research in the Mulder / CARSPAN tradition), and against the
current state of the art as represented by NeuroKit2, pyHRV, Kubios, the
VU-AMS / VU-DAMS system, and the recent methods literature. It answers two
questions per parameter:

1. Is the algorithm used correctly for this type of research?
2. Is the *choice* of algorithm state-of-the-art, or is there a better one?

**Guiding principle, CARSPAN is load-bearing.** spectHR exists to bring the
Groningen CARSPAN method to a modern, inspectable desktop tool. Every
recommendation here is **additive**: optional, opt-in extra methods and
documentation clarifications. **No CARSPAN-based calculation is to be removed,
replaced, or moved off the default path.** The CARSPAN PSD variants, the
CARSPAN frequency bands, the CARSPAN transfer pipeline, the mMI² normalisation,
the cosine-bell taper, `Resample_R` bin-averaging, and the CARSPAN IBI
classification all stay exactly as they are.

> **This document supersedes the earlier (2025-Q1) audit.** That version
> predated much of the current code: it listed DFA, PRSA, a real stationarity
> test, Tarvainen detrending, and PEP as *future* suggestions (all are now
> implemented), and it referenced file names (`time_metrics.py`,
> `frequency_metrics.py`) that no longer exist. The inventory below reflects
> the code as it actually stands.

---

## Algorithm inventory (current)

| Domain | Implementation | File | SOTA verdict |
|---|---|---|---|
| R-peak detection | `scipy.find_peaks` (height = median + 1.5·σ) on a prefiltered ECG, **plus sub-sample timing interpolation**; then manual correction | `signal/rpeak.py` | ✅ fit for purpose; sub-sample timing a real strength (see §1) |
| ECG polarity | skewness of 5-20 Hz band-passed signal, peak-prominence tiebreaker | `signal/ecg.py` | ✅ sound |
| IBI classification | centred rolling window (default 51 beats, 4σ), T/TL excluded from own stats, SL / SNS morphology heuristics, **no silent interpolation** | `signal/ibi_classification.py` | ✅ correct design (see §2) |
| PSD, Welch | 4 Hz cubic resample → `scipy.welch`; optional VU-DAMS quadratic window | `analysis/psd/_welch.py` | ✅ standard |
| PSD, CARSPAN (events / ibi-amplitude) | native DFT on the true event grid, Eq. 3.19 / 3.21 | `analysis/psd/_carspan.py` | ✅ faithful |
| PSD, Lomb-Scargle | direct periodogram on unevenly-sampled IBIs | `analysis/psd/_lombscargle.py` | ✅ SOTA for uneven sampling |
| PSD, autoregressive | Burg AR(16) on the resampled tachogram | `analysis/psd/_autoregressive.py` | ✅ **added 2026** (Task Force parametric slot) |
| Detrending | Tarvainen smoothness-priors (opt-in, λ; off by default) | `analysis/detrend.py` | ✅ Kubios standard |
| Frequency bands | VLF 0.02-0.06, LF 0.07-0.14, HF 0.15-0.40 Hz (CARSPAN; user-configurable) | workspace config | ✅ correct for tradition (see §5) |
| Band power | rectangular integration | `analysis/psd/_band_power.py` | ✅ standard |
| Time-domain | count / mean / median / min / max / RMSSD / SDNN / SDSD | `analysis/ecg_metrics.py` | ✅ standard (ddof note §5) |
| Poincaré | SD1 = RMSSD/√2; SD2 via Brennan identity; SD2/SD1; ellipse area | `analysis/ecg_metrics.py` | ✅ exact + honest |
| Stationarity | linear trend (`stationarity`) **plus** reverse-arrangements z (`stationarity_z`, Bendat & Piersol) | `analysis/ecg_metrics.py` | ✅ proper test present |
| Non-linear | DFA short-term α1 (Peng, boxes 4-16) | `analysis/ecg_metrics.py` | ✅ standard |
| PRSA | Deceleration / Acceleration Capacity, four-point (Bauer 2006) | `analysis/ecg_metrics.py` | ✅ SOTA |
| RSA | Grossman peak-to-valley, 1.0 s lag | `analysis/respiration_metrics.py` | ✅ standard |
| Respiration phases | Savitzky-Golay smooth → peak/trough alternation → INH/EXH | `signal/respiration.py` | ✅ sound |
| PEP / B-point | Lozano 2007 (max 2nd-derivative of dZ/dt) with C−B guard zone | `analysis/icg_metrics.py` | ✅ best-benchmarked (see §4) |
| BP beat parameters | SBP / DBP / MAP (true integral) / PP, flat-line rejection | `analysis/bp_metrics.py` | ✅ correct |
| Transfer / BRS | CARSPAN `RunTransfer` port; coherence gate 0.5 | `analysis/transfer.py` | ✅ faithful, standards-aligned |
| Profiles | sliding-window band power via `PSDEngine` | `analysis/profile.py` | ✅ |

**Bottom line.** Every choice is current best practice or a deliberate,
well-justified CARSPAN convention. The remaining items are documented
comparability caveats (§5) and optional additive methods, not defects.

---

## 1. R-peak detection: fit for purpose, with a real sub-sample-timing strength

`detect_rpeaks` (`signal/rpeak.py`) has two stages, and the second is the one
that matters most for HRV quality.

**Peak picking.** Beats are found with an amplitude threshold
(`median + 1.5·σ`) via `scipy.signal.find_peaks` on the prefiltered ECG, gated
by a physiological refractory distance. For the clean laboratory ECG this
tool targets, this reliably locates R-peaks, and it is backstopped by the
mandatory classify-and-correct workflow (§2), so detection is a first pass the
analyst reviews, not an unchecked final answer.

**Sub-sample timing interpolation (the strength).** Each detected peak's time
is then refined to *fractional-sample* precision from the amplitude asymmetry
of its two neighbours, shifting it by up to ±0.5 samples. This is a genuine
quality feature, not a nicety: R-peak times quantised to the ECG sample grid
inject **sampling jitter** into the IBI series, which appears as spurious
broadband / high-frequency power in the HRV spectrum. Sub-sample correction
suppresses that jitter, and it is something many reference detectors omit
entirely (they report the integer sample index). On the moderate sampling
rates common in ambulatory and older recordings this materially improves the
tachogram, and it means spectHR's pipeline can yield a *cleaner* spectrum than
a more elaborate peak-picker that skips the refinement. This is state of the
art and should be highlighted as such.

**Optional extension, not a fix.** The peak-picking stage itself is a simple
threshold rather than a QRS-enhanced pipeline (Pan-Tompkins derivative /
squaring / integration, or a NeuroKit-style gradient detector). That only
matters on noisy, low-amplitude, or pathological ECG, i.e. field / ambulatory
data outside this tool's core lab domain. If such data ever becomes a target,
a QRS-enhanced detector is worth offering as a *selectable option* feeding the
same sub-sample refinement and manual-review workflow. It is a use-case
extension, not a correction of a deficiency.

---

## 2. IBI classification: a correct, inspection-first design (not a weak point)

`classify_ibi` (`signal/ibi_classification.py`) is a deliberately conservative,
analyst-in-the-loop artefact classifier, and for this tool that is the *right*
design, not a compromise. Its strengths are real and specific:

- **Local adaptivity.** A centred rolling window (default 51 beats) gives local
  mean/σ thresholds, so it tracks slow rate changes instead of applying one
  global cut-off.
- **Robust statistics.** T (degenerate) and TL (too-long) intervals are
  excluded from the rolling statistics *before* the thresholds are computed, so
  a big artefact cannot inflate the window's σ and hide its neighbours, a
  subtlety many naive detectors miss.
- **Morphology, not just magnitude.** The SL (short-then-long ectopic pair) and
  SNS (short-normal-short compensatory-pause) heuristics classify the *shape*
  of an ectopic event. This is exactly the "beat classification" idea that the
  modern Lipponen & Tarvainen (2019) algorithm is celebrated for.
- **No silent interpolation.** Flagged beats are surfaced for the analyst to
  correct; nothing is quietly replaced. For research where every substitution
  is a modelling decision, this is the methodologically correct stance
  (Berntson et al. 1990).

**On the earlier "not state-of-the-art" framing.** A previous draft of this
audit compared this classifier unfavourably with Lipponen & Tarvainen (2019),
the automatic corrector inside Kubios. That comparison applied the wrong
yardstick: L&T is optimised for *hands-off automatic correction* (it decides
and interpolates for you), whereas spectHR's classifier is optimised for
*inspectable, analyst-driven* review. These are different goals. L&T is an
**alternative for a different use case, not an upgrade**. The spectHR classifier
is a sound, well-designed method for what it is built to do.

If a fully-automatic mode is ever wanted (e.g. for batch ambulatory data), the
L&T dRR dual-threshold scheme would be the natural opt-in engine for it, but it
should sit *beside* the current classifier, never replace it, and it should not
weaken the no-silent-interpolation default.

---

## 3. Power spectral density: four methods, now including autoregressive

The PSD suite is Welch (4 Hz cubic resample → `scipy.welch`), Lomb-Scargle
(direct on the uneven IBIs), the two faithful CARSPAN variants (native DFT on
the true event grid), and, **new in 2026, an autoregressive (Burg) estimator**
(`analysis/psd/_autoregressive.py`).

- **Welch** is the field standard; cubic interpolation performs comparably to
  the alternatives (Clifford & Tarassenko 2005). The interpolation-free CARSPAN
  method remains the default for Profiles/Transfer, which is the right call at
  low beat counts.
- **Lomb-Scargle** is the recommended estimator for unevenly-sampled series and
  is correctly offered.
- **Autoregressive** fills the one method slot that pyHRV and Kubios had and
  spectHR previously lacked; the Task Force (1996) standard explicitly endorses
  the parametric approach alongside the periodogram family. It gives a smooth
  spectrum with sharper band peaks and no segment-length trade-off, an
  advantage on the short (1-5 min) epochs typical of mental-effort work. It is
  a tachogram method (Burg fit on the resampled series, default order 16, in the
  10-20 range Boardman et al. 2002 recommend) and is **opt-in**; the CARSPAN
  paths are never touched. Available in the PSD dock, the band-power epoch
  metrics, and the Profiles; Transfer keeps its CARSPAN SOC path by design.

The optional Tarvainen smoothness-priors detrending conditions the tachogram
before Welch / Lomb-Scargle / AR (never the CARSPAN paths) and is off by
default, the Kubios-standard pre-processing step, correctly scoped.

---

## 4. PEP / B-point: a well-chosen, well-validated method

The B-point (aortic-valve opening) is scored as the maximum of the second
derivative of `dZ/dt` on the upstroke before the C-point, with a C−B guard
zone (Lozano et al. 2007; `analysis/icg_metrics.py`). This is not merely
acceptable: the 2025 PEPbench benchmark of automated PEP algorithms ranked the
Lozano method **best** on its reference dataset (lowest mean absolute error).
The code's own validation against VU-DAMS-scored PEP (r up to 0.90 with the
guard zone) confirms the agreement, and it correctly avoids the discredited
"dZ/dt-min" PEP shortcut.

One note for the record: VU-AMS's own automated scorer uses a *third*-derivative
(d³Z/dt³) B-point rule. spectHR's second-derivative Lozano choice is the
better-benchmarked one; the third-derivative variant is only worth adding if
bit-for-bit VU-AMS agreement is ever a requirement.

The **Heather index** of contractility is also provided, a sensible companion
sympathetic-contractility index.

---

## 5. Correct-but-document: comparability caveats (not defects)

These are cases where a spectHR number is computed correctly but is **not
numerically interchangeable** with a differently-defined value elsewhere. Each
warrants a documentation sentence, not a code change.

- **CARSPAN vs Task Force bands.** spectHR's LF (0.07-0.14 Hz) is deliberately
  narrow, centred on the ~0.10 Hz Mayer-wave band Mulder identified as
  mental-effort-sensitive; it is *not* the Task Force LF (0.04-0.15 Hz). HF is
  identical. A reader must not compare spectHR "LF power" numerically against
  Task-Force-based LF without reconfiguring the edges. (The README's bands table
  is correct; the caveat is about cross-study comparison.)
- **Population vs sample SD (ddof).** SDNN/SDSD and the Poincaré measures use
  the population estimator (`ddof=0`) for CARSPAN parity; Task Force, pyHRV and
  Kubios use the sample SD (`ddof=1`). Negligible for long epochs, non-trivial
  for short ones. Keep `ddof=0` for parity, but document the divergence.
- **LF/HF ratio.** Report it descriptively. The "sympatho-vagal balance"
  interpretation is not supported (Billman 2013); the README already handles
  this correctly in prose.
- **Transfer-function BRS is open-loop.** It estimates an open-loop transfer of
  a closed-loop system (BP and HR drive each other). Inherent to the method,
  worth a one-line note in the Transfer section.

---

## 6. What is already implemented (former "future work", now done)

The previous audit's Part 3 wish-list is essentially complete:

| Former suggestion | Status |
|---|---|
| Tarvainen smoothness-priors detrending | ✅ `analysis/detrend.py`, opt-in toggle |
| Real stationarity test | ✅ `stationarity_z` (reverse-arrangements, Bendat & Piersol) |
| DFA-α1 | ✅ `dfa_a1` (Peng, boxes 4-16) |
| PRSA (DC / AC) | ✅ `dc` / `ac` (Bauer 2006) |
| PEP (needs ICG) | ✅ full ICG/PEP path, Lozano B-point, Heather index |
| Autoregressive PSD | ✅ `analysis/psd/_autoregressive.py` (added 2026) |

Reactivity / Δ-from-baseline scoring (report each epoch as a change from a
chosen baseline epoch) remains a worthwhile, purely post-processing addition and
is the main item still open on the "nice to have" list.

---

## Recommended actions (in priority order)

**Optional, opt-in additions (CARSPAN remains default everywhere):**

1. **Δ-from-baseline reactivity columns**, report each epoch as a change from a
   chosen baseline epoch; pure post-processing of the existing per-epoch
   metrics. *Highest value of the remaining items.*
2. (Only if noisy field / ambulatory ECG becomes a target) a QRS-enhanced
   R-peak *picker* (Hamilton or NeuroKit-style gradient) as a selectable option
   feeding the existing sub-sample refinement and manual-review workflow. A
   use-case extension, not a fix.
3. (If a batch/automatic mode is ever needed) an L&T-style automatic corrector
   *beside* the current inspection-first classifier, never replacing it.

**Documentation clarifications (no algorithm change):**

4. Cross-study comparability note for the CARSPAN LF/VLF bands vs Task Force.
5. Note the `ddof=0` (population SD) convention next to SDNN / Poincaré.
6. One-line open-loop-BRS caveat in the Transfer section.

No algorithm is used incorrectly, and the load-bearing CARSPAN methods are
faithful and, where benchmarked (PEP, BRS), competitive or best-in-class.

---

## References

- Bauer, A., et al. (2006). Deceleration capacity of heart rate. *The Lancet*, 367, 1674-1681.
- Bendat, J. S., & Piersol, A. G. (2010). *Random Data: Analysis and Measurement Procedures* (4th ed.). Wiley. (Reverse-arrangements stationarity test.)
- Berntson, G. G., et al. (1990). Heart rate variability: origins, methods, caveats. *Psychophysiology*, 30, 183-196.
- Billman, G. E. (2013). The LF/HF ratio does not accurately measure cardiac sympatho-vagal balance. *Frontiers in Physiology*, 4, 26.
- Boardman, A., et al. (2002). A study on the optimum order of autoregressive models for heart rate variability. *Physiological Measurement*, 23, 325-336.
- Brennan, M., et al. (2001). Do existing measures of Poincaré plot geometry reflect nonlinear features of HRV? *IEEE Trans. Biomed. Eng.*, 48, 1342-1347.
- Burg, J. P. (1975). *Maximum entropy spectral analysis*. PhD thesis, Stanford University.
- Clifford, G. D., & Tarassenko, L. (2005). Quantifying errors in spectral estimates of HRV due to beat replacement and resampling. *IEEE Trans. Biomed. Eng.*, 52, 630-638.
- de Geus, E. J. C., et al. (2019). Should heart rate variability be "corrected" for heart rate? *Psychophysiology*, 56, e13287.
- Grossman, P., et al. (1990). A comparison of three quantification methods for estimation of respiratory sinus arrhythmia. *Psychophysiology*, 27, 702-714.
- Hamilton, P. (2002). Open source ECG analysis. *Computers in Cardiology*, 29, 101-104.
- Lipponen, J. A., & Tarvainen, M. P. (2019). A robust algorithm for heart rate variability time series artefact correction using novel beat classification. *Journal of Medical Engineering & Technology*, 43, 173-181. (The Kubios automatic corrector; an alternative for automatic use, not a replacement for the inspection-first classifier.)
- Lozano, D. L., et al. (2007). Where to B in dZ/dt. *Psychophysiology*, 44, 113-119.
- Mulder, L. J. M. (1988/1992). Measurement and analysis methods of heart rate and respiration for use in applied environments. *Biological Psychology*, 34, 205-236.
- Pan, J., & Tompkins, W. J. (1985). A real-time QRS detection algorithm. *IEEE Trans. Biomed. Eng.*, 32, 230-236.
- PEPbench (2025). Open, Reproducible, and Systematic Benchmarking of Automated Pre-Ejection Period Extraction Algorithms. Preprint / benchmark study (Lozano 2007 ranked best on the reference dataset).
- Peng, C.-K., et al. (1995). Quantification of scaling exponents and crossover phenomena in nonstationary heartbeat time series. *Chaos*, 5, 82-87.
- Robbe, H. W. J., et al. (1987). Assessment of baroreceptor reflex sensitivity by spectral analysis. *Hypertension*, 10, 538-543.
- Tarvainen, M. P., et al. (2002). An advanced detrending method with application to HRV analysis. *IEEE Trans. Biomed. Eng.*, 49, 172-175.
- Task Force of the ESC and NASPE (1996). Heart rate variability: standards of measurement, physiological interpretation, and clinical use. *Circulation*, 93, 1043-1065.
- van Roon, A. M., Span, M. M., Lefrandt, J. D., & Riese, H. (2025). Overview of mathematical relations between Poincaré plot measures and time and frequency domain measures of HRV. *Entropy*, 27(8), 861.

---

## Sources consulted (reference tools and benchmarks)

Online sources checked for the state-of-the-art comparison in this audit:

- NeuroKit2, ECG documentation: <https://neuropsychology.github.io/NeuroKit/functions/ecg.html>
- NeuroKit2, `ecg_findpeaks` source: <https://github.com/neuropsychology/NeuroKit/blob/master/neurokit2/ecg/ecg_findpeaks.py>
- NeuroKit2, `fractal_dfa` source: <https://github.com/neuropsychology/NeuroKit/blob/master/neurokit2/complexity/fractal_dfa.py>
- Pan-Tompkins++ (arXiv 2211.03171): <https://arxiv.org/pdf/2211.03171>
- Lipponen & Tarvainen (2019), robust HRV artefact correction (PubMed): <https://pubmed.ncbi.nlm.nih.gov/31314618/>
- Kubios HRV Scientific User's Guide: <https://www.kubios.com/downloads/HRV-Scientific-Users-Guide.pdf>
- Kubios, HRV preprocessing: <https://www.kubios.com/blog/preprocessing-of-hrv-data/>
- PhysioNet, DFA reference implementation: <https://physionet.org/physiotools/wag/dfa-1.htm>
- PEPbench, benchmarking of automated PEP algorithms (PMC): <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12605688/>
- Lozano B-point detection and correction (PMC): <https://pmc.ncbi.nlm.nih.gov/articles/PMC6105363/>
- dZ/dt-min PEP inadequacy (ScienceDirect): <https://www.sciencedirect.com/science/article/abs/pii/S0167876012006460>
- pyHRV, frequency-domain module (Welch / Lomb-Scargle / autoregressive): <https://pyhrv.readthedocs.io/en/latest/_pages/api/frequency.html>
- VU-DAMS / VU-AMS software: <https://vu-ams.nl/software-solutions/>
- RSA quantification, methodological issues (PMC): <https://pmc.ncbi.nlm.nih.gov/articles/PMC1828207/>
