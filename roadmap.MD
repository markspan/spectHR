# spectHR roadmap — metrics & features for psychophysiology research

This roadmap captures candidate metrics and features that would bring spectHR
closer to the feature set researchers expect from established HRV / cardiovascular
psychophysiology tools (Kubios HRV Scientific, NeuroKit2 / pyHRV, BIOPAC &
Mindware impedance workflows, the PhysioNet/RHRV ecosystem), prioritised by
value to the target user: a scientist doing psychophysiology research.

It is a *wish list with rationale*, not a commitment. Items are grouped by tier
(value × effort) and annotated with how they fit spectHR's architecture. Because
every per-epoch scalar is just an `@epoch_metric` discovered by the registry
(see [`src/spectHR/analysis/README.md`](src/spectHR/analysis/README.md)), many
Tier-2 items are a few lines that appear in the Results table and CSV/HDF5 export
automatically; the bigger lifts are preprocessing stages, new ICG calculators,
an event-related analysis mode, and batch/report workflow.

---

## Where spectHR already stands

Already implemented (so *not* on this roadmap):

- **Time-domain:** count, mean, median, min, max, RMSSD, SDNN, SDSD.
- **Poincaré:** SD1, SD2, SD2/SD1, ellipse area.
- **Non-linear:** DFA-α1; **PRSA** deceleration/acceleration capacity (DC/AC) —
  notably *not* in Kubios.
- **Stationarity:** linear drift correlation + reverse-arrangements z-score.
- **Frequency-domain:** CARSPAN / Welch / Lomb–Scargle PSD, per-band absolute
  powers, LF/HF; spectral profiles; 2-D + 3-D spectrogram.
- **Coupling:** input→HR transfer function with coherence (spectral baroreflex),
  per-band transfer profiles.
- **Respiration:** mean breathing frequency, HF-in-band validity flag,
  respiratory volume (MVO/SVO), and **Grossman peak-to-valley RSA + RSA0** with
  the VU-DAMS artefact guards.
- **Blood pressure:** beat-by-beat SBP / DBP / PP / MAP (CARSPAN-faithful).
- **ICG:** pre-ejection period (PEP) with scored Q/B/C landmarks and a B-point
  guard.
- **Workflow:** R-peak detection + manual editing, epochs (incl. from EVT event
  codes), CSV + HDF5 export, dock-figure PDF export.

This is a strong, psychophysiology-oriented base (the ~0.10 Hz mental-effort
mid-band heritage; BP, respiration and ICG analysed alongside HRV).

---

## Tier 1 — high value for psychophysiology

### 1.1 Automatic artefact correction + trend removal *(biggest single gap)*
Modern HRV pipelines do not rely on manual editing alone.
- **Automatic beat correction** — the Lipponen & Tarvainen (2019) dRR-distribution
  threshold method (Kubios's graded *low/medium/strong* correction), reporting the
  **percentage of beats corrected** per epoch.
- **Smoothness-priors detrending** (Tarvainen et al. 2002) before spectral
  estimation, to remove slow non-stationary trends. spectHR currently only
  high-passes the ECG.
- A per-epoch **data-quality column** (artefact %, # corrected, quality flag) so
  analysts can screen or exclude epochs. Pairs naturally with `stationarity_z`.

*Fit:* a preprocessing-pipeline stage (`spectHR/DataSet/preprocessing.py`) plus a
quality `@epoch_metric`.

### 1.2 ICG hemodynamics beyond PEP
spectHR already ensemble-averages the ICG and scores Q/B/C, so the landmarks for
the standard impedance-cardiography panel (Sherwood et al. 1990) are in reach:
- **LVET** (left-ventricular ejection time, B→X), **stroke volume** (Kubicek or
  Sramek–Bernstein), **cardiac output** (SV × HR), **Heather index**
  (dZ/dt-max ÷ Q-to-C time, contractility), **thoracic fluid content (TFC)**, and
  **total peripheral resistance** (needs MAP — spectHR has BP).

*Fit:* extend `spectHR/analysis/icg_metrics.py` (new landmarks + calculators),
new `@epoch_metric`s.

### 1.3 Event-related (phasic) cardiac response
The classic psychophysiology paradigm spectHR cannot currently do: stimulus-locked,
second-by-second HR/IBI averaging around event markers (the deceleration→acceleration
curve), with pre-stimulus baseline correction and condition contrasts; extendable
to evoked PEP. spectHR already parses EVT event codes for epochs — this reuses that
machinery for an *evoked-response* mode.

*Fit:* a new analysis mode + dock; a new headless module for event-locked averaging.

### 1.4 Frequency-domain reporting completeness
Reviewers expect these as default columns:
- **Normalised units** (LFn, HFn), **relative (%) band powers**, **peak frequency
  per band**, **total power**, **ln(HF)**.

*Fit:* new `@epoch_metric`s reading the already-cached PSD on the `EpochContext`.

---

## Tier 2 — expected metrics, mostly small `@epoch_metric` additions

### 2.1 Time-domain staples
**pNN50 / NN50** (and pNN20), **mean HR & SD HR** (bpm), **CVNN / CVSD**, and the
geometric measures **HRV triangular index** and **TINN**.

### 2.2 Non-linear / complexity family
- **DFA-α2** (long-term; spectHR has α1 only).
- **Sample Entropy**, **Approximate Entropy**, **Multiscale Entropy**.
- **CSI / CVI** (Cardiac Sympathetic / Vagal Index, Toichi — Lorenz-plot based).
- **Heart-rate fragmentation** (PIP, IALS, PSS, PAS) and **heart-rate asymmetry**
  (Guzik / Porta).

### 2.3 Spontaneous baroreflex — sequence method
The time-domain complement to the existing spectral/transfer BRS: 3+ beats of
concordant rising/falling SBP and IBI, slope in ms/mmHg, averaged over up- and
down-sequences. spectHR has beat-by-beat SBP + IBI already.

### 2.4 Blood-pressure variability (BPV)
Spectral analysis of the beat-to-beat SBP/DBP series (especially **LF-SBP** as a
vascular-sympathetic index), reusing the existing PSD engine on the per-beat BP
series.

*Fit:* all of Tier 2 are self-contained `@epoch_metric`s (or a BP-series PSD pass)
that surface automatically in the table and export.

---

## Tier 3 — workflow & methodology (drives adoption)

### 3.1 Batch / group processing
Run a folder of recordings under one settings file → one long-format results table
(row per participant × epoch). Often the deciding factor for lab adoption; the
headless `Session` / `EpochExporter` design is already most of the way there.

### 3.2 PDF analysis report
A per-recording report (settings used, artefact %, metric tables, key plots) for
sharing and archiving — a notable Kubios selling point.

### 3.3 Respiration completeness
**Respiration rate** as an explicit breaths/min column (alongside `resp_freq` Hz),
**respiration-rate variability**, and **ECG-derived respiration (EDR)** so RSA and
`hf_resp_in_band` work on ECG-only recordings.

### 3.4 Composite indices
Kubios's **PNS index** and **SNS index**, and **Baevsky's Stress Index (SI)** —
popular, simple, frequently requested (report with the same descriptive caveats
spectHR already applies to LF/HF).

---

## Suggested order

1. Artefact correction + smoothness-priors detrending + per-epoch quality flag (1.1).
2. ICG hemodynamics: LVET, SV, CO, Heather index, TPR (1.2).
3. Frequency normalised/relative/peak/total + pNN50 / HR-stats (1.4 + 2.1).
4. Event-related phasic cardiac response (1.3).
5. SampEn/ApEn, DFA-α2, CSI/CVI, fragmentation/asymmetry (2.2).
6. Sequence-method BRS + BPV (2.3–2.4); then batch processing + PDF report (3.1–3.2).

---

## References

Tarvainen, M. P., et al. (2014). *Kubios HRV — heart rate variability analysis
software.* Computer Methods and Programs in Biomedicine, 113(1), 210–220.
Lipponen, J. A., & Tarvainen, M. P. (2019). *A robust algorithm for heart rate
variability time series artefact correction using novel beat classification.*
Journal of Medical Engineering & Technology, 43(3), 173–181.
Tarvainen, M. P., Ranta-aho, P. O., & Karjalainen, P. A. (2002). *An advanced
detrending method with application to HRV analysis.* IEEE TBME, 49(2), 172–175.
Makowski, D., et al. (2021). *NeuroKit2: A Python toolbox for neurophysiological
signal processing.* Behavior Research Methods, 53, 1689–1696.
Sherwood, A., et al. (1990). *Methodological guidelines for impedance
cardiography.* Psychophysiology, 27(1), 1–23.
Grossman, P., & Taylor, E. W. (2007). *Toward understanding respiratory sinus
arrhythmia…* Biological Psychology, 74(2), 263–285.
La Rovere, M. T., Pinna, G. D., & Raczak, G. (2008). *Baroreflex sensitivity:
measurement and clinical implications.* Annals of Noninvasive Electrocardiology,
13(2), 191–207.
Toichi, M., et al. (1997). *A new method of assessing cardiac autonomic function…*
Journal of the Autonomic Nervous System, 62(1–2), 79–84.

(See also the bibliography in [`readme.MD` § References](readme.MD#references).)
