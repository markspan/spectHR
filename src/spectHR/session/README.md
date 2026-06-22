# `spectHR/session/`: the data model

This package is the **single home of the data model**. Everything spectHR
computes flows through these types. They are pure data: no Qt, no matplotlib,
no file I/O (loaders live in [`../DataSet/`](../DataSet)).

## The immutable primitives ([`_core.py`](_core.py))

Three frozen dataclasses cover every physiological time series. All arrays are
read-only; every "change" returns a **new** object (functional updates).

| Type | Shape | Typical channels |
|---|---|---|
| `Samples` | continuous 1-D waveform (`times`, `values`) | `ecg`, `resp`, `bp`, `icg` |
| `Events` | point process with labels (`times`, `labels`, cached `ibi`) | `hrv` (R-peaks, labelled `N`/`V`/`A`/…) |
| `Intervals` | labelled non-overlapping spans (`starts`, `ends`, `labels`) | `breath` (`INH`/`EXH`) |

Shared design rules:

- **Immutable.** Arrays are read-only at construction; mutators (`with_values`,
  `with_labels`, `added`/`moved`/`removed`, `reclassified`, …) return a new
  object.
- **Zero-copy windowing.** `obj.window(start, end)` uses `np.searchsorted` on
  the sorted time axis (O(log n)) and returns the *same type* whose arrays are
  numpy views, no separate slice class.
- **Cached derivations.** `Events.ibi` is a `cached_property` (works under
  `frozen=True` because it writes through `__dict__`).
- **Factories.** `Events.detect(...)`, `Intervals.detect_breath_phases(...)`,
  `Samples.filtered(...)` delegate to [`../Tools`](../Tools) for the algorithms.

## The aggregate ([`_session.py`](_session.py))

| Type | Role |
|---|---|
| `Session` | root container: typed channel dicts (`samples`/`events`/`intervals`) + an `epochs` table; functional preprocessing helpers; the metrics engine |
| `Epoch` | a labelled `[start, end]` analysis window |
| `AnalysisConfig` | **the** typed bundle of analysis settings; build from a workspace dict via `from_workspace` |
| `MetricsTable` | result of `epochs_table`: `labels`, `columns`, `values`, and the per-epoch `EpochContext`s |

`Session` owns the channels; the channels know nothing about the session (no
back-references). Computation flows one way:

```
Session -> AnalysisConfig -> EpochContext -> @epoch_metric -> MetricsTable
```

- `Session.scoped_to(label)` returns a new `Session` with every channel
  windowed (zero-copy) to one epoch, the epoch *is* the session, so metric code
  needs no special casing.
- `Session.epochs_table(config)` builds one
  [`EpochContext`](../analysis/epoch_context.py) per active epoch (from
  `scoped_to` plus the shared `config`) and evaluates every registered
  `@epoch_metric` / `@epoch_metric_group` (see [`../analysis/`](../analysis)).

Channel lookup: the `Session.ecg` / `resp` / `bp` / `icg` getters resolve a
channel by its canonical key. Device-suffixed keys are aliased onto the
canonical ones earlier, in the load pipeline, by the device-aware resolvers in
[`../DataSet/preprocessing.py`](../DataSet/preprocessing.py).
