# spectHR — Handover to Claude Code

*Written in chat mode; to be read by a Claude Code session at repo root.*
*British spelling throughout, matching AGENTS.md convention.*

---

## What this document is

A self-contained brief for a Claude Code session taking over two related tasks:

1. Rewrite `nff_loader.py` so it loads **all channels** from the NFF file, not just ECG.
2. Rewrite `evt_loader.py` so it parses the structured header sections and picks up extra
   time-series columns (IBI, BPSys) when present.
3. Wire the RESP channel from the NFF file into `PhysioData` so it works identically to
   the respiration signal that comes from an XDF/Polar band.

No other files need to change for this task. `PhysioData.py` is explicitly **not** on
the change list — the wiring already works once the loader populates `timeseries` and
`band_map` correctly.

---

## Repo layout (relevant paths only)

```
C:\Users\P154492\Documents\GitHub\spectHR\
├── src/
│   └── spectHR/
│       └── DataSet/
│           ├── PhysioData.py              read-only for this task
│           ├── Series/
│           │   ├── TimeSeries.py          read-only
│           │   └── RespirationSeries.py   read-only
│           └── loaders/
│               ├── evt_loader.py          REWRITE
│               ├── nff_loader.py          REWRITE
│               └── registry.py            read-only
├── ExampleData/
│   └── data/
│       ├── EXAMP1.EVT                     test file with IBI + BPSys columns
│       ├── example1.EVT                   test file, R-tops only, many event codes
│       └── example1.nff                   7-channel NFF file
└── tests/
    └── conftest.py                        shared fixtures; add new ones here
```

The session mount path follows the pattern
`/sessions/.../mnt/spectHR/src/spectHR/DataSet/loaders/`.
Run `find /sessions -name "nff_loader.py" 2>/dev/null` to confirm the exact path
before writing anything. All file writes must go through bash (`cat > ... << 'PYEOF'`),
never through the Write or Edit tool — see AGENTS.md §2.11.

---

## Task 1 — rewrite `nff_loader.py`

### What the current loader does

Reads exactly one channel (label `'ECG'`, or channel 1 if the file has only one channel)
and attaches it as `physiodata.timeseries["ecg"]`. Sets:

```python
physiodata.band_map   = {"ecg": {"ecg": "ecg"}}
physiodata.active_band = "ecg"
physiodata.has_ecg    = True
```

All other channels in the file are silently discarded.

### What the example1.nff file actually contains

Seven channels, all at 100 Hz, all 133 120 samples (≈ 1331 s):

| Chan | Label  | Purpose                              |
|------|--------|--------------------------------------|
| 1    | `ECG`  | Electrocardiogram                    |
| 2    | `BP`   | Continuous blood pressure waveform   |
| 3    | `RESP` | Respiration                          |
| 4    | `ESP`  | Electrostatic pressure / effort      |
| 5    | `PLET` | Plethysmogram (FIN.A.PRES optical)   |
| 6    | `CARD` | Cardiotachometer signal              |
| 7    | `TOON` | Audio tone / stimulus                |

### What the new loader must do

Load **every channel** in one pass. For each channel, derive a key from the label
(lowercased, stripped) and store it in `physiodata.timeseries[key]`. Time normalisation
(subtracting `earliest`) is handled by `PhysioData._normalize_times_and_build_epochs`
automatically for everything in `timeseries` — the loader must not do it.

The band map must wire ECG **and** RESP under the same band key so that
`physiodata["rsp"]` resolves correctly when `preprocess_ecg` runs:

```python
# Target state after load_nff returns:
physiodata.timeseries["ecg"]  = TimeSeries(...)   # channel 1
physiodata.timeseries["bp"]   = TimeSeries(...)   # channel 2
physiodata.timeseries["resp"] = TimeSeries(...)   # channel 3
physiodata.timeseries["esp"]  = TimeSeries(...)   # channel 4
# ... etc. for every channel present

physiodata.band_map    = {"ecg": {"ecg": "ecg", "rsp": "resp"}}
physiodata.active_band = "ecg"
physiodata.has_ecg     = True
```

The `"rsp": "resp"` entry in `band_map` is the single hook that makes everything
downstream work — `PhysioData.__getitem__("rsp")` resolves it to
`timeseries["resp"]`, which `preprocess_ecg` then passes to
`RespirationSeries.from_timeseries(rsp_ts)`.

### How `_index_polar_bands` does it in xdf_loader (follow this pattern)

```python
# from xdf_loader._index_polar_bands — the pattern to mirror:
bands = {}
for name in dataset.timeseries:
    if name.startswith(("ecg-[", "RSP-[")):
        band = name.split("[")[-1].rstrip("]")
        bands.setdefault(band, {})
        if name.startswith("ecg"):
            bands[band]["ecg"] = name
        elif name.startswith("RSP"):
            bands[band]["rsp"] = name
dataset.band_map = bands
dataset.active_band = next(iter(bands), None)
```

For NFF there is only one band (no per-device suffix), so the equivalent is simpler:

```python
band_streams: dict[str, str] = {}
if "ecg" in physiodata.timeseries:
    band_streams["ecg"] = "ecg"
if "resp" in physiodata.timeseries:
    band_streams["rsp"] = "resp"   # note: key is "rsp", value is timeseries key "resp"
physiodata.band_map    = {"ecg": band_streams}
physiodata.active_band = "ecg"
```

### `TNFF` class — keep as-is

The binary reader `TNFF` is correct. The only change needed to `TNFF` is removing the
single-channel assumption from `load_nff`. `TNFF.read_channel_data` already takes a
channel number argument and works for any channel.

### Performance note

Reading all 7 channels in a loop is fine — each call to `read_channel_data` does one
sequential pass through the file. The file is ~1.8 MB so total I/O is negligible.

---

## Task 2 — rewrite `evt_loader.py`

### The two example files and their differences

Both files live in `ExampleData/data/`. Read them at the start of the session to
confirm the exact content before writing the parser.

**EXAMP1.EVT** — structured header, IBI + BPSys columns:

```
[Event file]
Textline=E001S001
Created=9/13/2004 11:33:57
Origin=Carspan

[Events]
RPeak=0
BeginBlock=11
EndBlock=12
BeginPeriod=21
EndPeriod=22

[Timeseries]
Timeserie1=IBI
Timeserie2=BPSys

[Data]
     0   454.737   8410   1505
     0   455.578   8410   1505
    11   459.700
     0   459.863   7760   1434
...
[End]
```

**example1.EVT** — same family, no `[Timeseries]` section, many extra event codes:

```
[Event File]
Textline =EXAMPLE1
Created=03-07-2007 10:05:06
Origin=Carspan
[Events]
Rpeaks=0
BeginBlock=11
EndBlock=12
BeginPeriod=21
EndPeriod=22
[DATA]
     0   292.211
     0   292.976
    11   311.514
    21   313.900
    16   635.251        ← stimulus/response codes, dense in second half
    17   638.752
...
```

### Parser design: two-phase

**Phase 1 — scan header sections (before `[Data]` / `[DATA]`):**

Parse `[Events]` to find the R-peak code. Match key prefix `rpeak` case-insensitively
(`RPeak`, `Rpeaks`, `RPEAK` all match). Fall back to the existing frequency heuristic
if no `[Events]` section or no RPeak key found.

Parse `[Timeseries]` to build an ordered column map:
```python
# e.g. {"IBI": 2, "BPSys": 3}  (column indices in the data rows, 0-based)
timeseries_cols: dict[str, int] = {}
col_idx = 2   # columns 0=code, 1=time; extra columns start at 2
for line in timeseries_section_lines:
    name = line.split("=")[1].strip()   # e.g. "IBI", "BPSys"
    timeseries_cols[name] = col_idx
    col_idx += 1
```

**Phase 2 — parse `[Data]` rows:**

```python
parts = line.strip().split()
if len(parts) < 2:
    continue
code = int(parts[0])
time = float(parts[1])
if code == rtop_code and len(parts) >= 2 + len(timeseries_cols):
    for name, idx in timeseries_cols.items():
        extra_cols[name].append(float(parts[idx]))
```

### Units

Both extra columns are in CARSPAN's internal 0.1-unit encoding:

| Column | Raw unit | Divide by | Result unit |
|--------|----------|-----------|-------------|
| IBI    | 0.1 ms   | 10 000    | seconds     |
| BPSys  | 0.1 mmHg | 10        | mmHg        |

These constants must be named and documented:

```python
# CARSPAN internal unit scale factors.
# IBI is stored in units of 0.1 ms; divide by 10 000 to get seconds.
_IBI_SCALE_TO_SECONDS = 10_000.0
# BPSys (and any future BP channel) is stored in units of 0.1 mmHg.
_BP_SCALE_TO_MMHG = 10.0
```

### Case-insensitive section matching

Section headers vary: `[Data]`, `[DATA]`, `[Event file]`, `[Event File]`. Match with:

```python
if line.strip().lower().startswith("[data"):
    in_data = True
```

### What to do with the IBI column for now

Store it but do not wire it into `CardioSeries` yet — that is a separate task.
Log it at DEBUG level. A follow-up task will use it to populate a `stored_ibi` array
on `CardioSeries` for artifact-aware IBI access.

### What to do with BPSys for now

Same deferral — store the raw array, log it, but do not create a `BPSeries` object yet.
That class does not exist yet. A comment in the loader must say:

```python
# TODO: construct BPSeries(times=rtop_times, sbp=sbp_values) and store
# in physiodata.bp_map[band] once BPSeries is implemented.
# See chat-mode handover document for design.
```

### Epoch code handling — do not change the existing logic

The current heuristic (2 unique non-R-top codes → pair as start/stop; > 2 → GUI dialog)
is correct for both files. `example1.EVT` has 6 non-R-top codes and will fall into the
GUI branch — that is the right behaviour. Do not touch this part of the loader.

### `[End]` marker

EXAMP1.EVT has an `[End]` section marker at the bottom. The parser must treat any line
starting with `[End` (case-insensitive) as end-of-data and stop reading there.

---

## How `preprocess_ecg` uses the respiration signal (read-only reference)

Once `band_map["ecg"]["rsp"] = "resp"` is set, the existing code in `PhysioData.py`
handles everything:

```python
# PhysioData.preprocess_ecg (do not modify):
try:
    rsp_ts = self["rsp"].timeseries   # resolves via band_map → timeseries["resp"]
except KeyError:
    rsp_ts = None

if rsp_ts is not None:
    resp = RespirationSeries.from_timeseries(rsp_ts)
    resp._pd     = self
    resp._stream = band
    self.rsp_map[band] = resp          # stored here for downstream use
```

The respiration widget, spectrogram breathing overlay, and transfer function all read
from `rsp_map` — they will all gain NFF-sourced breathing automatically.

---

## Coding conventions (from AGENTS.md)

- British spelling: *normalisation*, *behaviour*, *colour*, *recognised*.
- Docstrings on every public function and class; inline comments on every non-obvious step.
- `pathlib.Path` everywhere a path is passed, never bare strings.
- Catch the narrowest exception you can name; loaders catch `(ValueError, struct.error, OSError)`.
- No top-level GUI imports in anything under `src/spectHR/` — keep it headless.
- After every write: `python3 -m py_compile <path>`, `wc -l <path>`, null-byte check.

---

## Write protocol (from AGENTS.md §2.11)

**Never use the Write or Edit tool for Python files.** Use bash only:

```bash
# Targeted patch
python3 - << 'PYEOF'
p = '/sessions/.../mnt/spectHR/src/spectHR/DataSet/loaders/nff_loader.py'
src = open(p).read()
assert src.count(OLD) == 1
open(p, 'w').write(src.replace(OLD, NEW, 1))
PYEOF

# Full rewrite
cat > /sessions/.../mnt/spectHR/src/spectHR/DataSet/loaders/nff_loader.py << 'PYEOF'
# ... full content ...
PYEOF
echo "wrote $(wc -l < /sessions/.../mnt/spectHR/src/spectHR/DataSet/loaders/nff_loader.py) lines"
```

Find the exact session path first:
```bash
find /sessions -name "nff_loader.py" 2>/dev/null
```

---

## Test plan

### Existing tests — must still pass

```bash
cd /sessions/.../mnt/spectHR
python -m pytest tests/ -x -q
```

No existing test exercises the EVT or NFF loader (the test suite uses synthetic
`CardioSeries` fixtures only). All existing tests should pass unchanged.

### New smoke tests to add in `tests/conftest.py` or a new `tests/test_loaders.py`

```python
# 1. NFF: all channels loaded
pd = PhysioData("ExampleData/data/example1.EVT")
assert "ecg"  in pd.timeseries
assert "bp"   in pd.timeseries
assert "resp" in pd.timeseries
assert pd.band_map["ecg"]["rsp"] == "resp"

# 2. NFF: RESP wires through preprocess_ecg
pd.preprocess_ecg()
assert "ecg" in pd.rsp_map         # RespirationSeries was built from NFF RESP

# 3. EVT with timeseries columns: IBI and BPSys parsed without error
pd2 = PhysioData("ExampleData/data/EXAMP1.EVT")
assert pd2.hrv_map                  # CardioSeries created

# 4. EVT without timeseries columns: loads cleanly
pd3 = PhysioData("ExampleData/data/example1.EVT")
assert pd3.hrv_map
```

Note: tests 1 and 2 require the NFF file to be present, which it is in `ExampleData/data/`.
The `.evt` loader is what triggers `load_nff` (it calls it when a matching `.nff` exists).

---

## What is explicitly out of scope for this session

- `BPSeries` class — not yet implemented; EVT loader leaves a TODO comment.
- Stored IBI from EVT column 2 — deferred; EVT loader logs it at DEBUG only.
- Changes to `PhysioData.py`, `RespirationSeries.py`, or any analysis code.
- The spectrogram 3D widget work (separate branch, already implemented in chat).

---

## Summary of changes

| File | Action | Key change |
|---|---|---|
| `src/spectHR/DataSet/loaders/nff_loader.py` | Full rewrite | Load all channels; wire `band_map["ecg"]["rsp"] = "resp"` |
| `src/spectHR/DataSet/loaders/evt_loader.py` | Full rewrite | Two-phase header parser; pick up BPSys/IBI columns; case-insensitive section matching |
| `tests/test_loaders.py` | New file | Smoke tests against the example data files |

Two files rewritten, one new test file. Nothing else.
