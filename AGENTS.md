# AGENTS.md

A short style guide for human and AI contributors working on **spectHR**. Read
the [readme.MD](readme.MD) first for what the project *is*; this file describes
*how we write code and prose around it*.

---

## 1. Writing style (prose, docstrings, READMEs)

* **British / UK spelling**: *normalisation*, *behaviour*, *centred*,
  *summarise*, *colour*, *modelling*. Pick a dialect and stick to it; in
  spectHR we are British.
* **Tone**: informative but conversational. Address the reader as *you*
  when guidance is involved ("you have to check data quality"). Avoid
  marketing language and avoid academic detachment in equal measure.
* **Honesty about trade-offs.** Where a method is contested, say so and
  cite the disagreement. Where a default is a judgement call, say which
  judgement. The reader trusts the project more when it owns its choices.
* **Citations** use anchor links at the bottom of the document, e.g.
  `[Mulder, 1989](#ref-mulder1989)`. References are alphabetical by first
  author, with full DOIs.
* **Structure** prefers short paragraphs over deep heading trees. Prose
  with the occasional bulleted list is the norm; numbered lists are
  reserved for genuinely ordered steps.
* **`<details>`** blocks are used for optional depth (algorithm internals,
  derivations) so the surface stays approachable.
* **Em-dashes** (`U+2014`) never; commas for step labelling
  ("Step 1, Check and clean the ECG"); `---` rules between top-level
  sections in Markdown.
* **Names**: the project is *spectHR* (lower-s, upper-HR). The reference
  Pascal program is *CARSPAN* (all caps). Acronyms keep their case.
* **Maths** uses LaTeX in `$...$` / `$$...$$`. Inline values use the
  ASCII or Unicode symbol that reads most naturally, `α = 0.10`, not
  `\\alpha = 0.10`, when the surrounding text is plain.
* **Tables** are the preferred shape for parameter lists, defaults,
  band edges, anything where alignment helps comprehension.

---

## 2. Programming style

### 2.1 Readability beats compactness

> Always use docstrings if possible. Be generous with comments.
> Readability is favoured over compactness.
>, `~/.claude/CLAUDE.md`

That sentence is the project's first principle. Practical consequences:

* **Every public function, method, and class has a docstring.** NumPy
  format (Parameters / Returns / Notes / Raises). Module-level
  docstrings explain what the module is *for*, not just what it
  contains.
* **Comments explain the *why*, not the *what*.** Reach for one any
  time the code embodies a non-obvious decision (a magic constant, a
  sign convention, a reference to an external paper or to CARSPAN's
  Pascal source).
* **Vertical alignment** of related assignments is encouraged when it
  helps a reader skim. Example from `workSpace.py`:

  ```python
  self.timeseries:  dict[str, TimeSeries]        = {}
  self.events:      dict[str, EventSeries]       = {}
  self.epochs:      dict[str, Epoch]             = {}
  ```

* **Short methods.** When something grows beyond ~80 lines, look for a
  helper to extract, a lower-level routine, a small dataclass, or a
  module under a cleaner name (we did this for `epoch_builders/`).

### 2.2 Modern Python, but conservatively

* `from __future__ import annotations` at the top of every module.
* **Lowercase generics** in annotations: `dict[str, int]`, `list[str]`,
  `tuple[float, float]`. We do not import `Dict`, `List`, `Tuple` from
  `typing` unless we need a runtime hook. `Optional[X]` is fine where
  `X | None` is uglier in context.
* **Type-annotate the public surface.** Internal helpers may stay
  unannotated when annotations would add noise without value.
* **Dataclasses** for plain data containers (see `IBIClassificationParams`,
  `PSDResult`). Frozen when the values are configuration constants.
* **Pathlib** over `os.path`; `pathlib.Path` everywhere a path is
  passed around.

### 2.3 Errors and edge cases

* **Catch the smallest set of exceptions you can name.** Loaders catch
  `(IOError, OSError, UnicodeDecodeError, csv.Error)`, not bare
  `Exception`. A bare `Exception` hides bugs.
* **Raise `ValueError`** with a sentence that says what was expected
  and what was received: *"Need at least 4 valid samples for Welch
  PSD, got 2."* Never raise an empty exception.
* **Return NaN for under-determined metrics**, not zero. A user
  reading a CSV must be able to distinguish "this band had no power"
  from "this metric could not be computed". The metric wrappers in
  `CardioMetricsMixin` (e.g. `vlf_power`) catch
  `(KeyError, AttributeError, ValueError, IndexError)` and return
  `np.nan` precisely so a single bad epoch doesn't crash a whole table.
* **Defensive guards have a comment** explaining what they're guarding
  against. A `hasattr` check that wasn't necessary is debt; a
  `hasattr` check that documents a real interaction (older pickle
  files, partial state) is fine.

### 2.4 Logging, not printing

* Module logger is `from spectHR.Tools.Logger import logger`.
* **`logger.info`** for milestones a user might want to see.
* **`logger.debug`** for diagnostic detail.
* **`logger.warning`** for recoverable but suspicious situations
  (a heuristic firing, a fallback path, a missing optional file).
* `print` is reserved for `__main__` smoke tests in scratch scripts.

### 2.5 Configuration and single source of truth

* Defaults live in **one place**. `_DEFAULT_WORKSPACE` in
  `spectUI/workSpace.py` is canonical. Per-module dicts
  (`WELCH_PARAMS`, `LOMBSCARGLE_PARAMS`, `CARSPAN_PARAMS`,
  `HRV_FREQUENCY_BANDS`) are kept in lock-step via
  `update_params(...)`.
* When the same trio of knobs has to flow through multiple call
  sites, encode it as a dataclass and let function signatures inherit
  the defaults from it (see `IBIClassificationParams.DEFAULT_IBI_PARAMS`).
* **Magic numbers get a comment** with their physical meaning, units
  and (where possible) a literature reference. A bare `300.0` is
  not OK; `300.0  # ms, refractory period (CARSPAN T_refr)` is.

### 2.6 Extension points

* **Epoch metrics**: decorate a standalone function with
  `@epoch_metric` (in `spectHR.analysis`). It takes one argument, a
  `CardioSeriesLike` or the per-epoch `EpochContext`, and returns a
  single scalar (one CSV column, never more). It is auto-discovered by
  `PhysioData.epoched_parameters_table()` and exported in the
  Parameters table, CSV, and HDF5. This covers time-domain HRV, the
  standard band powers, and the beat-by-beat BP/RESP parameters.
* **File loaders**: write a function with signature
  `loader(physiodata, filename, **kwargs) -> None` and decorate it
  with `@register_loader(".ext")`. The decorator wires it into the
  registry; no other change is needed.
* These two decorators are the *only* sanctioned plug-in points;
  anything else should go through code review before becoming a
  pattern.

### 2.7 Library / GUI separation

* **`src/spectHR/`** is a pure-Python library. It must import
  cleanly *without* a Qt environment, GUI display, or any of the
  optional viewer dependencies. Tests run against this layer.
* **`src/spectUI/`** is the GUI built on PySide6. Imports of
  `PySide6.*` belong here, not in `spectHR/`. The one historical
  exception (`evt_loader.py` needing `EventCodeWindow`) is resolved
  by importing it lazily inside the function that uses it.
* If `import spectHR` triggers a `PySide6` import or fails on a
  headless box, that is a regression.

### 2.8 Numerical work

* **Match published conventions.** When an algorithm is in a paper
  or a reference manual (CARSPAN Eq. 3.19, Welch 1967, Lomb-Scargle),
  the docstring quotes the formula and cites the source. Sign,
  scaling and indexing conventions follow the citation literally;
  any divergence (e.g. spectHR's regular-grid DC removal in
  `carspan_strict`) is documented in the docstring as an explicit
  divergence with a justification.
* **Cross-language ports mirror the source one-to-one** before any
  refactor. `outputs/carspan_psd_reference.py` is the template:
  every step quotes the Pascal expression in a comment above the
  Python equivalent, variable names are preserved, and the
  vectorisation is explained as an *equivalence*, not a "cleaner
  version".
* **Floating-point edge cases** are guarded explicitly. The
  uniform-IBI `sd_ratio` returns `NaN` because we know the Brennan
  formula collapses into ULP-level noise, and we say so in the
  docstring.

### 2.9 Testing

* `pytest` from the project root. The full suite must remain green
  before any commit. As of writing it is 71 tests covering time-
  domain metrics, frequency-domain metrics, three PSD back-ends, and
  artefact-handling edge cases.
* **Add a test before you fix a bug.** When `sd_ratio` returned
  0.75 for uniform IBIs, the fix shipped together with
  `TestSd1Sd2.test_sd_ratio_nan_when_sd2_zero`.
* Tests use synthetic input where possible so they run on any
  machine without external data files; the `make_cs(...)` helper in
  `tests/test_hrv_metrics.py` is the canonical pattern.

### 2.10 File conventions

* **Module header** is a triple-quoted string explaining the module's
  role, not a list of classes. The role is what a reader needs first;
  the contents are obvious from the file.
* **Imports** in three groups (stdlib, third-party, project), each
  alphabetised, separated by a blank line. `from __future__` always
  comes first.
* **Constants** in `UPPER_SNAKE_CASE`. Module-private constants
  start with a leading underscore (`_Y_ZOOM_STEP_UP`,
  `_FILENAME_BAD_CHARS`). Public configuration dicts that the
  workspace mutates do *not*, `WELCH_PARAMS` is intentionally
  un-prefixed.
* **Filenames** for new modules are `lower_snake_case.py` for plain
  modules, `CamelCase.py` only when the file contains a single
  namesake class (e.g. `PhysioData.py`, `CardioSeries.py`).

---

## 3. AI-assistant guidelines

When an AI assistant edits this codebase, the rules above apply, plus:

* **Read before you write.** A change should refer to the current
  state of the file, not a remembered summary. The Edit tool requires
  a prior Read for a reason.
* **Stay surgical.** Prefer a focused Edit to a whole-file Write.
  Whole-file Writes have, in practice, occasionally truncated files
  on this Windows-mount setup; smaller diffs are safer.
* **Verify, don't trust.** After every batch of edits, syntax-check
  the modified files (`py_compile`) and run the relevant pytest
  selection. If you can't run the tests, say so.
* **Match the voice.** New docstrings, comments and README sections
  use British spelling, the same tone, the same heading style, and
  cite the same Pascal / paper sources where the surrounding text
  does.
* **Don't silently revert recent edits.** If a file shows recent
  user / linter changes (the system reminder will say so), respect
  them. If you genuinely think a recent change is wrong, raise it,
  don't reverse it.
* **Keep `import spectHR` headless.** Adding a top-level GUI import
  to anything under `src/spectHR/` is a regression even if tests pass
  on your machine.
* **Be honest about uncertainty.** When the code looks ambiguous and
  the cited literature doesn't disambiguate, say so and propose
  diagnostics rather than guessing.

---

## 4. References that shape the project's voice

* Mulder, L.J.M. (1988). *Assessment of cardiovascular reactivity by
  means of spectral analysis*. PhD thesis, University of Groningen.
* Task Force of the European Society of Cardiology and the North
  American Society of Pacing and Electrophysiology (1996). Heart
  rate variability: standards of measurement, physiological
  interpretation and clinical use. *Circulation* 93, 1043–1065.
* van Roon, A.M., Span, M.M., Lefrandt, J.D., & Riese, H. (2025).
  Overview of mathematical relations between Poincaré plot measures
  and time and frequency domain measures of heart rate variability.
  *Entropy* 27(8), 861.

The README's full reference list is the authoritative version; this
section just notes the three works whose conventions and tone
spectHR follows most closely.

### 2.11 Writing files from the AI assistant

**Never use the Write or Edit tool to write Python source files.**
Both tools write through a Windows-mount path that suffers from
filesystem-sync latency: the bash sandbox can see a stale, null-byte-
padded, or truncated version of the file for seconds to minutes after
the tool reports success. The result is silent truncation, syntax
errors on the next import, or duplicate blocks.

**Use bash writes instead.** The only safe way to modify a source file
is through the bash mount path (`/sessions/.../mnt/spectHR/...`):

```python
# Targeted patch (preferred, only the changed fragment)
python3 - << 'PYEOF'
p = '/sessions/.../mnt/spectHR/src/some/module.py'
src = open(p).read()
assert src.count(OLD) == 1          # fail fast if the pattern is ambiguous
open(p, 'w').write(src.replace(OLD, NEW, 1))
PYEOF
```

```bash
# Full rewrite (when the whole file changes)
cat > /sessions/.../mnt/spectHR/src/some/module.py << 'PYEOF'
# ... full file content ...
PYEOF
echo "wrote $(wc -l < path/to/file) lines"
```

Rules for every file write:

1. **Read first.** Use `sed -n 'X,Yp'` or `grep -n` to confirm the
   exact whitespace and text before constructing the replacement.
2. **Compile after.** Run `python3 -m py_compile <path>` immediately
   after writing to catch truncation before the next import.
3. **Check line count and null bytes.**
   `wc -l <path>` and
   `python3 -c "assert b'\x00' not in open('<path>','rb').read()"`.
4. **Assert uniqueness** before a targeted `str.replace` so a pattern
   match across multiple sites is caught as an error, not silently
   applied twice.

The Write / Edit tools remain available for Markdown, JSON, YAML, and
other non-Python assets where truncation is immediately visible and
does not silently break imports.
