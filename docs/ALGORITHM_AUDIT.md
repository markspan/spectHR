# spectHR Algorithm Audit

**Scope.** A review of the analysis algorithms in spectHR against current
practice in **non-clinical cardiovascular psychophysiology** (mental effort /
mental workload research in the Mulder / CARSPAN tradition). The report answers
three questions:

1. Are the algorithms used correctly for this type of research?
2. Are they described correctly in `readme.MD`?
3. Which additional algorithms would be useful for a researcher in this area?

**Guiding principle, CARSPAN is load-bearing.** spectHR exists to bring the
Groningen CARSPAN method to a modern, inspectable desktop tool. Every
recommendation here is **additive**: documentation clarifications and *optional,
opt-in* extra methods. **No CARSPAN-based calculation is to be removed,
replaced, or moved off the default path.** The CARSPAN PSD variants, the
CARSPAN frequency bands, the CARSPAN transfer pipeline, the mMI² normalisation,
the cosine-bell taper, `Resample_R` bin-averaging, and the CARSPAN IBI
classification all stay exactly as they are.

---

## Algorithm inventory (as audited)

| Domain | Implementation | File |
|---|---|---|
| R-peak detection | NeuroKit-style, then manual correction | preprocessing path |
| IBI classification | centred 51-beat rolling window, 4.0 σ; labels N/L/S/TL/SL/SNS/T; T & TL excluded | classification path |
| PSD, Welch | 4 Hz cubic resample → `scipy.signal.welch`; ms²/Hz → mMI²/Hz | `analysis/psd/_welch.py` |
| PSD, CARSPAN events | unit-impulse SOC, manual Eq. 3.19 | `analysis/psd/_carspan.py` |
| PSD, CARSPAN strict | IBI-amplitude DFT, manual Eq. 3.21 (default for profiles/transfer) | `analysis/psd/_carspan.py` |
| PSD, Lomb–Scargle | available variant | `analysis/psd/_lombscargle.py` |
| Frequency bands | VLF 0.02–0.06, LF 0.07–0.14, HF 0.15–0.40 Hz (CARSPAN; user-configurable) | workspace config |
| Band power | rectangular integration | `analysis/psd/_band_power.py` |
| Time-domain | count/mean/median/min/max/RMSSD/SDNN/SDSD/stationarity | `analysis/time_metrics.py` |
| Poincaré | SD1 = RMSSD/√2; SD2 via Brennan identity; SD2/SD1; ellipse area | `analysis/time_metrics.py` |
| Frequency-domain metrics | fullrange/vlf/lf/hf power; lf_hf_ratio | `analysis/frequency_metrics.py` |
| RSA | Grossman peak-to-valley, 1.0 s lag | respiration path |
| Transfer / BRS | CARSPAN `RunTransfer` port; coherence gate 0.5; ms/mmHg for BP input | `analysis/transfer.py` |
| BP beat parameters | SBP/DBP/MAP/PP per interval, flat-line rejection | `analysis/bp_metrics.py` |
| Profiles | sliding-window band power (CARSPAN `RunProfileSommation`) | `analysis/profile.py` |
| Spectrogram | time–frequency surface | `analysis/spectrogram.py` |

---

## Part 1: Are the algorithms used correctly?

### 1.1 R-peak detection and IBI classification: ✅ correct, conservative

The classification uses a centred rolling window (51 beats) with a 4.0 σ
threshold and excludes the **T** (too large) and **TL** (too large-large)
labels from every downstream metric. Crucially, there is **no silent
interpolation**: the user must inspect and correct flagged beats before any
metric is computed.

This matches best practice. Berntson et al. (1990) and Mulder (1988) both
stress that artifact detection must precede spectral estimation, and that a
single missed or spurious R-peak injects broadband energy that can swamp the
genuine HRV signal. spectHR's "you have to check data quality" stance is the
methodologically correct one.

**Gap.** The classifier catches *individual* deviant beats but does not assess
**epoch-level stationarity**, which is a precondition for spectral
interpretation. See §3.1 (Tarvainen detrending) and §3.4 (a real stationarity
test).

### 1.2 Welch PSD: ✅ correct, with the expected interpolation caveat

`_welch.py` resamples the unevenly-spaced IBI series to **4 Hz** by cubic
interpolation, then calls `scipy.signal.welch` (Hann window, 256-sample
segments, 50 % overlap). 4 Hz is comfortably above Nyquist for a 0.50 Hz
ceiling. Cubic interpolation is the field-standard approach and performs
comparably to alternatives (Laguna et al., 1998; Clifford & Tarassenko, 2005).

The known limitation, interpolation distorts the spectrum at low beat counts,
is precisely why the **interpolation-free CARSPAN method is offered and is the
default** for the Profiles and Transfer views. This is the right architectural
choice.

The mMI² normalisation (divide by mean IBI² then ×10⁶) is implemented in the
engine layer and is correct. The configurable `units` key (mMI² vs ms²) is
appropriate: whether to HR-correct HRV is genuinely unresolved (de Geus et al.,
2019), so exposing both is better than hard-coding either.

### 1.3 CARSPAN PSD: ✅ faithful and well-suited to the data

The `ibi_amplitude` variant (Eq. 3.21, `carspan_strict`) runs a native DFT on
the **actual cumulative-IBI time grid**, no uniform-resampling, no
stationary-grid assumption, and the `events` variant (Eq. 3.19) treats
R-peaks as unit impulses. Both are faithful ports of the CARSPAN Pascal source
and reproduce the manual's worked example to within ~2 % on every band.

For unevenly-sampled event series, a native DFT on the true event times is more
principled than forcing the data onto a uniform grid. The cosine-bell taper
(5 % per side, Pascal `TaperPercent`) correctly limits spectral leakage, and
the `smooth_for_display` 3-point moving average is applied **only to the
displayed curve, not to the band-power integrals**, so it does not bias any
exported metric. This is exactly how it should be.

### 1.4 Frequency bands: ⚠️ correct for this tradition, but the divergence from Task Force needs an explicit warning

spectHR's bands (CARSPAN / Groningen):

| Band | spectHR (CARSPAN) | Task Force (1996) |
|---|---|---|
| VLF | 0.02–0.06 Hz | < 0.04 Hz |
| LF | **0.07–0.14 Hz** | **0.04–0.15 Hz** |
| HF | 0.15–0.40 Hz | 0.15–0.40 Hz |

For this tool's research domain, the CARSPAN bands are the **correct** choice.
The narrow LF band (0.07–0.14 Hz) is deliberately centred on the ~0.10 Hz
Mayer-wave / baroreceptor oscillation that Mulder (1980, 1989) identified as the
band most sensitive to invested mental effort. HF is identical to Task Force.

**The risk is comparison error, not method error.** spectHR's LF is *not the
same quantity* as Task Force LF, it is narrower and shifted. A researcher who
reads "LF power" from spectHR and compares it numerically against published
Task-Force-based LF values is making a methodological mistake. The README
states that spectHR follows CARSPAN and links Mulder (1989), but it does **not
explicitly warn** that the LF/VLF numbers are not interchangeable with the
clinical-standard bands.

**Recommendation (doc only):** add one sentence to the Frequency bands section
stating that spectHR's LF/VLF follow the CARSPAN convention and are not directly
comparable to Task Force (1996) LF/VLF without reconfiguring the band edges.
The bands themselves stay as they are.

### 1.5 LF/HF ratio: ⚠️ fine to export; the "sympatho-vagal balance" label is outdated

`frequency_metrics.py:136` documents `lf_hf_ratio` as a "sympatho-vagal balance
indicator." Since Billman (2013), Reyes del Paso et al. (2013), and Heathers
(2014), that interpretation is widely rejected: LF power is not a clean
sympathetic index (it mixes baroreflex, both autonomic branches, and mechanical
respiratory coupling), so the ratio inherits all of that ambiguity.

The README's main text already hedges correctly ("LF: baroreceptor reflex,
mixed sympathetic/parasympathetic"). Only the **code docstring** overstates the
case.

**Recommendation (wording only):** change the docstring to, e.g., *"LF/HF ratio.
Historically read as sympatho-vagal balance; that interpretation is not
supported (Billman 2013), report it descriptively."* The calculation is
unchanged. Optionally add the same caveat next to `lf_hf_ratio` in the README
export table.

### 1.6 Time-domain & Poincaré metrics: ✅ correct; the Poincaré disclosure is exemplary

RMSSD, SDNN, SDSD are standard and correctly restricted to N-labelled beats.
The Poincaré derivations use exact algebraic identities:
SD1 = RMSSD/√2, and SD2² = 2·Var(IBI) − ½·Var(ΔIBI) (Brennan et al., 2001).
`sd_ratio` and `ellipse_area` guard against degenerate uniform-IBI series.

The README's note (citing van Roon et al., 2025) that SD1/SD2 carry no
information beyond RMSSD/SDNN and should not be treated as independent metrics
is one of the most honest disclosures in any HRV package. **Keep it verbatim.**

**Gap.** `stationarity` is a Pearson correlation of IBI vs time, a *linear
trend* detector only. It will miss non-linear drift, periodic trends, and
variance non-stationarity, which are the conditions that actually violate the
wide-sense-stationarity assumption behind Welch and CARSPAN PSD. See §3.4.

### 1.7 Grossman peak-to-valley RSA: ✅ correct, with a sound default

The 1.0 s lag matches Grossman et al. (1990) and the VU-DAMS implementation
(the manual is bundled in `docs/`). The configurable `rsa_lag_s` with the
explicit note that children (20–30 bpm) need 0.3–0.5 s reflects current
knowledge of vagal conduction delay. Invalid cycles are NaN-flagged rather than
silently zeroed (`rsa` keeps NaN; `rsa0` zero-fills), a clean separation.

### 1.8 Transfer function / spectral baroreflex sensitivity: ✅ faithful and standards-aligned

`transfer.py` is a careful port of the CARSPAN `RunTransfer` pipeline
(taper → IBI-amplitude SOC DFT → auto/cross-spectra → optional 3-point
triangular smoother → H = Cross/Auto_in → modulus / wrapped & unwrapped phase /
squared coherence → coherence-gated band summaries). Every step is annotated
with its Pascal source line.

Two correctness points worth highlighting:

- **Coherence gate = 0.5.** This matches the Robbe et al. (1987) standard for
  spectral BRS and is the right default.
- **Single-epoch coherence is 1 by construction**, correctly documented, and
  the `smooth=True` path (3-point triangular smoother) is what yields sub-unity
  coherence for sliding-window analysis. This is mathematically sound and
  faithful to CARSPAN's `WindowSize=3` profile branch.

For BP→HR the modulus unit is correctly reported as **ms/mmHg**, the
conventional BRS gain unit. SBP/DBP as input and IBI as output follows the
standard convention.

**Caveat to surface (doc only):** transfer-function BRS is an *open-loop*
estimate of a closed-loop system (BP and HR drive each other). This is inherent
to the method, not a bug, but a one-line note in the Transfer section would set
correct expectations.

### Part 1 summary

| Algorithm | Verdict |
|---|---|
| R-peak / IBI classification | ✅ correct, conservative |
| Welch PSD | ✅ correct |
| CARSPAN PSD (both variants) | ✅ faithful |
| Frequency bands | ⚠️ correct for tradition; add comparison warning |
| LF/HF ratio | ⚠️ valid; fix docstring wording |
| Time-domain / Poincaré | ✅ correct; exemplary disclosure |
| Grossman RSA | ✅ correct |
| Transfer / BRS | ✅ faithful; add open-loop note |

No algorithm is used *incorrectly*. The only substantive issues are
**interpretive labelling** (LF/HF) and **comparability documentation** (bands).

---

## Part 2: Are they described correctly in `readme.MD`?

The README is unusually thorough and, in most places, more careful than the
published literature it draws on. Findings:

### 2.1 Confirmed typo: FullRange band range

`readme.MD:274` (Step 5, PSD tab):

> **FullRange (0.02–0.65 Hz)**, the total HRV spectrum.

The code and the band-config table both use **0.02–0.50 Hz** (the transfer
`f_max` default is 0.5 Hz, and the FullRange band tops out at 0.50). The
"0.65" is a typo. **Fix to 0.02–0.50 Hz.**

### 2.2 Bands table vs. PSD-tab text: consistent

The Theoretical-background table (`:144`) and the PSD-tab list (`:274`) agree on
VLF/LF/HF. Good. Only the FullRange figure above is wrong.

### 2.3 LF/HF ratio: README is fine, code lags

The README never calls LF/HF "sympatho-vagal balance" in its main prose; the
overstatement is confined to the code docstring (§1.5). Optionally add a caveat
next to `lf_hf_ratio` in the Parameters export table for completeness.

### 2.4 Task Force comparability: missing caveat

As noted in §1.4, the README should explicitly state that CARSPAN LF/VLF are not
numerically interchangeable with Task Force LF/VLF. Currently a reader could
assume they are.

### 2.5 Normalisation: units, RSA lag, HDF5/CSV schema, accurate

The mMI² vs ms² explainer (`:160`–`:169`) is correct and genuinely educational.
The RSA-lag section (`:365`–`:371`) correctly cites Grossman (1990) and the
children caveat. The HDF5/CSV schema documentation matches the export code,
including the "every scalar is also an epoch-group attribute" design and the
per-epoch failure handling.

### 2.6 Transfer section: accurate, could add the open-loop note

The Transfer documentation (`:305`–`:351`) accurately describes modulus / phase
/ coherence, the coherence gate, the smoothing toggle, and the input-signal
selector. Adding the one-line open-loop-BRS caveat (§1.8) would round it out.

### Part 2 summary

| Item | Status | Action |
|---|---|---|
| FullRange 0.02–**0.65** Hz | ❌ typo | fix to 0.02–0.50 Hz |
| Task Force comparability | ⚠️ missing | add one warning sentence |
| LF/HF "balance" | ✅ README ok; code docstring off | fix docstring |
| Open-loop BRS | ⚠️ missing | add one note |
| Everything else | ✅ accurate |, |

---

## Part 3: Additional algorithms worth considering

All are **optional, opt-in additions** that sit alongside the CARSPAN engine.
None displaces a CARSPAN default. Ranked by value to non-clinical
cardiovascular-psychophysiology research.

### 3.1 Tarvainen smoothness-priors detrending: ⭐ highest priority

**What.** A regularised detrending method (Tarvainen et al., 2002) that removes
slow non-stationary trends from the IBI series without the band-edge distortion
of a high-pass filter. It is the de-facto standard pre-processing step in
modern HRV pipelines (it is built into Kubios).

**Why it fits.** Mental-effort epochs frequently contain slow drift (warm-up,
fatigue, posture). That drift leaks into VLF/LF and biases exactly the
mental-effort-sensitive band. Smoothness-priors detrending is the cleanest fix
and would *improve* the reliability of the existing CARSPAN LF estimate rather
than compete with it.

**Integration.** A pre-processing toggle ("detrend: none / smoothness-priors,
λ=…") applied before PSD. CARSPAN stays the spectral engine; detrending just
conditions its input. Single small numpy/scipy function.

### 3.2 Event-related / baseline-referenced reactivity scoring: ⭐ high

**What.** Report each task epoch as a **change from a baseline epoch**
(ΔRMSSD, ΔLF, ΔHF, ΔHR…), not only as absolutes.

**Why it fits.** Mental-effort research is fundamentally about *reactivity*,
the cost of effort relative to rest (Mulder 1992; Stuiver & Mulder 2014). The
tool already computes everything per epoch; adding a "baseline epoch" selector
and emitting Δ and %-change columns turns raw metrics into the quantities
researchers actually analyse. Pure post-processing on existing outputs.

### 3.3 Respiration-corrected HF-HRV: medium

**What.** Report HF power (or RSA) adjusted for respiration rate/depth, since HF
amplitude depends on breathing parameters independently of vagal tone (Grossman
& Taylor, 2007).

**Why it fits.** spectHR already extracts respiration and computes breath
frequency. Surfacing the breathing rate alongside HF, and optionally flagging
when the breathing peak falls outside the HF band, lets users judge whether an
HF change is vagal or merely a breathing artifact. Low effort given the existing
respiration pipeline; can reuse the transfer machinery already present.

### 3.4 A real stationarity / non-stationarity test: medium

**What.** Replace or supplement the linear-trend `stationarity` metric with a
proper test (e.g. reverse-arrangements test, or a windowed variance-ratio
check) that flags epochs unsuitable for spectral interpretation.

**Why it fits.** Welch and CARSPAN PSD both assume wide-sense stationarity. The
current Pearson-r metric only catches linear trends. A genuine test (paired
naturally with §3.1) would warn users before they over-interpret a spectrum
from a non-stationary epoch. Additive: a new `@epoch_metric` column.

### 3.5 DFA-α1 (detrended fluctuation analysis): lower

**What.** Short-term scaling exponent α1 (Peng et al., 1995), a non-linear HRV
index increasingly reported in psychophysiology.

**Why it fits.** Adds a non-linear dimension complementary to the spectral and
Poincaré measures. Requires ≥ a few hundred beats per epoch, so its
applicability depends on epoch length. Self-contained algorithm; nice-to-have.

### 3.6 PRSA (phase-rectified signal averaging): lower / exploratory

**What.** Bauer et al. (2006) acceleration/deceleration capacity, robust to
non-stationarity and artifacts.

**Why it fits.** Strong artifact tolerance is attractive for field/ambulatory
data, but PRSA is more established in clinical risk stratification than in
mental-effort work. Worth noting as a future direction.

### 3.7 PEP / pre-ejection period: note only (needs ICG)

PEP is the cleanest non-invasive sympathetic index and would complement the
parasympathetic-dominant HRV measures. It requires impedance cardiography (ICG),
which spectHR does not ingest. Out of scope unless an ICG channel is added, but
worth a line in the README's "what HRV can and cannot tell you" discussion,
which already correctly notes that HRV does not directly index sympathetic
activity.

### Part 3 priority summary

| Algorithm | Value | Effort | Note |
|---|---|---|---|
| Tarvainen detrending | ⭐ highest | low | conditions CARSPAN input; doesn't replace it |
| Reactivity / Δ-from-baseline | ⭐ high | low | post-processing of existing metrics |
| Respiration-corrected HF | medium | low–med | reuses existing respiration pipeline |
| Real stationarity test | medium | low | pairs with detrending |
| DFA-α1 | lower | med | needs longer epochs |
| PRSA | lower | med | artifact-robust; more clinical |
| PEP | note only | n/a | needs ICG hardware |

---

## Recommended actions (in priority order)

**Safe documentation / wording fixes (no algorithm change):**

1. Fix the FullRange typo `0.02–0.65` → `0.02–0.50 Hz` (`readme.MD:274`).
2. Add a Task Force comparability warning to the Frequency-bands section.
3. Soften the `lf_hf_ratio` docstring (and optionally the README export table).
4. Add a one-line open-loop-BRS caveat to the Transfer section.

**Optional, opt-in algorithm additions (CARSPAN remains default everywhere):**

5. Smoothness-priors detrending as a pre-processing toggle.
6. Baseline-referenced reactivity (Δ / %-change) columns.
7. Respiration-rate surfacing / HF-breathing-band overlap flag.
8. A genuine stationarity test as a new epoch metric.

---

## References

- Bauer, A., et al. (2006). Deceleration capacity of heart rate. *The Lancet*, 367, 1674–1681.
- Berntson, G. G., et al. (1990). Heart rate variability: origins, methods, caveats. *Psychophysiology*, 30, 183–196.
- Billman, G. E. (2013). The LF/HF ratio does not accurately measure cardiac sympatho-vagal balance. *Frontiers in Physiology*, 4, 26.
- Brennan, M., et al. (2001). Do existing measures of Poincaré plot geometry reflect nonlinear features of HRV? *IEEE Trans. Biomed. Eng.*, 48, 1342–1347.
- Clifford, G. D., & Tarassenko, L. (2005). Quantifying errors in spectral estimates of HRV due to beat replacement and resampling. *IEEE Trans. Biomed. Eng.*, 52, 630–638.
- de Geus, E. J. C., et al. (2019). Should heart rate variability be "corrected" for heart rate? *Psychophysiology*, 56, e13287.
- Grossman, P., et al. (1990). A comparison of three quantification methods for estimation of respiratory sinus arrhythmia. *Psychophysiology*, 27, 702–714.
- Grossman, P., & Taylor, E. W. (2007). Toward understanding respiratory sinus arrhythmia. *Biological Psychology*, 74, 263–285.
- Heathers, J. A. J. (2014). Everything Hertz: methodological issues in short-term frequency-domain HRV. *Frontiers in Physiology*, 5, 177.
- Laguna, P., et al. (1998). Power spectral density of unevenly sampled data by least-square analysis. *IEEE Trans. Biomed. Eng.*, 45, 698–715.
- Mulder, G. (1980). *The heart of mental effort*. PhD thesis, University of Groningen.
- Mulder, L. J. M. (1988/1992). Measurement and analysis methods of heart rate and respiration for use in applied environments. *Biological Psychology*, 34, 205–236.
- Mulder, L. J. M. (1989). CARSPAN: cardiovascular spectral analysis.
- Peng, C.-K., et al. (1995). Quantification of scaling exponents and crossover phenomena in nonstationary heartbeat time series. *Chaos*, 5, 82–87.
- Reyes del Paso, G. A., et al. (2013). The utility of LF/HF as an index of sympathetic cardiac control. *Psychophysiology*, 50, 477–487.
- Robbe, H. W. J., et al. (1987). Assessment of baroreceptor reflex sensitivity by spectral analysis. *Hypertension*, 10, 538–543.
- Stuiver, A., & Mulder, B. (2014). Cardiovascular state changes during mental effort. *Biological Psychology*, 99, 27–34.
- Tarvainen, M. P., et al. (2002). An advanced detrending method with application to HRV analysis. *IEEE Trans. Biomed. Eng.*, 49, 172–175.
- Task Force of the ESC and NASPE (1996). Heart rate variability: standards of measurement, physiological interpretation, and clinical use. *Circulation*, 93, 1043–1065.
- van Roon, A. M., Span, M. M., Lefrandt, J. D., & Riese, H. (2025). Overview of mathematical relations between Poincaré plot measures and time and frequency domain measures of HRV. *Entropy*, 27(8), 861.
