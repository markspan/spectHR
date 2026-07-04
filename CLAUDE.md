# CLAUDE.md

Orientation for a Claude Code session working on **spectHR**. Read
[readme.MD](readme.MD) for what the project *is*, and [AGENTS.md](AGENTS.md)
for the writing/style conventions (British spelling throughout). This file is
the *how the codebase is shaped and how we work in it* brief.

> Note: `HANDOFF.md` / `HANDOVER.md` are historical and describe the **old**
> (`PhysioData`) architecture, the files they name no longer exist. Don't
> trust them; this file supersedes them.

---

## What it is

spectHR is a Python/PySide6 reimplementation of the CARSPAN HRV analyser
(originally Delphi/Pascal). It loads cardiac recordings (XDF, VU-AMS EDF,
CARSPAN EVT/NFF, RR text, Polar), detects R-peaks, lets the analyst edit them,
splits the recording into epochs, and computes time-domain, frequency-domain
(PSD), Poincaré, blood-pressure, respiration/RSA and ICG/PEP metrics, plus
spectrograms and respiration→HR transfer functions.

## Reference material

Ground-truth references for algorithm / feature parity, most authoritative first:

- **The `V2` branch**, the working reference implementation being ported (see
  the parity note under [the data model](#the-data-model-srcspecthrsession));
  read it with `git show V2:<path>`.
- **Original CARSPAN Delphi/Pascal sources**,
  `G:\My Drive\Source_23-01-2013work` (outside the repo): `Carspan.dpr` plus the
  `*.pas` / `*.dfm` units the Python port descends from. The authoritative
  record of *what the original algorithm actually did*.
- **Manuals in [`docs/`](docs/):**
  - [CARSPAN manual](docs/Carspan_Manual_VERSION_36.pdf), the HRV analyser this
    project reimplements (Mulder, Hofstetter & van Roon).
  - [CARCAL manual](docs/CARCAL%20manual%20v%201.doc), the companion
    blood-pressure calibration tool.
  - [VU-DAMS / VU-AMS manual](docs/VU-DAMS_manual_V2_DAMS5.0_10-01-2022.pdf),
    the VU Ambulatory Monitoring System (the ICG / accelerometer EDF source
    format and its reference metrics).
  - [`docs/ALGORITHM_AUDIT.md`](docs/ALGORITHM_AUDIT.md), a written audit of how
    the Python algorithms line up against the originals.
- **Scientific bibliography**, the full academic reference list (Mulder,
  Grossman, Billman, Robbe, Riese, Lozano, Peng, van Roon, Task Force 1996, …)
  lives in [readme.MD § References](readme.MD#references); the algorithm
  docstrings and readme sections cite into it by `#ref-…` anchors. Treat it as
  the canonical source list, extend *it*, not a second copy here.

> **At session start, request read access to `G:\My Drive\Source_23-01-2013work`.**
> Those original CARSPAN Delphi sources live outside the repo, so Claude Code
> will prompt the user for permission, ask for and obtain that approval before
> reading them when a task needs the original algorithm as the reference.

## Architecture: the one rule that matters

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

- `Samples`, a regularly/irregularly sampled signal (frozen, read-only arrays).
- `Events`, a point process with per-point labels (R-peaks live here as
  `events["hrv"]`; R-peak *edits* are functional methods on `Events`).
- `Intervals`, labelled spans (breath phases live here as `intervals["breath"]`
  with `"INH"`/`"EXH"` labels).
- `Epoch(label, start, end, active)`, analysis windows.

`Session.epochs_table(config)` evaluates every registered `@epoch_metric`
(see `spectHR/analysis/registry.py`) per active epoch → a `MetricsTable`.
`AnalysisConfig`/`WorkspaceView` are the typed settings layer.

> The `development` branch ports the old V2 functionality onto this immutable
> `Session` API. The **`V2` branch is the reference** for feature parity, when
> a feature "should look like V2", read the V2 source (`git show V2:<path>`).
> PRs target `V2` per repo config, but day-to-day work lands on `development`.

## UI layout (`src/spectUI/`)

- `main_window.py`, wires every dock; `_LoadWorker` runs the load+preprocess
  pipeline on a background thread; `DataCoordinator` (`coordinator.py`) does
  dependency-aware refresh across docks via a `DataChange` flag mask.
- Three dock families:
  - **Timeline** docks (`widgets/timeline/`, `widgets/prep/`, `widgets/hr.py`,
    `widgets/bp.py`), scrolling series with coupled x-axis.
  - **Grid** docks (`widgets/grid/`), one tile per epoch, computed
    off-thread via `DockScheduler`. Base class `EpochGridView` owns the
    scrollable viewport-aspect layout, the *Equal y-axis* + arrow-zoom
    toolbar, and `MAX_COLUMNS` / `TILE_HEIGHT_FACTOR`. PSD/profile/transfer/
    spectrogram(+3D) subclass it.
  - **Standalone** (`widgets/poincare.py`, `widgets/epochs.py`,
    `widgets/results.py`).

## Preprocessing pipeline (`spectHR/dataset/preprocessing.py`)

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

## Settings: one file, manual save

All settings (analysis parameters **and** working directories) live in one
`~/workspace.json`, loaded at startup (created from defaults on first run).
Changes are **not** auto-saved, the user persists with **Save settings
(Ctrl+S)**, which opens a Save-As dialog (defaults to `~/workspace.json`).
`Parameters` (extends `WorkspaceView`) carries the `Directories` section and
`data_dir`/`cache_dir`/`output_dir`/`export_dir()` accessors. `AppSettings`
(QSettings, forced to an **INI file** under the user's config dir, never the
Windows registry) holds only machine-local UI state: window geometry, dock
layout and the saved dock perspectives. It accepts an injected `QSettings` so
tests can isolate to a temp `.ini`.

## Working conventions

- **Run tests:** `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
  (Windows; the venv is `.venv`). Full suite is ~420 tests, runs in ~45 s.
- **Qt tests MUST be subprocess-isolated**, importing spectUI/Qt into the
  shared pytest process segfaults. The `*_qt.py` tests build a session, render
  offscreen (`QT_QPA_PLATFORM=offscreen`) and assert inside a `subprocess`
  driver string. Follow that pattern for new UI tests; isolate `Path.home()`
  (set `USERPROFILE`/`HOME`) so they don't write a real `~/workspace.json`.
- **Commit messages:** write to a file and `git commit -F _commit_msg.txt`
  (here-strings/`-m` mangle multi-line/UTF-8 messages here). End with the
  `Co-Authored-By: Claude …` trailer. Work lands on `development`; commit
  incrementally, tests green first.
- **Example data:** `ExampleData/`, `example1.EVT`/`.nff` (ECG+BP+RESP, no
  ICG), `ExampleData/data/VU-AMS_5fs_example_data.edf` (has ICG=`dzdt-[vuams]`
  + raw accel `mxr/myr/mzr` → exercises PEP and per-epoch accel-PCA breathing).
- **Deliberate function-local imports.** Some imports sit inside functions on
  purpose, and should stay there: to keep the headless `spectHR` import light
  (heavy deps like `scipy.signal`, `h5py`, matplotlib) or to break a module
  cycle (`session` ↔ `config`, `session` ↔ `analysis`, `config` ↔ `session`).
  Don't hoist those to module top. A pure-stdlib function-local import with no
  such reason is just clutter and belongs at the top of the module.
- LF→CRLF git warnings and an offscreen exit-code-9 on Qt teardown are benign.

## Export

`spectHR/analysis/exporter.py` (`EpochExporter`) is ported to `Session` and
wired to the Results dock's **Export…** button: it writes `<name>.csv` (the
metrics table) + `<name>.h5` (all per-epoch arrays + summary scalars via the
recursive `_h5_write_node` walker), then optionally the open dock figures as
PDFs (`MainWindow._export_plots`, named `{datafile}_{dock}_{epoch}.pdf`). The
transfer input is resolved per epoch by `_transfer_input` (BP, falling back to
respiration when no BP channel is present).

## Gotchas learned the hard way

- A `.pkl` cache predating a pipeline step won't have that step's data
  (e.g. breath phases), recreate the cache, don't recompute on every load.
- `Path.home()` on Windows resolves via `USERPROFILE`, not `HOME`.
- PEP ensemble averaging uses integer indexing on the uniform ICG grid (don't
  reintroduce per-beat `np.interp`, it was 30× slower).
- The two-arg `QSettings(org, app)` ignores `setDefaultFormat`/`setPath` and
  uses the native backend (the **registry** on Windows). `AppSettings` therefore
  constructs `QSettings(IniFormat, UserScope, …)` explicitly, keep it that way,
  and inject a temp-`.ini` `QSettings` in tests rather than touching the real store.
- Retriggering / inverting R-tops (`MainWindow._reprocess`) re-detects beats over
  the whole recording, so it also re-runs `recompute_breath_phases`, otherwise
  the INH/EXH phases stay limited to an EVT file's originally annotated window.
