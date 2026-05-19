# Porting CARSPAN's profile computation into spectHR

This document is the step-by-step plan for replacing the current
`CardioMetricsMixin.band_power_profile` body with a faithful port of
CARSPAN's `RunAnalysis(Tag=1)` profile pipeline from
`T_AnaFunctions.pas`. The goal is the same one we hit with the PSD port:
read the spectHR profile output as if it had come straight out of the
Delphi/Pascal CARSPAN — same numbers, same sliding-window grid, same
band-edge logic — and keep everything that isn't necessary
(blood-pressure cross spectra, modulus/phase/coherence, OUT signals)
out of the picture.

A side-by-side audit (CARSPAN vs spectHR) is in section 1. Sections 2-9
are the actual port steps, each with the exact Pascal block it mirrors.

---

## 1. What's the same, what's different

CARSPAN's profile pipeline lives in `T_AnaFunctions.pas` and runs
`RunAnalysis` with `FViewProgressAnalysis.Tag = 1`. Six Pascal routines
fire per call, in order:

1. `RunDFT`               (line 1929, `Tag<>0` branch at 2032)
2. `RunPDS`                (line 2102, `Tag<>0` branch at 2152)
3. `RunCrossSpectrum`      (line 2179, ignored — no OUT signal)
4. `RunResample`           (line 2253, `Tag<>0` branch at 2320)
5. `RunMAW`                (line 2347, `Tag<>0` branch at 2421)
6. `RunProfileSommation`   (line 2888 — the integrator)

spectHR's `band_power_profile` (`CardioMetricsMixin.py:507`) calls
`view.band_powers(psd_method=method)` per window, which internally
runs `compute_carspan_psd_strict(smooth=False)` then
`band_power_rectangular`. That already covers steps 1, 2, 4, and 5
(the SOC + AutoSpectrum + Resample + MAW-suppressed chain) **inside the
PSD compute layer** — `compute_carspan_psd_strict` is the bit-by-bit
port of `SOC + AutoSpectrum(mode=3) + Resample_R` we built during the
PSD port, and the `smooth=False` argument forces the MAW skip.

So the per-window PSD inputs are already aligned. **The gap is in step
6** — `RunProfileSommation`:

| | CARSPAN | spectHR today |
|---|---|---|
| Window arithmetic | `floor((T - W)/S) + 1`, start `t₀ + p·S`, stop `t₀ + p·S + W` | identical |
| Per-window PSD | SOC → AutoSpectrum → Resample (no MAW) | identical via `compute_carspan_psd_strict(smooth=False)` |
| Band edges | **resp-aware** per window via `GetRespirationMinBandValue`/`GetRespirationMaxBandValue` if `AnaBand.RespirationBand=True`, else static `AnaBand.Min/Max` | always static `BandSpec.low/high` |
| Resp-freq source | `1/LProfile.MeanIn` when input signal is `RespPeriod` | not consulted |
| Resp-freq cap | `(PDSin_BCK.Count-1)·FreqRes` | not consulted |
| Integration | `Σ bin · FreqRes` with `FreqRes = 1/WindowLength` and indices `round(F/FreqRes)-1` | `band_power_rectangular` (midpoint rule on the resampled grid) |
| mMI² conversion | `d = sqr(MeanIn)`, `Result / d` (Eq. 3.20) | already in `_carspan_display` per window |
| Other outputs | modulus / phase / coherence / cross | not used in HRV-only spectHR |

The four bullet points to action are therefore:

- A. **Resp-aware band edges per window** (the headline change).
- B. **Resp-frequency estimation from spectHR's `RespirationSeries`**
     (CARSPAN's `1/MeanIn` doesn't translate directly — we use the
     accelerometer-derived breathing signal we already segment).
- C. **A `BandSpec.respiration_band` flag** so existing fixed bands keep
     working and only ones marked respiration-tracked are remapped.
- D. (Optional) A `carspan_strict` integration mode that mirrors Pascal's
     `round(F/FreqRes)-1` index quirk with `FreqRes = 1/WindowLength`,
     for bit-exact comparisons against CARSPAN. Default integration
     stays the cleaner midpoint rule.

Blood-pressure paths, the OUT signal (`PDSout_BCK`), cross spectrum
(`CrsSp`), `Coherence`, `Modulus`, `Phase`, `Phase2` — all skipped.

---

## 2. Step 1 — Window enumeration

**Pascal** (`GetNrOfProfiles` at line 1153, `GetProfileData` at 1115):

```pascal
result := floor((GetSegmentTime - WindowLength) / StepSize) + 1;
StartTime := Double(RP.First^) + ProfileIndex * StepSize;
StopTime  := Double(RP.First^) + ProfileIndex * StepSize + WindowLength;
```

**spectHR** — already matches at `CardioMetricsMixin.py:570-582`:

```python
n_windows = int((duration - window_s) / step_s) + 1
win_start = t0 + i * step_s
win_end   = win_start + window_s
```

**Action**: none. Window loop arithmetic is already bit-identical.

---

## 3. Step 2 — Per-window PSD

**Pascal** (`RunDFT` 2042-2096 → `RunPDS` 2162-2173 → `RunResample`
2329-2341 → `RunMAW` 2433-2484, with the working `PDSin` backed up to
`PDSin_BCK` *before* the 3-point MAW so integration runs on the
un-smoothed copy):

```pascal
LProfile.DFTin     := SOC(..., TaperPercent=5, Time=WindowLength, ...);
LProfile.PDSin     := AutoSpectrum(LProfile.DFTin, 3, Time);
LProfile.PDSin     := Resample(LProfile.PDSin, 1/WindowLength, NewRes=0.01, false);
LProfile.PDSin_BCK := copy(LProfile.PDSin);    // pre-MAW snapshot
LProfile.PDSin     := MAW(LProfile.PDSin, [1,1,1]/3, false);  // display only
```

**spectHR** — `compute_carspan_psd_strict(smooth=False)` already
delivers the post-Resample, pre-MAW grid (the equivalent of
`PDSin_BCK`). `_psd_carspan_native` is the helper that calls it.

**Action**: none. Replace `view.band_powers(method=method)` in the
profile loop with a direct call to `_psd_carspan_native(win_view,
method)` so the per-window grid is exactly the resampled-but-unsmoothed
one, no detour through the mixin's display-side smoother.

---

## 4. Step 3 — Per-window respiration-frequency estimate (CARSPAN's `MeanIn`)

**Pascal** (`RunProfileSommation` 2941-2954, the first pass that builds
`FRespFreqList`):

```pascal
LProfile := LAData.GetSegment(Sindex).GetProfile(Pindex);
If (LAData.FSpecAna.FTSIn.Name = 'RespPeriod') And (FTSOut.Name = '') Then
 Begin
  TmpRespFreqObject1.FRespFreq    := 1 / LProfile.MeanIn;
  TmpRespFreqObject1.FRespFreqMax := (LProfile.PDSin_BCK.Count-1) * FreqRes;
  FRespFreqList.Add(TmpRespFreqObject1);
 End;
```

CARSPAN feeds its own respiration channel called `RespPeriod` (the
inter-breath interval series in seconds) and reads `1/mean(period)` as
the per-window resp frequency. spectHR doesn't carry a `RespPeriod`
series, but **it does** carry phase-segmented breath cycles in
`PhysioData.rsp_map[band] : RespirationSeries` (built from the
accelerometer / chest-belt signal). Each cycle has `starts[i]` and
`ends[i]` — one full breath = inhale + the following exhale (or vice
versa).

**Action**: write a small helper on `RespirationSeriesView` (the
windowed view we already have) that returns the per-window resp
frequency:

```python
def mean_breath_frequency_hz(self) -> float | None:
    """Mean breath frequency in Hz inside this view.

    Reconstructs full breath cycles by pairing successive INH→EXH (or
    EXH→INH) phases and averaging `1 / cycle_duration`. Returns
    ``None`` when fewer than one full cycle falls inside the window.
    """
```

Then inside `band_power_profile`, for each window:

```python
rsp_view = self._respiration_view_for_window(win_start, win_end)
resp_freq = rsp_view.mean_breath_frequency_hz() if rsp_view else None
resp_freq_max = float(psd_result.freqs[-1])  # Nyquist of the strict grid
```

`_respiration_view_for_window` is a thin wrapper that picks
`self._pd.rsp_map` (only one band in practice) and calls
`.view(win_start, win_end)`. When no respiration series is loaded,
`resp_freq` stays `None` and the band-edge logic in step 4 falls back
to the static configuration — exactly what CARSPAN does when
`FRespFreqList.Count = 0`.

---

## 5. Step 4 — Respiration-aware band edges

**Pascal** (`RunProfileSommation` 2989-2998 + the two helpers at
2837-2884):

```pascal
If (FRespFreqList.Count <> 0) Then Begin
  TmpMinValue := GetRespirationMinBandValue(RespFreq, RespFreqMax, AnaBand);
  TmpMaxValue := GetRespirationMaxBandValue(RespFreq, RespFreqMax, AnaBand);
End Else Begin
  TmpMinValue := AnaBand.Min;
  TmpMaxValue := AnaBand.Max;
End;
```

```pascal
Function GetRespirationMinBandValue(ARespFreq, AFreqMax: Double; AAnaBand): Double;
 If AAnaBand.RespirationBand Then
   If AAnaBand.Min > AFreqMax Then Result := AFreqMax
   Else If (ARespFreq - AAnaBand.Min) < 0.01 Then Result := 0.01
   Else Result := ARespFreq - AAnaBand.Min
 Else Result := AAnaBand.Min;

Function GetRespirationMaxBandValue(ARespFreq, AFreqMax: Double; AAnaBand): Double;
 If AAnaBand.RespirationBand Then
   If ARespFreq + AAnaBand.Max > AFreqMax Then Result := AFreqMax
   Else Result := ARespFreq + AAnaBand.Max
 Else Result := AAnaBand.Max;
```

So when a band is marked `RespirationBand=True`, CARSPAN treats
`AnaBand.Min` and `AnaBand.Max` as **±widths around the resp
frequency**, not absolute Hz edges. A band configured as
`Min=0.04, Max=0.04, RespirationBand=True` with `RespFreq=0.27 Hz`
becomes `[0.23, 0.31] Hz` for that window.

**Action**:

1. Extend `BandSpec` in `spectHR/Tools/PSD/_band_spec.py` (or wherever
   it lives) with a new flag:

   ```python
   @dataclass(frozen=True)
   class BandSpec:
       low:  float
       high: float
       respiration_band: bool = False   # new
   ```

   Backwards-compatible: existing static bands stay `False`.

2. Add the two clamp helpers next to `BandSpec`:

   ```python
   def respiration_min(band: BandSpec, resp_freq: float,
                       freq_max: float) -> float:
       if not band.respiration_band:
           return band.low
       if band.low > freq_max:
           return freq_max
       return max(0.01, resp_freq - band.low)

   def respiration_max(band: BandSpec, resp_freq: float,
                       freq_max: float) -> float:
       if not band.respiration_band:
           return band.high
       return min(freq_max, resp_freq + band.high)
   ```

   These are direct ports — same `0.01 Hz` floor, same `freq_max` cap,
   same "treat band.low/high as half-widths" interpretation.

3. In the per-window loop, derive `(lo, hi)` once per band:

   ```python
   if resp_freq is not None:
       lo = respiration_min(band, resp_freq, resp_freq_max)
       hi = respiration_max(band, resp_freq, resp_freq_max)
   else:
       lo, hi = band.low, band.high
   ```

---

## 6. Step 5 — Band-power integration

**Pascal** (`Calculate_Energy` 819-850, fed `PDSin_BCK`,
`FreqRes = 1/WindowLength`, `d = sqr(MeanIn)`):

```pascal
LowerBand  := min(LowerBand, (Spectrum.Count-1)*FreqRes);
UpperBand  := min(UpperBand, (Spectrum.Count-1)*FreqRes);
LowerIndex := round(LowerBand/FreqRes) - 1;     // clamp ≥ 0
UpperIndex := round(UpperBand/FreqRes) - 1;     // clamp ≤ Count-1
Result     := 0;
for index := LowerIndex to UpperIndex do
  Result := Result + Double(Spectrum[index]^);
Result := Result * FreqRes;
if AModIdx then Result := Result / d;           // sqr(MeanIn)
if ALogarithmic then Result := Ln(Result);
```

Two CARSPAN-isms to note:

- The integration uses `FreqRes = 1/WindowLength` even though the
  spectrum was already binned to the `NewRes = 0.01 Hz` display grid.
  This is a Pascal quirk that effectively under-counts band power by
  the ratio `NewRes / (1/WindowLength)`. spectHR's
  `band_power_rectangular` does it cleanly with the actual bin width.
- The mMI² conversion (`Result / d`) duplicates what spectHR already
  does in `_carspan_display` at the PSD level — applying it once at the
  PSD step and integrating the converted spectrum gives the same
  number as integrating the raw spectrum and dividing once at the end.

**Action**:

- **Default path**: keep `band_power_rectangular(freqs, power, lo, hi)`
  for cleaner integration. This is mathematically correct and matches
  what we already do for the whole-epoch `band_powers()`.
- **(Optional) `pascal_strict` path**: add a `integration: Literal[
  "rectangular", "pascal_strict"] = "rectangular"` knob on `PsdMethod`
  (carspan-strict only). When `"pascal_strict"`, replicate
  `Calculate_Energy` byte-for-byte — `FreqRes = 1/window_s`, index
  formula `round(f/FreqRes)-1`, no mMI² double-conversion. Use only
  for bit-exact CARSPAN reproduction.

---

## 7. Step 6 — Output unit, NaN sentinel, `ProfileResult` assembly

**Pascal**: appends each `Result` to `LBandData.PDSin` and is done —
the values are already in mMI² (or mMI² Ln) per window.

**spectHR** today:

- Stores NaN when the window has fewer than 4 R-peaks (`win_view.times.size < 4`).
- Strips `/Hz` from the PSD unit to get the band-power unit (`mMI²` etc.).
- Packs everything into `ProfileResult(timestamps, band_names, band_power, unit, method, window_s, step_s)`.

CARSPAN doesn't have a NaN sentinel — it simply skips windows with
`Count = 0`. Keeping spectHR's NaN keeps downstream plotting code
happy; it doesn't change the numbers, just lets sparse windows survive
the integer indexing into `band_power`.

**Action**: leave the NaN behaviour, leave the unit detection, leave
the `ProfileResult` shape. Just rewire the inside of the per-window
loop to call the three new helpers from steps 3-5.

---

## 8. Step 7 — Stitch it together

After steps 2-6, the new `band_power_profile` body looks like:

```python
method = self._resolve_method(psd_method)
# … existing validation, n_windows, grid alloc …

# One read of the respiration map per call.
rsp_series = None
if self._pd is not None and self._pd.rsp_map:
    # CARSPAN only consults one channel; we use the first.
    rsp_series = next(iter(self._pd.rsp_map.values()))

for i in range(n_windows):
    win_start = t0 + i * step_s
    win_end   = win_start + window_s
    timestamps[i] = win_start + window_s / 2.0
    win_view = self.view(win_start, win_end)
    if win_view.times.size < 4:
        continue

    # Step 2 — per-window strict CARSPAN PSD on the resampled grid.
    try:
        psd_result = self._psd_carspan_native(win_view, method)
    except Exception:
        continue

    # Step 3 — per-window resp freq (None if no respiration series).
    resp_freq = None
    resp_freq_max = float(psd_result.freqs[-1])
    if rsp_series is not None:
        rsp_view = rsp_series.view(win_start, win_end)
        resp_freq = rsp_view.mean_breath_frequency_hz()

    # Step 4-5 — per-band clamp + integrate.
    for b, (name, band) in enumerate(method.bands.items()):
        if resp_freq is not None:
            lo = respiration_min(band, resp_freq, resp_freq_max)
            hi = respiration_max(band, resp_freq, resp_freq_max)
        else:
            lo, hi = band.low, band.high
        grid[b, i] = band_power_rectangular(
            psd_result.freqs, psd_result.power, lo, hi
        )

    # Unit auto-detect — same heuristic as today, on the first window.
    if not unit:
        unit = _strip_per_hz(str(psd_result.unit))

return ProfileResult(
    timestamps=timestamps,
    band_names=list(method.bands.keys()),
    band_power=grid,
    unit=unit,
    method=method.algorithm,
    window_s=float(window_s),
    step_s=float(step_s),
)
```

`_strip_per_hz` is the same one-liner that already lives in
`PSDPlotWidget._strip_per_hz` — lifting it to `_psd_utils.py` keeps the
mixin from re-implementing it.

---

## 9. Step 8 — Tests

The existing test suite in `tests/test_hrv_metrics.py` exercises
`band_power_profile` against fixed bands. New coverage:

1. **No respiration loaded** — output is bit-identical to today's
   output (regression-style test against a stored CSV).
2. **Respiration-aware band, no respiration series** — falls back to
   `band.low/high` exactly (so loading a respiration-flagged band on a
   subject without a respiration channel behaves predictably).
3. **Respiration-aware band, synthetic respiration at 0.25 Hz** — the
   resp-band edges should land at `(0.25 - band.low, 0.25 + band.high)`
   clamped to the spectrum's Nyquist; band power should track the
   spectral peak that's planted at 0.25 Hz.
4. **Pascal-strict integration (if implemented)** — feed a 60 s window
   with a known sinusoidal IBI; check the band power agrees with
   CARSPAN's `Calculate_Energy` to within 1 % (allowing for the
   `FreqRes` quirk).
5. **All-NaN window survives** — feed a window that contains no
   R-peaks; the corresponding column of `band_power` is all-NaN and
   the rest of the profile is unaffected.

The first test in particular pins the current behaviour before the
port, so the rewire of the loop body is provably non-breaking for
existing recordings.

---

## 10. Out of scope

For the avoidance of doubt, the port deliberately ignores:

- All blood-pressure code paths (`acFBPModIdx`, `acFBPDM`,
  `acDBP*` calculations elsewhere in `T_AnaFunctions.pas`).
- `LProfile.PDSout_BCK`, `LProfile.CrsSp`, `Coherence`, `Modulus`,
  `Phase`, `Phase2`, and the entire `RunCrossSpectrum`/`RunTransfer`
  chain.
- The `OUT` signal in general — spectHR's HRV-only context has no
  second input.
- The mMI² *vs.* mMI² Ln (`acLn`) presentation switch — that lives
  upstream of band power in spectHR (the user toggles it on the plot
  widget).
- The Pascal `WeightedCoherence` path that mixes coherence into PDS_CH1.

Everything inside that scope can be deleted from the port without
losing CARSPAN-equivalence for the HRV-only profile output.
