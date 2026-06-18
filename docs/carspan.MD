# CARSPAN Technical Reference for spectHR Developers

**Scope.** This document is a technical reference for developers working on
spectHR who need to understand what the original CARSPAN Delphi/Pascal program
does and how spectHR maps onto it. British spelling throughout. Source material:
Delphi 7 sources at `G:\My Drive\CARSPAN\SourcesArie\Delphi7sources\Carspan\Src\`,
the PreCarNFF Visual Basic module, and the spectHR Python implementation at
`src/spectHR/`.

---

## 1. Overview

CARSPAN (CARdiac SPectral ANalysis) is a Windows desktop application for
time-domain and frequency-domain analysis of cardiac (HRV), blood-pressure, and
respiration signals. Its primary inputs are an event file (`.EVT`, text, one row
per R-peak or event marker) and an optional continuous-data file (`.NFF`, binary
multi-channel, or any supported variant). The analysis produces three output
files:

- `*_Summary.out` -- human-readable summary per block/period with band energies
  and means.
- `*_Numerical.out` -- fixed-width columnar file intended for import into
  statistics software; one row per spectral analysis per segment per pass
  (ACTindex 1..5).
- `*_Profiles.pro` -- INI-like sliding-window profile file, one row per profile
  step.

### High-level data flow

```
EVT file + NFF file
        |
    TEventFile.ProcessEventFile / ProcessDataFile
        |  (reads markers, IBI columns, sampled channels)
    TEventFile.AutoCorrect / ManualCorrect
        |  (artefact detection and IBI replacement via TDataCorrect)
    TEventFile.AnaFunctions.RunAnalysis
        |
        +-- RunDFT       (SOC for all channels, all segments/profiles)
        +-- RunCrossSpectrum
        +-- RunPDS       (auto-spectra)
        +-- RunResample  (bin-average to 0.01 Hz display grid; epoch path only)
        +-- RunMAW       (3-point triangular smoother on display spectra)
        +-- RunTransfer  (H = Cross/Auto, Modulus, Phase, UnwrapPhase, Coherence)
        +-- RunModIdx    (optional modulation-index normalisation)
        +-- RunProfileSommation  (band-power summary per profile step; profile path only)
        |
    TOutput.CreateSpectralFunctionsSummary / CreateSpectralFunctionsNumerical
    TOutput.CreateSpectralProfilesProfile
```

Two analysis modes exist and are mutually exclusive within a single invocation
(controlled by `FViewProgressAnalysis.Tag`):

- **Spectral functions** (Tag = 0): one spectrum per epoch segment. Resamples to
  0.01 Hz grid, then applies 3-point smoother and transfer functions.
- **Spectral profiles** (Tag != 0): sliding-window spectra within each epoch.
  Does NOT resample to 0.01 Hz; uses `WindowSize=3` (3-point triangular) in
  `AutoSpectrum` / `CrossSpectrum` directly.

---

## 2. Data model

### 2.1 TDataCol (`T_DataCol.pas`)

The atomic column of data, representing one time series.

| Field | Type | Meaning |
|---|---|---|
| `Index` | Integer | Position in EventFile.DataCols list |
| `Name` | string | e.g. `"RPeaks"`, `"IBI"`, `"SBP"`, `"Resp"` |
| `ChannelKind` | TTimeSerieKind | enum: tkRPEAKS, tkIBI, tkIBIINVERSE, tkBPSYS, tkBPDIA, tkBPPUL, tkBPMPR, tkRESMVO, tkRESSVO, tkRESPVO, tkPRECOMP, tkECGTWAVE |
| `ScaleFactor` | Double | calibration multiplier (from NFF header) |
| `ZeroLevel` | Double | calibration offset |
| `ResSamples` | Integer | window width for sampled respiration |
| `OldData` | TList | raw values as loaded from file |
| `NewData` | TList | values after applying corrections |
| `OrgData` | TList | original precomputed values (precomp columns only) |
| `CorData` | TList | list of TDataCor correction objects |
| `RPDataCol` | TDataCol | pointer to the R-peaks column |
| `IBIDataCol` | TDataCol | pointer to the IBI column |

The special column for R-peaks (`tkRPEAKS`) holds event times in milliseconds.
The IBI column (`tkIBI`) holds inter-beat intervals in milliseconds, derived by
`CalcIBI`. The IBI-inverse column (`tkIBIINVERSE`) is `1000/IBI` (instantaneous
heart rate in beats/s), computed on demand.

`OldData` is never modified after load. All corrections are accumulated as
`TDataCor` objects in `CorData` and merged into `NewData` via `RefreshNewData`.

### 2.2 TDataCor (`T_DataCor.pas`)

One correction record on a `TDataCol`.

| Field | Type | Meaning |
|---|---|---|
| `NewData` | TList | replacement values |
| `TimeB` | Double | start time of corrected segment (ms) |
| `TimeE` | Double | end time of corrected segment (ms) |
| `Accepted` | Boolean | whether the correction is active |
| `Kind` | TCorKind | SHORT, LONG, SHORT-LONG, SHORT-LONG-SHORT, SHORT-NORMAL-SHORT, COMPLEX, SPECIAL, AUTO, MANUAL, DELETE, PRECOMP, NONE |

### 2.3 TProfile (`T_AnaData.pas`)

One frequency-domain result container, corresponding to a single analysis
window within one segment. Holds:

| Field | Type | Meaning |
|---|---|---|
| `DFTin` | TList | complex DFT result for the input channel |
| `DFTout` | TList | complex DFT result for the output channel |
| `PDSin` | TList | auto-spectrum (real, after smoother) for input |
| `PDSout` | TList | auto-spectrum for output |
| `PDSin_BCK` | TList | auto-spectrum backup before MAW smoother |
| `PDSout_BCK` | TList | auto-spectrum backup before MAW smoother |
| `CrsSp` | TList | complex cross-spectrum |
| `Coherence` | TList | squared coherence |
| `Modulus` | TList | transfer modulus |
| `Phase` | TList | unwrapped phase |
| `Phase2` | TList | wrapped phase (second copy, not mutated by UnwrapPhase) |
| `MeanIn` | Double | mean of the input signal (IBI in ms, or raw units) |
| `VarIn` | Double | variance of the input signal |
| `MeanOut` | Double | mean of the output signal |
| `VarOut` | Double | variance of the output signal |
| `LowerLimit` | Double | effective lower band limit (after clipping to spectrum length) |
| `UpperLimit` | Double | effective upper band limit |

### 2.4 TSegment (`T_AnaData.pas`)

Contains a list of `TProfile` objects (one per profile step or just one for
epoch analyses) and a list of `TProfile` band-data objects (one per frequency
band, used in the profile path to accumulate band-power time series).

### 2.5 TAData (`T_AnaData.pas`)

One complete spectral analysis specification with its results. Holds:

- `FSpecAna` -- a `TSpecAna` describing input/output channels, bands, and
  which derived quantities (coherence, modulus, phase, modulation index, log)
  to compute.
- `FSegments` -- list of `TSegment`, one per epoch segment.
- `SameIn`, `SameOut` -- pointers to other `TAData` objects that have already
  computed the same DFT for the input or output channel (avoids redundant DFT
  work when multiple analyses share a channel).
- `FMean`, `FBlock`, `FPeriod` -- bookkeeping for output.

### 2.6 TAnaData (`T_AnaData.pas`)

Top-level container owned by `TEventFile`, with two lists:

- `FSpectra` -- list of `TAData` objects for spectral-function analyses.
- `FProfiles` -- list of `TAData` objects for spectral-profile analyses.

### 2.7 TSpecAna (`T_SpecAna.pas`)

Describes one analysis pair (input channel, optional output channel, bands,
calculations).

| Field | Type | Meaning |
|---|---|---|
| `FName` | string | analysis name |
| `FTSIn` | TTimeSerie | input channel specification |
| `FTSOut` | TTimeSerie | output channel (empty for power-only) |
| `FACalcs` | TAnaCalcs | set of: acModIdx, acMean, acVarCoef, acCoherence, acModulus, acPhase, acLn |
| `FMinCoh` | Double | minimum coherence threshold for modulus/phase gating |
| `FBands` | TList | list of TAnaBand records |

### 2.8 TSpecAnaSet (`T_SpecAnaSet.pas`)

A collection of `TSpecAna` objects (either power spectra or transfer functions)
plus the segment definition and band list. Holds:

- `FASPower` -- list of `TSpecAna` for auto-spectrum analyses.
- `FASTrans` -- list of `TSpecAna` for cross-spectrum/transfer analyses.
- `FBands` -- list of `TAnaBand` records.
- `FSegment` -- `TAnaSegment` describing how to slice the data.
- `FSaveUnsmoothed` -- whether to save pre-MAW spectra.
- `FPlotUnsmoothed` -- whether to plot pre-MAW spectra.

### 2.9 TSpecAnalysis (`T_SpecAnalysis.pas`)

Combines two `TSpecAnaSet` objects (FAnaFunctions for epoch analyses,
FAnaProfiles for profile analyses) with a list of `TTimeSerie` records defining
which channels are available. Validates that all channel references in the
`TSpecAnaSet` refer to available time series.

### 2.10 TAnaSegment (record, `T_CarspanGlobals.pas`)

Defines how the data is segmented.

| Field | Type | Meaning |
|---|---|---|
| `Kind` | TAnaSegmentKind | skPeriodsCodes, skPeriodsTime, skBlocks |
| `Time` | Integer | fixed period length in seconds (skPeriodsTime) |
| `WindowLength` | Integer | profile window length in seconds |
| `StepSize` | Integer | profile step size in seconds |
| `AdjustPeriodTime` | TAdjustPeriodTimeKind | apIncrease, apDecrease, apDismiss |

### 2.11 TAnaBand (record, `T_CarspanGlobals.pas`)

| Field | Type | Meaning |
|---|---|---|
| `Name` | string | e.g. "VLF", "LF", "HF" |
| `Min` | Double | lower band edge in Hz |
| `Max` | Double | upper band edge in Hz |
| `Accepted` | Boolean | whether the band is valid for the current segment length |
| `Used` | Boolean | whether the band is currently selected |
| `RespirationBand` | Boolean | if True, band limits are relative to measured respiration frequency |

### 2.12 TEventFile (`T_EventFile.pas`)

The main session object. Owns:

- `DataCols` -- list of all `TDataCol` objects.
- `Markers` -- all event markers (R-peaks, block/period codes, user codes).
- `BlockAreas`, `PeriodAreas` -- derived area lists from markers.
- `AnaSpecs` -- `TSpecAnalysis` (analysis configuration).
- `AnaFunctions` -- `TAnaFunctions` (algorithm implementation).
- `AnaData` -- `TAnaData` (results container).
- `StanCodes` -- `TStandardCodes` (integer codes for RPeak, BOB, EOB, BOP, EOP).
- `CorSpecs` -- `TCorSpecs` (correction parameters).
- `ExperimentNr`, `SubjectNr`, `TextLine`, `Created`, `Origin` -- file metadata.

### 2.13 TTimeSerie (record, `T_CarspanGlobals.pas`)

| Field | Type | Meaning |
|---|---|---|
| `Accepted` | Boolean | is the channel available |
| `Name` | string | display name |
| `Kind` | TTimeSerieKind | see above |
| `EvtColumn` | Integer | column index for precomputed series in EVT file |
| `Channel` | Integer | channel number in NFF file |
| `ScaleFactor` | Double | from NFF calibration |
| `ZeroLevel` | Double | from NFF calibration |
| `ResSamples` | Integer | window for sampled respiration |

---

## 3. File formats

### 3.1 EVT file

The `.EVT` file is a plain-text fixed-column file. The first few lines are a
header:

```
TextLine      (free-form description, up to ~80 chars)
Created date
Origin (author/system)
[blank lines and optional metadata]
[Data]
```

Each data row has two or more fixed-width columns:

```
<EventCode>  <TimeStamp_ms>  [<Column2>  <Column3> ...]
```

- `EventCode` is an integer (e.g. the RPeak code, typically 1 or user-defined).
- `TimeStamp_ms` is event time in milliseconds.
- Additional columns (3..N) are precomputed time series values (blood pressure
  systolic, diastolic, pulse, mean; respiration; IBI; etc.), one value per
  R-peak event. These are stored in `TDataCol` objects with `EvtColumn` indices.

Standard codes (read from the session specification or from a `.ini` settings
file):

| Name | Meaning |
|---|---|
| RPeak | Code for an R-peak (cardiac event) |
| Bob (Begin of Block) | Start of an experimental block |
| Eob (End of Block) | End of an experimental block |
| Bop (Begin of Period) | Start of an analysis period |
| Eop (End of Period) | End of an analysis period |

All other codes are user-defined and stored in `UserCodes`. R-peaks read from
the file are loaded into the `OldData` list of the RPeaks `TDataCol`, with their
time stamps in milliseconds. The IBI column is derived by differencing consecutive
R-peak times (`CalcIBI`).

### 3.2 NFF file

NFF (New File Format) is a binary multi-channel file used by the CARSPAN/VU-AMS
ecosystem. Structure:

**General header (512 bytes, 256 words):**

| Offset (words) | Field | Meaning |
|---|---|---|
| 0 | NFF_ID | 4 chars "NFF " |
| 1 | Version | SmallInt, = 1 |
| 2..3 | Header sizes | general=256 words, channel=128 words |
| 4..6 | Creation date | day, month, year |
| 7..9 | Creation time | hour, minute, second |
| 10 | ms | millisecond |
| 13 | Nchans | number of channels |
| 14 | ADres | AD resolution in bits |
| 32..35 | Tstart | start time in ms (32-bit) |
| 33 | Ntrials | number of trials |
| 34 | Ttrial | trial length in ms |
| 35 | Tblock | block length in ms |
| 58..65 | OrgName | original filename (16 chars) |
| 66..73 | EvtName | event filename (16 chars) |
| 74..81 | InfoName | info filename (16 chars) |
| 82..121 | sComment | comment (80 chars) |
| 122..241 | sInfo | info (240 chars) |

**Channel header (256 bytes, 128 words) per channel:**

| Offset (32-bit longs) | Field | Meaning |
|---|---|---|
| 0 | zero_man, zero_exp | zero = zero_man x 10^zero_exp |
| 2 | scale_man, scale_exp | scale = scale_man x 10^scale_exp |
| 4 | Tsample | sample period in microseconds |
| 5 | Nsample | number of samples |
| 6 | Nsampblk | samples per block (= 512) |
| 7 | iOffset | block offset in samples |

**Data:** blocks of 512 signed 16-bit integers per channel, interleaved.
Physical value = (raw * ScaleFactor) + ZeroLevel, where ScaleFactor and
ZeroLevel are derived from the scale/zero mantissa and exponent fields.

`TNFF.GetChannelData(ChannelNr)` returns a `PDynArray` (pointer to a dynamic
SmallInt array) of all samples for the channel. `GetInterval(ChannelNr)` returns
the sample period in milliseconds.

### 3.3 PreCarNFF VB module (`NFF.bas`)

This is a Visual Basic 6 reference implementation of NFF reading (`OpenNFF_File`,
`ReadNFFData`). Its `NFF_GeneralHeader` and `NFF_ChannelHeader` type definitions
are the authoritative layout documentation for the format. The Delphi TNFF class
maps 1:1 to this layout. No analysis is performed in this module; it is a file
I/O helper only.

---

## 4. Preprocessing and data correction

### 4.1 TCorSpecs (record, `T_CarspanGlobals.pas`)

| Field | Default | Meaning |
|---|---|---|
| `TWL` | 60 s | time-window length for running statistics |
| `NCor` | 10 | maximum number of erroneous values for auto-correction |
| `NSD` | 5.0 | maximum allowed standard deviations from mean |
| `MinSD` | 0.05 | minimum accepted standard deviation |
| `MaxSD` | 0.15 | maximum accepted standard deviation |
| `NSucD` | 5.0 | maximum allowed successive-difference deviations |
| `MinSucD` | 0.05 | minimum accepted successive difference |
| `MaxSucD` | 0.25 | maximum accepted successive difference |

These defaults come from `CarspanDefaultSettings.ini`, section `[Corrections]`.

### 4.2 TDataCorrect (`T_DataCorrect.pas`)

The auto-correction engine. Method `AutoCorrect(CorData, RPData, CorSpecs,
IsRPCor)` runs:

1. **CheckFirstWindow** -- sorts the first time-window of values, finds the
   median (centre index), and computes robust limits:
   `LimitL = median - 6 * (median - Q25)`, `LimitU = median + 6 * (Q75 - median)`.
   Values outside these limits are flagged `Exclude=True` and excluded from
   running statistics.

2. **RunSinglePass** -- iterates over all values. For each value, calls either
   `CheckRPValue` (IBI/RPeaks path, `IsRPCor=True`) or `CheckTSValue` (other
   time series). The check:
   - Maintains a running time-window of length `TWL` via
     `SetRunningTimeWindow`, updating `FTWIdxB`/`FTWIdxE`.
   - Maintains a running mean and standard deviation over non-excluded values
     within the window via `SetRunningMeanAndStdDev`.
   - For R-peaks: classifies as `vkSHORT` if `value < mean - NSD * sd` or
     `value < MinSD`, classifies as `vkLONG` if `value > mean + NSD * sd` or
     `value > MaxSD`. Also checks successive differences against `NSucD * sucDev`.
   - For other time series: similar classification using `vkSHORT` (LOW) /
     `vkLONG` (HIGH).

3. **ProcessCorrections** -- scans the tagged list to find runs of
   SHORT/LONG/NORMAL patterns. Identifies the pattern type via `CheckErrKind`
   (produces one of: ckSHORT, ckLONG, ckSHORTLONG, ckSHORTLONGSHORT,
   ckSHORTNORMALSHORT, ckCOMPLEX). For patterns up to `NCor` consecutive
   erroneous values, creates a `TDataCor` object with interpolated replacement
   values via `InterPolate(IdxB, IdxE, FixValCount, AddValues)`.

   `InterPolate` linearly interpolates between the boundary normal values.
   `AddValues` is 0 for SHORT patterns (no inserted beats) and the required count
   for LONG patterns (extra beats inserted, typically 1 for ckLONG).

4. After `AutoCorrect`, the corrections are returned via `TakeFirstCorrection`
   and applied to the `TDataCol` via `AddColCorrection` and `RefreshColNewData`.

**Manual correction** (`ManualCorrect`) works identically but takes explicit
`IdxB`, `IdxE`, `FixValCount`, `AddValues` from the user. Delete corrections
(`IsDelete=True`) replace the range with the boundary value repeated.

---

## 5. Spectral analysis pipeline

All spectral analysis lives in `TAnaFunctions` (`T_AnaFunctions.pas`). The key
constant `NewRes = 0.01` defines the target display grid resolution in Hz.
`TaperPercent` is hardcoded to 5 inside `RunDFT`.

### 5.1 Taper (procedure `Taper`)

Applied once to each mean-subtracted (or unit-weight) signal before the DFT.

```
NrOfTaperSmp = max(1, round(TaperPercent * N / 100))
Fac = pi / (2 * NrOfTaperSmp)

For LeftSmp = 1 to NrOfTaperSmp:
    RightSmp = N - LeftSmp
    FArg = LeftSmp * Fac
    FCos = cos(FArg)    [except FCos = 0 when LeftSmp = NrOfTaperSmp]
    FMult = 1 - FCos^2
    Data[LeftSmp-1]  *= FMult
    Data[RightSmp]   *= FMult
```

This is a cosine-bell (raised-cosine) taper, often called a split-cosine-bell or
Tukey window. With `TaperPercent=5` and an epoch of N samples, 5% of both ends
are tapered. The formula `1 - cos^2(x) = sin^2(x)` so each sample `i` (1-based)
receives weight `sin^2(i * pi / (2 * NrOfTaperSmp))`. Note: sample index 0
receives weight `sin^2(Fac)` -- NOT zero -- because the loop uses `LeftSmp`
(1-indexed) as the argument, not `LeftSmp - 1`. This is the "CARSPAN index" taper.

### 5.2 SOC (function `SOC`) -- the core DFT

`SOC(IBIDataCol, DataCol, IsRPDataCol, RPColIndex, TaperPercent, Time, Mean, Variance)`

`Time` = time span of the segment in ms = `RPDataCol.Last - RPDataCol.First`.
`df = 1 / Time` (in units consistent with time).
`DFArg = 2 * pi * df`.
`DeltaT = Time / (N_IBI - 1)` = mean IBI.
`Fs = 1 / DeltaT` = mean heart rate.
`MaxPnt = floor(Fs * 0.5 / df) = floor(N/2)` roughly.

**Path 1: IsRPDataCol=True (R-peak / IBI path, Equation 3.19)**

```
NData[i] = 1   (unit amplitude)
Mean = sum(1/IBI[i]) / N         (mean HR in beats/ms)
Variance = sum((1/IBI[i])^2) / N - Mean^2

Taper(NData, TaperPercent)

For FreqPoint = 0 to MaxPnt-1:
    Result[FreqPoint] = 0+0j

For IBI = 0 to N-1:
    T += IData[IBI]           (cumulative R-peak time in ms)
    ExpT += DeltaT            (expected cumulative time at mean rate)

    ArgIBI = ExpT * DFArg     (DFArg = 2*pi*df = 2*pi/Time)
    ZIBI = cos(ArgIBI) - j*sin(ArgIBI)
    AIBI = ZIBI               (reference phasor at expected time)

    Arg = T * DFArg
    Z = cos(Arg) - j*sin(Arg) (phasor at actual time, for freq bin 0)
    A = Z

    Amp = NData[IBI]          (= tapered unit weight)

    ADif = A - AIBI           (deviation from expected phasor)

    For FreqPoint = 0 to MaxPnt-1:
        Result[FreqPoint] += ADif * Amp
        A    = A    * Z       (advance actual phasor by df)
        AIBI = AIBI * ZIBI    (advance expected phasor by df)
        ADif = A - AIBI
```

The subtraction of the expected phasor (AIBI from ZIBI) is the DC-removal step:
it subtracts the contribution of a perfectly regular impulse train at the mean
rate, removing spectral leakage at very low frequencies.

**Path 2: IsRPDataCol=False (arbitrary time series, Equation 3.21)**

```
NData[i] = DataCol[i]           (raw values, e.g. IBI ms, or BP mmHg)
Mean = sum(NData) / N
Variance = sum(NData^2)/N - Mean^2
NData[i] -= Mean                (mean subtraction)

Taper(NData, TaperPercent)

Amp = NData[IBI] * IData[IBI] / 1000   (mean-subtracted value * IBI_s)

ADif = A - AIBI = A - 0 = A    (AIBI = 0 for this path)

For FreqPoint = 0 to MaxPnt-1:
    Result[FreqPoint] += A * Amp
    A = A * Z
```

Note: in Path 2 ZIBI and AIBI are both zero, so `ADif = A` always. The
amplitude is the mean-subtracted channel value multiplied by the IBI duration in
seconds. This is a weighted DFT on the IBI time grid -- each sample is placed at
the real cumulative IBI time `T`.

The result `Result[FreqPoint]` is a complex DFT coefficient stored as a `DComplex`
(real + imaginary parts as doubles).

### 5.3 AutoSpectrum (function `AutoSpectrum`)

Computes the power spectral density from a list of complex DFT coefficients.

**WindowSize = 0 (epoch / spectral-functions path):**

```
For each freq bin k:
    PDS[k] = 1000000 * (2 * |DFT[k]|^2 / Time)
           = 2e6 / Time * (Re^2 + Im^2)
```

Units: mMI^2/Hz when applied to the IBI path (Path 1), ms^2/Hz when applied
to Path 2 (before the modulation-index normalisation step). The factor `1000000`
converts `ms^2` to `mMI^2` (milli-squared).

**WindowSize = 3 (profile path):**

Uses a 3-point triangular window centred at the current bin. The window weights
are `[1/3, 2/3, 1]` (normalised by the sum = 2) -- actually CARSPAN's
`CreateWindow` produces `[1*(1/2), 2*(1/2), 1*(1/2)]` for size 3 (MaxPnt=1),
which after normalisation by sum=1 gives `[1/4, 1/2, 1/4]`... Let us read the
Pascal exactly:

```pascal
function TAnaFunctions.CreateWindow(WindowSize, MaxPnt: integer): dVector;
  for index := 0 to MaxPnt do
    VD_PElement(Result, index)^ := (index+1)*(1/(MaxPnt+1));
    VD_PElement(Result, WindowSize-index-1)^ := (index+1)*(1/(MaxPnt+1));
```

For WindowSize=3, MaxPnt=1: indices 0,1,2 get weights:
- index=0: w[0] = 1/2, w[2] = 1/2
- index=1: w[1] = 2/2 = 1

Sum = 0.5 + 1 + 0.5 = 2. Normalised: [0.25, 0.5, 0.25] -- a triangular filter.

For each bin in the profile path, the power is the weighted average over
[bin-1, bin, bin+1] (with edge-mirroring for the first and last bins, and
edge-replication for the final tail).

### 5.4 CrossSpectrum (function `CrossSpectrum`)

**WindowSize = 0 (epoch path):**

```
For each freq bin k:
    Cross[k] = conj(DFT_in[k]) * DFT_out[k] / (T / 2000000)
             = conj(DFT_in[k]) * DFT_out[k] * 2e6 / T
```

The result is complex (a `DComplex`). Units: mMI^2/Hz (when both signals are
IBI-path).

**WindowSize = 3 (profile path):** same 3-point triangular smoother as
`AutoSpectrum` but applied to the complex cross-spectrum, with each element
multiplied by a real window weight.

### 5.5 RunPDS (auto-spectra step, inside `RunAnalysis`)

Calls `AutoSpectrum` with `WindowSize=0` for the spectral-functions path and
`WindowSize=3` for the profile path. The result is stored in `LProfile.PDSin`
and `LProfile.PDSout`.

The factor `1e6 * 2 / T` means:

```
PDS[k]  = 1000000 * 2 / T * |DFT[k]|^2
```

For the IBI channel (Path 1, unit impulses): the raw unit is beats^2/Hz. After
multiplying by mean_ms^2 (in `RunModIdx`) and the 1e6 factor, the result is
mMI^2/Hz.

For other channels (Path 2): the raw unit is (channel_unit * s)^2 / ms, which
simplifies to channel_unit^2/Hz scaled appropriately.

### 5.6 RunResample (spectral-functions path only)

After `RunPDS`, each spectrum is resampled from the native resolution `1/Time`
Hz to the display grid at `NewRes = 0.01` Hz via `Resample_R`.

`Resample_R` is a fractional-coverage weighted bin-averaging:

```
native_df = 1/Time
MAXPNT = floor(N_native * native_df / NewRes)

For IFRQ = 1 to MAXPNT:
    FRQCEN = IFRQ * NewRes
    FRQLOW = FRQCEN - NewRes/2
    FRQHIG = FRQCEN + NewRes/2

    Advance ISAVE until FRQARR[ISAVE] >= FRQLOW
    IFIRST = max(1, ISAVE-1)
    Advance ISAVE until FRQARR[ISAVE] >= FRQHIG
    ILAST  = min(ISAVE, N_native - 1)

    if FRQARR[IFIRST] < FRQLOW:  FFACL = (FRQARR[IFIRST+1] - FRQLOW) / native_df
    else:                         FFACL = 1

    if FRQARR[ILAST] > FRQHIG:   FFACH = (FRQHIG - FRQARR[ILAST-1]) / native_df
    else:                         FFACH = 1

    SUMY = FFACL * Y[IFIRST]
    for idx = IFIRST+1 to ILAST-2:   SUMY += Y[idx]
    SUMY += FFACH * Y[ILAST-1]
    SUMX = FFACL + (ILAST-2 - IFIRST) + FFACH

    Result[IFRQ-1] = SUMY / SUMX
```

The upper-boundary bin `FRQARR[ILAST]` is excluded from the sum (only
`FRQARR[ILAST-1]` contributes via `FFACH`). This is energy-conserving across
adjacent display bins.

For the profile path, `RunResample` is also called but with `OldRes = 1 / WindowLength`
(window length in seconds, not segment length). The CARSPAN manual states the
0.01 Hz interpolation is NOT applied for profiles -- this is contradicted by the
code which does call `Resample` in both paths. The spectHR `CarspanOptions`
`resample_to_display_grid=False` flag correctly skips this for profiles.

The cross-spectrum is also resampled (passing `Complex=True` to `Resample`, which
applies `Resample_R` separately to the real and imaginary parts).

### 5.7 RunMAW (3-point moving-average window)

After resampling, a 3-point uniform moving average is applied to `PDSin`,
`PDSout`, and (complex) `CrsSp`. The window is `[1, 1, 1]` (normalised by sum=3).
Before smoothing, backup copies `PDSin_BCK` and `PDSout_BCK` are created.

The `PDSin_BCK`/`PDSout_BCK` copies are what `RunModIdx` and band-power
integration use (via `Calculate_Energy`). The smoothed `PDSin`/`PDSout` are
used for display only. This means band-power numbers in the output files are
based on the pre-MAW spectrum.

Exception: if `GAnaFunc.FSaveUnsmoothed = False`, the output uses the smoothed
spectra even for band integration.

### 5.8 RunTransfer (transfer function step)

For each spectral analysis with both input and output channels:

```
TransList = Transfer(CrsSp, PDSin)
  where Transfer[k] = CrsSp[k] / PDSin[k]   (complex / real)
  (zero if PDSin[k] = 0)

Modulus[k]  = sqrt(|Transfer[k]|^2) = sqrt(Re^2 + Im^2)
Phase[k]    = arctan2(Im, Re)    [wrapped, stored in Phase]
Phase2[k]   = arctan2(Im, Re)    [second copy, not mutated]
Coherence[k] = |CrsSp[k]|^2 / (PDSin[k] * PDSout[k])
              = (Re^2 + Im^2) / (PDSin * PDSout)   [if denom > 0, else 0]

UnwrapPhase(Phase, thresh=pi, step=2*pi)
```

The `UnwrapPhase` accumulates a `ModFactor` counter:

```
ModFactor = 0
for i = 0 to N-2:
    Dev = Phase[i] - Phase[i+1]      (raw, before modification)
    if Dev >= pi:    ModFactor++
    elif Dev <= -pi: ModFactor--
    Phase[i+1] += ModFactor * 2*pi
```

After `RunTransfer`, `CrsSp` and the DFT lists are freed. `PDSin`/`PDSout` are
resolved from `SameIn`/`SameOut` where applicable (deduplication).

### 5.9 RunModIdx (modulation index step)

If `acModIdx` is in the analysis's `FACalcs` set:

For the RPeaks/IBI channel:
```
d = 1 / mean_ms^2          (= 1 / (mean IBI in ms)^2)
PDS[k] *= d
```

For other channels:
```
d = 1e6 / mean^2
PDS[k] *= d
```

This converts from raw ms^2/Hz to mMI^2/Hz (modulation index squared per Hz).
The same is applied to `PDSin_BCK`/`PDSout_BCK`.

### 5.10 RunProfileSommation (profile path only)

After all per-window spectra are computed, this step summarises each window into
band-power scalars stored in `LBandData`:

For each profile step Pindex, for each band Bindex:

```
LowerBand = LAnaBand.Min   (or respiration-relative if RespirationBand=True)
UpperBand = LAnaBand.Max

BandPDS_in[Pindex]  = Calculate_Energy(acModIdx, acLn, PDSin_BCK, Low, High, FreqRes, d)
BandPDS_out[Pindex] = Calculate_Energy(acModIdx, acLn, PDSout_BCK, Low, High, FreqRes, d)
BandCoh[Pindex]     = Calculate_BandMean(Coherence, Low, High, FreqRes)
BandMod[Pindex]     = Calculate_BandMean(Modulus,   Low, High, FreqRes)
BandPhase[Pindex]   = Calculate_BandMean(Phase,     Low, High, FreqRes)
BandPhase2[Pindex]  = Calculate_BandMean(Phase2,    Low, High, FreqRes)
```

`Calculate_Energy`:

```
LowerIndex = round(LowerBand / FreqRes) - 1   (0-based)
UpperIndex = round(UpperBand / FreqRes) - 1

Energy = sum(PDS[LowerIndex..UpperIndex]) * FreqRes

if acModIdx: Energy *= d
if acLn:     Energy  = ln(Energy)
```

This is rectangular integration: energy = sum * bin_width.

`FreqRes = 1 / WindowLength` for profiles (native grid resolution, no
resampling to 0.01 Hz).

**Respiration-relative bands.** When `LAnaBand.RespirationBand=True`, the band
limits are dynamically adjusted relative to the measured respiration frequency
`FRespFreq`:

```
LowerBound = FRespFreq - LAnaBand.Min   (but at least 0.01)
UpperBound = FRespFreq + LAnaBand.Max   (but at most FreqMax)
```

`FRespFreq` is derived from the mean period of the `RespPeriod` time series
(`1 / LProfile.MeanIn`), computed per profile step when that series is present.

### 5.11 Band-summary statistics for spectral functions

For the spectral-functions output, `Calculate_Energy` is called with the
resampled, pre-MAW `PDSin_BCK` (or `PDSin` if `FSaveUnsmoothed=False`) at
`FreqRes = 0.01` Hz.

`Caluculate_WeightedCoherenceSom` (coherence path, ACTindex=2):

```
Result = sum(Coherence[lo..hi] * PDSin[lo..hi]) / sum(PDSin[lo..hi])
```

`Caluculate_ModulusSum` (modulus path, ACTindex=3) and `Caluculate_PhaseSum`
(phase path, ACTindex=4/5): gate by minimum coherence threshold `FMinCoh`:

```
BEnergy = 0; NrOfPoints = 0
for k = lo to hi:
    if Coherence[k] >= MinCoh:
        BEnergy += Modulus[k]   (or Phase[k])
        NrOfPoints++
if NrOfPoints > 0: BEnergy /= NrOfPoints
```

---

## 6. Output metrics

### 6.1 Numerical file columns (one row per ACTindex per spectral analysis)

The `_Numerical.out` (and `.xls`) file has the following fixed columns:

| Column | Width | Field | Notes |
|---|---|---|---|
| 1 | 2 | ACTindex | 1=PDS, 2=Coherence, 3=Modulus, 4=Phase(unwrapped), 5=Phase(wrapped) |
| 2 | 4 | ExperimentNr | |
| 3 | 4 | SubjectNr | |
| 4 | 3 | BlockIndex+1 | 1-based block number |
| 5 | 3 | PeriodIndex (counter within block) | 1-based |
| 6 | 10.3f | PStartTime | segment start time (ms) |
| 7 | 10.3f | PEndTime | segment end time (ms) |
| 8 | 5 | PLength | segment length in seconds |
| 9 | 5 | NrOfIBI | number of R-peaks minus 1 |
| 10 | 4 | ColInIndex | column index of input channel |
| 11 | 4 | ColOutIndex | column index of output channel (0 if power only) |
| 12 | 10.3f | MeanIn | mean of input signal |
| 13 | 10.3f | sdvc | SD (or VC if acModIdx) of input signal |
| 14 | 10.3f | MeanOut | mean of output signal |

For each frequency band (in order of definition, only `Used` bands):

| Field | Width | Notes |
|---|---|---|
| BEnergy | 12.3f | band power, coherence, modulus, or phase value |
| BCnt | 4 | number of frequency points in band |
| LowLimit | 6.2f | actual lower band limit used |
| HighLimit | 6.2f | actual upper band limit used |

Then all spectral values at each 0.01 Hz bin (14.3f each).

### 6.2 ACTindex meaning

| ACTindex | Data source | Band metric | Description |
|---|---|---|---|
| 1 | PDSin_BCK or PDSin | Calculate_Energy | Band power (mMI^2/Hz or ms^2/Hz) |
| 2 | Coherence, PDSin | Caluculate_WeightedCoherenceSom | Power-weighted mean coherence |
| 3 | Modulus, Coherence | Caluculate_ModulusSum | Mean modulus (coherence-gated) |
| 4 | Phase (unwrapped), Coherence | Caluculate_PhaseSum | Mean unwrapped phase (coherence-gated) |
| 5 | Phase2 (wrapped), Coherence | Caluculate_PhaseSum | Mean wrapped phase (coherence-gated) |

The `sdvc` column:
- When `acModIdx` is set: `sqrt(VarIn) / MeanIn` (coefficient of variation).
- Otherwise: `sqrt(VarIn)` (standard deviation).

### 6.3 Profile file columns (`_Profiles.pro`)

INI-style file. The `[Timeseries]` section maps column numbers to names using
the patterns:

| Prefix | Meaning |
|---|---|
| `Mean_<name>` | mean of the input signal per window step |
| `SD_<name>` or `VC_<name>` | SD or VC per window step |
| `PDS_<BandName>_<name>` | band power profile |
| `MOD_<BandName>_<in>-<out>` | modulus profile |
| `PH1_<BandName>_<in>-<out>` | unwrapped phase profile |
| `PH2_<BandName>_<in>-<out>` | wrapped phase profile |
| `COH_<BandName>_<in>-<out>` | coherence profile |

The `[Data]` section has rows interleaved with event-marker rows. Each data row:

```
<code=99>  <CentreTime>  <col1>  <col2>  ...
```

`CentreTime = ProfileIndex * StepSize + RPDataCol[0] + WindowLength/2`.
Marker rows are written when a marker falls before the current profile step time.

### 6.4 Summary file

Human-readable, not intended for import. Per block/period: lists mean of each
channel, then for each spectral analysis lists band energies and frequency-point
counts.

### 6.5 Time-domain metrics

CARSPAN itself does not compute classical time-domain metrics (SDNN, RMSSD, etc.).
These are purely spectHR additions. CARSPAN only reports: `MeanIn` (mean IBI or
mean of the channel), `VarIn`/`VarOut` (variance), and derived `sdvc`
(SD or VC).

---

## 7. Parameters

All parameters are read by `TProgPar.ReadSettings` from:

- Windows Registry (via `FNVC.Reg`): directories, recent files, FTP errors,
  AutoUpdate flag.
- `CarspanDefaultSettings.ini` (same directory as the executable): spectral and
  correction defaults.

### 7.1 Profile parameters

| Parameter | INI section | Default | Type | Meaning |
|---|---|---|---|---|
| `Profile_WindowLength` | [Profiles] WindowLength | 60 | Integer | sliding window length in seconds |
| `Profile_StepSize` | [Profiles] StepSize | 10 | Integer | step between windows in seconds |

### 7.2 Coherence threshold

| Parameter | INI section | Default | Type | Meaning |
|---|---|---|---|---|
| `Min_Coherence` | [Coherence] Min_Coherence | 0.3 | Double | minimum coherence for modulus/phase gating |

### 7.3 Correction parameters (see Section 4.1)

All in `[Corrections]` section:

| Key | Default | Meaning |
|---|---|---|
| TWL | 60 | Time window length (seconds) |
| NCor | 10 | Max consecutive errors for auto-correction |
| NSD | 5.0 | SD threshold |
| MinSD | 0.05 | Minimum accepted SD |
| MaxSD | 0.15 | Maximum accepted SD |
| NSucD | 5.0 | Successive-difference SD threshold |
| MinSucD | 0.05 | Minimum accepted successive difference |
| MaxSucD | 0.25 | Maximum accepted successive difference |

### 7.4 Frequency bands

Stored in `[FrequencyBands Functions]` and `[FrequencyBands Profiles]`:

```
NrOfBands = 3
Band1_Name = VLF
Band1_Min  = 0.02
Band1_Max  = 0.06
Band2_Name = LF
Band2_Min  = 0.07
Band2_Max  = 0.14
Band3_Name = HF
Band3_Min  = 0.15
Band3_Max  = 0.40
```

Defaults above are the CARSPAN Groningen standard bands (Mulder 1992 tradition).
They differ from the Task Force (1996) bands (VLF <0.04, LF 0.04-0.15,
HF 0.15-0.40).

### 7.5 Derived / hardcoded constants

| Name | Value | Location | Meaning |
|---|---|---|---|
| `NewRes` | 0.01 | `T_AnaFunctions.pas` | display grid resolution in Hz |
| `TaperPercent` | 5 | `RunDFT` | taper percentage (5 % per end) |
| MAW window | [1,1,1] | `RunMAW` | 3-point uniform smoother for display |
| AutoSpectrum profile WindowSize | 3 | `RunPDS` | profile path triangular smoother |
| pi threshold for unwrap | pi | `RunTransfer` | UnwrapPhase thresh |
| step for unwrap | 2*pi | `RunTransfer` | UnwrapPhase step |

### 7.6 Segment kind

| Value | Meaning |
|---|---|
| `skPeriodsCodes` | epochs defined by BOP/EOP marker codes |
| `skPeriodsTime` | epochs defined by fixed time length |
| `skBlocks` | use full experimental blocks as single epochs |

Default from `TSpecAnaSet.InitData`: `skBlocks`.

### 7.7 FSaveUnsmoothed / FPlotUnsmoothed

`FSaveUnsmoothed` (default True): when True, the numerical output uses
`PDSin_BCK` (pre-MAW spectrum) for band-power integration. When False, uses the
smoothed `PDSin`.

`FPlotUnsmoothed` (default False): when True, the spectrum plot shows the pre-MAW
spectrum.

---

## 8. External tool: NFF.bas

**File:** `G:\My Drive\CARSPAN\SourcesArie\PreCarNFF\NFF.bas`

**Language:** Visual Basic 6 / VBA module.

**Purpose:** Read NFF (New File Format) binary multi-channel physiological data
files from Visual Basic programs, including the PreCarspan preprocessing tool.

**Key functions:**

| Function | Purpose |
|---|---|
| `OpenNFF_File(fn, wh)` | Opens the NFF file, reads the general header, fills `NFF_WorkHeader`: `Nchans`, `Fsam` (sample frequency from `Tsample`), `nSamples`, `ChanName()`. Returns Boolean success. |
| `ReadNFFData(...)` | Reads sample data from a specified channel. |

**Structures:**

`NFF_GeneralHeader` and `NFF_ChannelHeader` provide the authoritative byte-level
layout of the NFF format (see Section 3.2 for field details). This is the same
format read by `TNFF` in the Delphi sources. No analysis is performed in this
module.

**Input:** NFF binary file.
**Output:** `NFF_WorkHeader` record with file metadata; sample arrays on request.

---

## 9. spectHR mapping table

| CARSPAN unit / function | spectHR file | spectHR function | Status | Notes |
|---|---|---|---|---|
| `T_NFF.pas` TNFF | `src/spectHR/DataSet/readers/` | NFF reader (via MNE/EDF chain) | Partial | spectHR reads VU-AMS EDF, not raw NFF; T_NFF not directly ported |
| `T_EventFile.pas` ProcessEventFile | `src/spectHR/DataSet/readers/reader_evt.py` | EVT file parser | Ported | |
| `T_DataCol.pas` TDataCol | `src/spectHR/session/samples.py`, `events.py` | `Samples`, `Events` | Ported | Immutable redesign |
| `T_DataCor.pas` TDataCor | `src/spectHR/session/events.py` | correction labels on `Events` | Partial | Functional correction model, no TCorKind taxonomy |
| `T_DataCorrect.pas` AutoCorrect | `src/spectHR/DataSet/preprocessing.py` | `apply_beat_detection` + UI beat editor | Partial | Auto-detect via NeuroKit; manual correction in UI; CARSPAN rolling-window corrector not ported |
| `T_AnaFunctions.pas` Taper | `src/spectHR/analysis/psd/_carspan.py` | `_carspan_taper` | Ported | Bit-for-bit faithful |
| `T_AnaFunctions.pas` SOC (Path 1) | `src/spectHR/analysis/psd/_carspan.py` | `_events_periodogram` | Ported | Eq. 3.19, unit-impulse SOC |
| `T_AnaFunctions.pas` SOC (Path 2) | `src/spectHR/analysis/psd/_carspan.py` | `_ibi_amplitude_periodogram` | Ported | Eq. 3.21, ~2 % agreement on manual example |
| `T_AnaFunctions.pas` Resample_R | `src/spectHR/analysis/psd/_carspan.py` | `_bin_average` | Ported | Bit-for-bit faithful including edge policy |
| `T_AnaFunctions.pas` AutoSpectrum (WindowSize=0) | `src/spectHR/analysis/transfer.py` | `_auto_spectrum` | Ported | |
| `T_AnaFunctions.pas` AutoSpectrum (WindowSize=3) | `src/spectHR/analysis/_smoothing.py` | `smooth3_triangular` | Ported | 3-point triangular smoother |
| `T_AnaFunctions.pas` CrossSpectrum | `src/spectHR/analysis/transfer.py` | `_cross_spectrum` | Ported | |
| `T_AnaFunctions.pas` Transfer | `src/spectHR/analysis/transfer.py` | `_transfer_function` | Ported | |
| `T_AnaFunctions.pas` Modulus | `src/spectHR/analysis/transfer.py` | `_modulus` | Ported | |
| `T_AnaFunctions.pas` Phase | `src/spectHR/analysis/transfer.py` | `_phase_wrapped` | Ported | |
| `T_AnaFunctions.pas` UnwrapPhase | `src/spectHR/analysis/transfer.py` | `_unwrap_phase` | Ported | Bit-for-bit faithful |
| `T_AnaFunctions.pas` Coherence | `src/spectHR/analysis/transfer.py` | `_coherence` | Ported | |
| `T_AnaFunctions.pas` Calculate_Energy | `src/spectHR/analysis/frequency_metrics.py` | `_band_power_integrate` | Ported | Rectangular integration |
| `T_AnaFunctions.pas` Caluculate_WeightedCoherenceSom | `src/spectHR/analysis/transfer.py` | `_band_weighted_coherence` | Ported | |
| `T_AnaFunctions.pas` Caluculate_ModulusSum | `src/spectHR/analysis/transfer.py` | `_band_modulus_mean` | Ported | |
| `T_AnaFunctions.pas` Caluculate_PhaseSum | `src/spectHR/analysis/transfer.py` | `_band_phase_mean` | Ported | |
| `T_AnaFunctions.pas` RunProfileSommation | `src/spectHR/analysis/profile.py` | `compute_band_power_profile` | Ported | |
| `T_AnaFunctions.pas` RunTransfer (profile) | `src/spectHR/analysis/transfer.py` | `compute_transfer_profile` | Ported | |
| `T_AnaFunctions.pas` RunModIdx | `src/spectHR/analysis/psd/_engine.py` | mMI^2/Hz conversion in `_carspan_display` | Ported | Applied after PSD, not as in-place mutation |
| `T_AnaFunctions.pas` MAW (RunMAW) | `src/spectHR/analysis/psd/_carspan.py` | `smooth_for_display` option (3-point MA via `_smooth3`) | Ported | Applied display-side only; never affects integration |
| `T_AnaData.pas` TAnaData / TProfile | `src/spectHR/session/session.py` | `Session` + `MetricsTable` | Ported | Redesigned as immutable primitives |
| `T_SpecAnalysis.pas` TSpecAnalysis | `src/spectHR/analysis/registry.py` | `@epoch_metric` registry | Ported | Declarative rather than imperative |
| `T_CarspanParams.pas` CorrSpecs | `src/spectHR/session/workspace.py` | `AnalysisConfig` | Partial | Correction params not surfaced |
| `T_Output.pas` CreateSpectralFunctionsNumerical | `src/spectHR/analysis/exporter.py` | `EpochExporter` | Ported | CSV + HDF5 instead of fixed-width .out |
| `T_Output.pas` CreateSpectralProfilesProfile | `src/spectUI/widgets/results.py` | profile export | Partial | Profile export via CSV, not .pro INI format |
| `T_EventFile.pas` CalcDataColBPSYS/DIA | `src/spectHR/analysis/bp_metrics.py` | `bp_beat_parameters` | Ported | Per-beat systolic/diastolic extraction |
| `T_EventFile.pas` CalcDataColRESPVO / CalcDataColRESMVO | `src/spectHR/DataSet/preprocessing.py` | `apply_breath_phases` | Ported | INH/EXH detection |
| `T_DataCorrect.pas` CheckFirstWindow | `src/spectHR/DataSet/classification.py` | IBI classification (rolling window, 4 sigma) | Partial | Different algorithm: centred 51-beat window, not TWL-length time window |
| `T_AnaFunctions.pas` GetRespirationMinBandValue / GetRespirationMaxBandValue | `src/spectHR/analysis/psd/_carspan.py` | not explicitly ported | Missing | Respiration-relative band limits not implemented in spectHR |

---

## 10. Known gaps and differences

### 10.1 Artefact classification and correction

**CARSPAN:** The `TDataCorrect.AutoCorrect` engine uses a time-based rolling
window (`TWL` seconds), computes a running mean and SD over non-excluded beats,
classifies beats as SHORT/LONG relative to `NSD * SD`, and interpolates
replacement beats. The correction taxonomy (SHORT, LONG, SHORT-LONG, etc.) is
stored in the EVT file alongside the data and is auditable.

**spectHR:** Uses a beat-count-based rolling window (51 beats centred), with a
fixed 4 sigma threshold. Labels are N/L/S/TL/SL/SNS/T. No automatic interpolation:
flagged beats are excluded from downstream analysis rather than replaced. The
CARSPAN `TCorKind` taxonomy is not implemented.

**Impact:** CARSPAN-corrected EVT files imported into spectHR will have
corrections already applied and stored in the file; spectHR reads the `NewData`
values directly. Re-running auto-correction from scratch in spectHR will give
different results because the algorithm is different.

### 10.2 Respiration-relative frequency bands

CARSPAN supports `RespirationBand=True` for any frequency band, dynamically
adjusting the limits per profile step: `[FRespFreq - Min, FRespFreq + Max]`.
`FRespFreq` is the instantaneous respiration rate (1 / mean_period from the
`RespPeriod` time series). spectHR does not implement this feature. All bands
use fixed Hz limits.

### 10.3 Display-only smoothing vs. integration smoothing

**CARSPAN:** `PDSin_BCK` is the pre-MAW backup; the 3-point uniform MAW is
applied to `PDSin` for display. Band-power integration uses `PDSin_BCK` when
`FSaveUnsmoothed=True` (the default). So by default the output numbers are based
on the unsmoothed spectrum.

**spectHR:** The `smooth_for_display` option in `CarspanOptions` controls
whether the 3-point MA is applied to the display curve. Band-power integration
always runs on the unsmoothed resampled grid. This matches CARSPAN's default
(`FSaveUnsmoothed=True`) behaviour.

### 10.4 Profile path -- resampling

The CARSPAN manual (section 3.3.5) states that resampling to 0.01 Hz is not
applied to the profile path. However the Pascal code calls `Resample` for
profiles too (using `OldRes = 1 / WindowLength`). spectHR implements the
manual's stated behaviour with `resample_to_display_grid=False` for profiles.
This is a deliberate, documented divergence.

### 10.5 AutoSpectrum profile smoother

For profiles, CARSPAN passes `WindowSize=3` to `AutoSpectrum`, implementing a
triangular 3-point smoother `[0.25, 0.5, 0.25]` applied to the power spectrum
inside the DFT loop (using Pascal's `CreateWindow`). spectHR's
`smooth3_triangular` function in `_smoothing.py` mirrors this but runs on the
full power array after `_auto_spectrum`, which is equivalent for non-windowed
spectra.

### 10.6 SameIn / SameOut DFT deduplication

CARSPAN's `FindSameProfiles` detects when two different spectral analyses share
the same input or output channel and avoids recomputing the DFT. spectHR's
`Session` immutable model combined with the `@epoch_metric` registry naturally
deduplicates computation through Python's function-call caching and shared
`Session` state; however there is no explicit equivalent of `SameIn`/`SameOut`.

### 10.7 NFF file reading

spectHR reads VU-AMS EDF files (via MNE), not raw NFF files. The NFF reader
(`T_NFF.pas`) is not ported. If raw NFF files need to be read, the NFF.bas
VB module and T_NFF.pas provide the reference format description.

### 10.8 EVT file writing

CARSPAN writes back corrected EVT files (adding correction annotations to the
data columns). spectHR saves corrections in the session `.pkl` cache but does
not write CARSPAN-format EVT files.

### 10.9 Fixed-width output files

CARSPAN's `_Summary.out`, `_Numerical.out`, and `_Profiles.pro` files use
fixed-width ASCII columns in a format specific to CARSPAN's era. spectHR exports
CSV and HDF5 via `EpochExporter`. The column names follow the CARSPAN naming
convention (`{band}_tf_modulus`, `{band}_tf_coherence`, etc.) but the file
format differs.

### 10.10 ACTindex 4 vs. 5 distinction

CARSPAN writes two phase rows per transfer analysis: ACTindex=4 uses the
unwrapped `Phase` array; ACTindex=5 uses the wrapped `Phase2` array. Both pass
through `Caluculate_PhaseSum` (coherence-gated mean). spectHR's `TransferResult`
stores both `phase_wrapped` and `phase_unwrapped` and exposes both as export
columns (`{band}_tf_phase_w` and `{band}_tf_phase_u`), matching CARSPAN's ACT
4/5 distinction.

### 10.11 Blood-pressure channel derivation

CARSPAN derives per-beat BP values from the continuous NFF BP waveform in
`CalcDataColBPSYS`, `CalcDataColBPDIA`, `CalcDataColBPPUL`, `CalcDataColBPMPR`.
The systolic is the waveform maximum between two R-peaks; the diastolic is the
minimum. spectHR's `bp_beat_parameters` in `bp_metrics.py` implements the same
peak-finding logic with a flat-line guard. This is ported.

### 10.12 T-wave and ECG waveform columns

CARSPAN derives `tkECGTWAVE` (T-wave amplitude) from the ECG channel in
`CalcDataColECGTWAVE`. spectHR does not compute T-wave amplitude.

### 10.13 Logarithmic spectrum option

When `acLn` is in `FACalcs`, CARSPAN applies `ln()` to band-power values in
`Calculate_Energy`. spectHR's frequency metrics do not offer a logarithmic band
power option. This would be a straightforward addition.

### 10.14 Manual correction dialog

CARSPAN has an extensive interactive beat editor (not analysed here, UI code).
spectHR implements a comparable interactive editor in the Timeline dock.

---

*End of CARSPAN technical reference.*
