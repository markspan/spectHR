# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Shared spectral-tile drawing, ported from the V2 plot widgets.

These are *display* routines (matplotlib only): they take an already-computed
``spectHR`` result plus the workspace band table and render a tile the V2 way
— confidence-interval shading, a black PSD line, per-band under-curve fills
labelled with their integrated power, and a unit-bearing y-axis.  The PSD and
the (Bode) transfer modulus panel share the same band-fill style.
"""
from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes

from spectHR.analysis._smoothing import smooth3
from spectHR.analysis.psd import band_power_rectangular

# Frequencies below this are excluded when auto-scaling y, so VLF drift power
# does not dominate the axis (V2 ``Y_SCALE_F_MIN``).
_Y_SCALE_F_MIN = 0.08


def band_x_range(bands: dict) -> tuple[float, float]:
    """X-axis range (Hz): ``FullRange`` if present, else the band union."""
    if not bands:
        return 0.0, 0.5
    if "FullRange" in bands:
        return float(bands["FullRange"]["low"]), float(bands["FullRange"]["high"])
    lows = [float(s["low"]) for s in bands.values() if "low" in s]
    highs = [float(s["high"]) for s in bands.values() if "high" in s]
    return (min(lows), max(highs)) if lows else (0.0, 0.5)


def strip_per_hz(unit: str) -> str:
    """Drop a ``/Hz`` suffix — band power is the PSD integrated over Hz."""
    u = (unit or "").strip()
    for suffix in ("/Hz", "/hz", " /Hz", " /hz"):
        if u.endswith(suffix):
            return u[: -len(suffix)].rstrip()
    return u


def band_color(bands: dict, name: str, default: str = "#7f8c8d") -> str:
    """Colour configured for *name* in the band table."""
    spec = bands.get(name) if isinstance(bands, dict) else None
    return spec.get("color", default) if isinstance(spec, dict) else default


def _scale_ymax(
    freqs: np.ndarray,
    power: np.ndarray,
    bands: dict,
    ci_upper: np.ndarray | None = None,
) -> float:
    """Peak power within the named (non-FullRange) bands, above the VLF floor.

    Mirrors V2 ``_y_max``: the upper CI bound is allowed to lift the limit,
    but only up to 3× the PSD peak so a wide CI (short epochs) does not blow
    the axis up.
    """
    named = [s for n, s in bands.items() if n != "FullRange" and "low" in s]
    if not named or freqs.size == 0:
        return float(np.nanmax(power)) if power.size else 0.0
    lo = max(min(float(s["low"]) for s in named), _Y_SCALE_F_MIN)
    hi = max(float(s["high"]) for s in named)
    mask = (freqs >= lo) & (freqs <= hi)
    if not np.any(mask):
        return 0.0
    peak = float(np.nanmax(power[mask]))
    if ci_upper is not None and peak > 0.0:
        ci_peak = float(np.nanmax(ci_upper[mask]))
        peak = max(peak, min(ci_peak, peak * 3.0))
    return peak


def _band_draw_extents(bands: dict) -> dict[str, tuple[float, float]]:
    """Map each band to the ``(draw_low, draw_high)`` its fill should span.

    With CARSPAN-style gapped bands (e.g. ``0.06→0.07`` then ``0.07→0.14``)
    the polygon edges are pushed out to the midpoint shared with the
    neighbouring band so the coloured fills *meet* visually instead of
    leaving a gap (V2 ``_band_draw_extents``).  ``FullRange`` keeps its own
    range; the band-power *integration* still uses each band's configured
    edges (handled by the caller).
    """
    named = sorted(
        ((n, s) for n, s in bands.items()
         if n != "FullRange" and "low" in s and "high" in s),
        key=lambda kv: float(kv[1]["low"]),
    )
    extents: dict[str, tuple[float, float]] = {}
    for i, (name, spec) in enumerate(named):
        draw_low, draw_high = float(spec["low"]), float(spec["high"])
        if i > 0:
            draw_low = (float(named[i - 1][1]["high"]) + float(spec["low"])) / 2.0
        if i < len(named) - 1:
            draw_high = (float(spec["high"]) + float(named[i + 1][1]["low"])) / 2.0
        extents[name] = (draw_low, draw_high)
    full = bands.get("FullRange")
    if isinstance(full, dict) and "low" in full and "high" in full:
        extents["FullRange"] = (float(full["low"]), float(full["high"]))
    return extents


def draw_band_fills(
    ax: Axes,
    freqs: np.ndarray,
    curve: np.ndarray,
    bands: dict,
    *,
    unit: str = "",
    value_fmt=None,
) -> None:
    """Fill the area under *curve* for each band, PSD-style, with a legend.

    Adjacent band fills are extended to the midpoint shared with their
    neighbour so the colours connect at the boundaries (V2 behaviour); the
    legend value is still integrated over each band's *configured* edges.
    *value_fmt* maps a band name to its legend value string (e.g. the
    integrated power); when ``None`` the band power of *curve* is used.
    """
    extents = _band_draw_extents(bands)
    for name, spec in bands.items():
        if "low" not in spec or "high" not in spec:
            continue
        lo, hi = float(spec["low"]), float(spec["high"])
        draw_low, draw_high = extents[name]
        # Polygon spans the extended range with interpolated endpoints so the
        # fill reaches exactly to the neighbour midpoint.
        mask = (freqs >= draw_low) & (freqs <= draw_high)
        if not np.any(mask):
            continue
        p_lo = float(np.interp(draw_low, freqs, curve))
        p_hi = float(np.interp(draw_high, freqs, curve))
        f_band = np.concatenate(([draw_low], freqs[mask], [draw_high]))
        p_band = np.concatenate(([p_lo], curve[mask], [p_hi]))
        if value_fmt is not None:
            label = f"{name}: {value_fmt(name)}"
        else:
            bp = band_power_rectangular(freqs, curve, lo, hi)
            label = f"{name}: {bp:.1f} {unit}".strip()
        ax.fill_between(
            f_band, 0.0, p_band,
            color=spec.get("color", "gray"),
            alpha=float(spec.get("alpha", 0.30)),
            label=label,
            zorder=0 if name == "FullRange" else 4,
        )


def draw_psd_tile(
    ax: Axes, result, bands: dict, *, ci_alpha: float = 0.05, smooth: bool = False
) -> None:
    """Draw one epoch's PSD the V2 way: CI shading, band fills, black line.

    *result* is a :class:`~spectHR.analysis.psd.PSDResult` (``freqs`` /
    ``power`` / ``unit`` and optional ``ci_lower`` / ``ci_upper``).

    When *smooth* is True the displayed curve and confidence interval are
    passed through CARSPAN's 3-point moving average (manual §3.2) — the
    plot-only smoother V2 applies to the CARSPAN spectra.  Band-power legend
    values are always integrated on the *raw* (unsmoothed) periodogram, so
    the numbers match the compute layer exactly while the drawn curve is the
    smooth display one.
    """
    if result is None or result.freqs.size == 0:
        ax.text(0.5, 0.5, "Insufficient data", ha="center", va="center",
                transform=ax.transAxes, color="gray")
        ax.set_xticks([]); ax.set_yticks([])
        return

    f, p_raw = result.freqs, result.power
    ci_lo, ci_hi = result.ci_lower, result.ci_upper
    if smooth:
        p = smooth3(p_raw)
        ci_lo = smooth3(ci_lo) if ci_lo is not None else None
        ci_hi = smooth3(ci_hi) if ci_hi is not None else None
    else:
        p = p_raw

    x0, x1 = band_x_range(bands)
    ax.set_xlim(x0, x1)

    if ci_lo is not None and ci_hi is not None:
        ci_pct = int(round((1.0 - ci_alpha) * 100))
        ax.fill_between(f, ci_lo, ci_hi,
                        color="gray", alpha=0.20, zorder=1, label=f"{ci_pct} % CI")
        for ci_line in (ci_lo, ci_hi):
            ax.plot(f, ci_line, color="gray", lw=0.7, ls="--", alpha=0.55, zorder=2)

    # Band power from the raw spectrum; the fill/line use the display curve.
    unit = strip_per_hz(result.unit)
    values = {
        name: band_power_rectangular(f, p_raw, float(s["low"]), float(s["high"]))
        for name, s in bands.items() if "low" in s and "high" in s
    }
    draw_band_fills(
        ax, f, p, bands, unit=unit,
        value_fmt=lambda n: f"{values[n]:.1f} {unit}".strip(),
    )
    ax.plot(f, p, "k", linewidth=1.0, alpha=0.85, zorder=3)

    ymax = _scale_ymax(f, p, bands, ci_hi)
    ax.set_ylim(0.0, max(ymax * 1.1, 1e-12))
    ax.set_ylabel(unit or "power", fontsize=8)
    ax.set_xlabel("Frequency (Hz)", fontsize=8)
    ax.legend(fontsize=6, loc="upper right", framealpha=0.6)

    # PSD method name in the upper-left corner (V2's left-loc subtitle).
    method_label = (result.method or "").replace("_", " ").strip().capitalize()
    if method_label:
        ax.text(0.02, 0.97, method_label, transform=ax.transAxes,
                ha="left", va="top", fontsize=7, color="dimgray")

    # Drop the top / right spines (V2 styling).
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
