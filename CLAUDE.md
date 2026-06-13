# CLAUDE.md

Orientation for a Claude Code session working on **spectHR**. Read
[README.md](README.md) for what the project *is*, and [AGENTS.md](AGENTS.md)
for the writing/style conventions (British spelling throughout). This file is
the *how the codebase is shaped and how we work in it* brief.

> Note: `HANDOFF.md` / `HANDOVER.md` are historical and describe the **old**
> (`PhysioData`) architecture — the files they name no longer exist. Don't
> trust them; this file supersedes them.

---

## What it is

spectHR is a Python/PySide6 reimplementation of the CARSPAN HRV analyser
(originally Delphi/Pascal). It loads cardiac recordings (XDF, VU-AMS EDF,
CARSPAN EVT/NFF, RR text, Polar), detects R-peaks, lets the analyst edit them,
splits the recording into epochs, and computes time-domain, frequency-domain
(PSD), Poincaré, blood-pressure, respiration/RSA and ICG/PEP metrics, plus
spectrograms and respiration→HR transfer functions.

## Architecture — the one rule that matters

**Strict separation of algorithm from UI:**

| Package | Role | May import |
|---|---|---|
| `src/spectHR/` | headless analysis library | numpy, scipy, **never Qt or matplotlib** |
| `src/spectUI/` | PySide6 UI + matplotlib drawing | spectHR + Qt; **no analysis algorithms** |

This is enforced by `tests/test_headless_imports.py` (importing Qt into the
shared pytest process also segfaults, so keep it pure). When adding a feature:
the *calculation* goes in spectHR, the *drawing/interaction* goes in spectUI,
and the UI calls the library. spectUI may hold display-only maths (axis
normalisation, downsampling for rendering) but never signal processing.

### The data model (`src/spectHR/session/`)

`Session` is a mutable dataclass of **immutable** channel primitives:

- `Samples` — a regularly/irregularly sampled signal (frozen, read-only arrays).
- `Events` — a point process with per-point labels (R-peaks live here as
  `events["hrv"]`; R-peak *edits* are functional methods on `Events`).
- `Intervals` — labelled spans (breath phases live here as `intervals["breath"]`
  with `"INH"`/`"EXH"` labels).
- `Epoch(label, start, end, active)` — analysis windows.

`Session.epochs_table(config)` evaluates every registered `@epoch_metric`
(see `spectHR/analysis/registry.py`) per active epoch → a `MetricsTable`.
`AnalysisConfig`/`WorkspaceView` are the typed settings layer.

> The `development` branch ports the old V2 functionality onto this immutable
> `Session` API. The **`V2` branch is the reference** for feature parity — when
> a feature "should look like V2", read the V2 source (`git show V2:<path>`).
> PRs target `V2` per repo config, but day-to-day work lands on `development`.

## UI layout (`src/spectUI/`)

- `MainWindow.py` — wires every dock; `_LoadWorker` runs the load+preprocess
  pipeline on a background thread; `DataCoordinator` (`coordinator.py`) does
  dependency-aware refresh across docks via a `DataChange` flag mask.
- Three dock families:
  - **Timeline** docks (`widgets/timeline/`, `widgets/prep/`, `widgets/hr.py`,
    `widgets/bp.py`) — scrolling series with coupled x-axis.
  - **Grid** docks (`widgets/grid/`) — one tile per epoch, computed
    off-thread via `DockScheduler`. Base class `EpochGridView` owns the
    scrollable viewport-aspect layout, the *Equal y-axis* + arrow-zoom
    toolbar, and `MAX_COLUMNS` / `TILE_HEIGHT_FACTOR`. PSD/profile/transfer/
    spectrogram(+3D) subclass it.
  - **Standalone** (`widgets/poincare.py`, `widgets/epochs.py`,
    `widgets/results.py`).

## Preprocessing pipeline (`spectHR/DataSet/preprocessing.py`)

Loader-agnostic `Session → Session` transforms, applied in `_LoadWorker.run`
(raw files only; a cached `.pkl` is trusted as already-processed):

```
apply_canonical_channels  # alias device-suffixed keys (ecg-[vuams], dzdt-[vuams]→icg, …)
apply_ecg_polarity        # flip inverted ECG before detection
apply_rsp_source          # native respiration wins; ICG/accel only as fallback
apply_bp_calibration
apply_beat_detection       # R-peaks (skipped if hrv already present, e.g. EVT)
apply_breath_phases        # INH/EXH from resp; per-epoch accel PCA when configured
```

`recompute_breath_phases` re-runs breath detection when the respiration
setting changes at runtime.

## Settings — one file, manual save

All settings (analysis parameters **and** working directories) live in one
`~/workspace.json`, loaded at startup (created from defaults on first run).
Changes are **not** auto-saved — the user persists with **Save settings
(Ctrl+S)**. `Parameters` (extends `WorkspaceView`) carries the `Directories`
section and `data_dir`/`cache_dir`/`output_dir`/`export_dir()` accessors.
`AppSettings` (QSettings) holds only window geometry/dock layout.

## Working conventions

- **Run tests:** `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
  (Windows; the venv is `.venv`). Full suite is ~410 tests, runs in ~45 s.
- **Qt tests MUST be subprocess-isolated** — importing spectUI/Qt into the
  shared pytest process segfaults. The `*_qt.py` tests build a session, render
  offscreen (`QT_QPA_PLATFORM=offscreen`) and assert inside a `subprocess`
  driver string. Follow that pattern for new UI tests; isolate `Path.home()`
  (set `USERPROFILE`/`HOME`) so they don't write a real `~/workspace.json`.
- **Commit messages:** write to a file and `git commit -F _commit_msg.txt`
  (here-strings/`-m` mangle multi-line/UTF-8 messages here). End with the
  `Co-Authored-By: Claude …` trailer. Work lands on `development`; commit
  incrementally, tests green first.
- **Example data:** `ExampleData/` — `example1.EVT`/`.nff` (ECG+BP+RESP, no
  ICG), `ExampleData/data/VU-AMS_5fs_example_data.edf` (has ICG=`dzdt-[vuams]`
  + raw accel `mxr/myr/mzr` → exercises PEP and per-epoch accel-PCA breathing).
- LF→CRLF git warnings and an offscreen exit-code-9 on Qt teardown are benign.

## Gotchas learned the hard way

- A `.pkl` cache predating a pipeline step won't have that step's data
  (e.g. breath phases) — recreate the cache, don't recompute on every load.
- `Path.home()` on Windows resolves via `USERPROFILE`, not `HOME`.
- PEP ensemble averaging uses integer indexing on the uniform ICG grid (don't
  reintroduce per-beat `np.interp` — it was 30× slower).
