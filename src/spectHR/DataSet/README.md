# `spectHR/DataSet/`: loaders and pre-processing

This package turns a file on disk into an analysis-ready
[`Session`](../session). It does **not** define the data model, those types
live in [`../session/`](../session) and are re-exported from here only as a
convenience.

Two stages: loaders *parse*, preprocessing *conditions*.

## Loaders ([`loaders/`](loaders))

One module per file format, each registering itself for one or more extensions
with `@register_loader(".ext")` ([`loaders/registry.py`](loaders/registry.py)).
`load(path)` dispatches on the suffix; [`loaders/__init__.py`](loaders/__init__.py)
force-imports every loader module so its decorator runs.

| Extension | Module | Source |
|---|---|---|
| `.xdf` | [`xdf_loader.py`](loaders/xdf_loader.py) | LSL XDF |
| `.edf` | [`edf_loader.py`](loaders/edf_loader.py) | VU-AMS EDF (ICG + accel) |
| `.evt` | [`evt_loader.py`](loaders/evt_loader.py) | CARSPAN events (+ companion `.nff` signals) |
| `.nff` | [`nff_loader.py`](loaders/nff_loader.py) | CARSPAN signal file |
| `.txt` | [`polar_csv.py`](loaders/polar_csv.py) | Polar RR text |
| `.pkl` | [`pkl_loader.py`](loaders/pkl_loader.py) | cached `Session` (already preprocessed) |

A loader's job is parsing only: produce a `Session` of raw channels. It does no
conditioning.

## Pre-processing ([`preprocessing.py`](preprocessing.py))

Loader-agnostic, headless `Session -> Session` transforms, applied (for raw
files) in order:

```
apply_canonical_channels  # alias device-suffixed keys (ecg-[vuams], dzdt-[…]→icg, …)
apply_ecg_polarity        # flip inverted ECG before detection
apply_rsp_source          # native respiration wins; ICG/accel only as fallback
apply_bp_calibration
apply_beat_detection      # R-peaks (skipped if hrv already present, e.g. EVT)
apply_breath_phases       # INH/EXH from respiration
```

Each transform returns a **new** `Session` when it changes something and the
**same** object when it does not, so chaining is cheap. A cached `.pkl` is
trusted as already-conditioned and skips this pipeline.

**Channel resolution** also lives here (`resolve_ecg` / `resolve_resp` /
`resolve_bp` / `resolve_icg`): the single place that knows device-naming
conventions. It is used before/at canonicalisation; afterwards the canonical
`Session.*` getters suffice. See the note in
[`preprocessing.py`](preprocessing.py) and [`../session/README.md`](../session/README.md).
