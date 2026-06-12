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


def _scale_ymax(freqs: np.ndarray, power: np.ndarray, bands: dict) -> float:
    """Peak power within the named (non-FullRange) bands, above the VLF floor."""
    named = [s for n, s in bands.items() if n != "FullRange" and "low" in s]
    if not named or freqs.size == 0:
        return float(np.nanmax(power)) if power.size else 0.0
    lo = max(min(float(s["low"]) for s in named), _Y_SCALE_F_MIN)
    hi = max(float(s["high"]) for s in named)
    mask = (freqs >= lo) & (freqs <= hi)
    return float(np.nanmax(power[mask])) if np.any(mask) else 0.0


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

    *value_fmt* maps a band name to its legend value string (e.g. the
    integrated power); when ``None`` the band power of *curve* is used.
    """
    for name, spec in bands.items():
        if "low" not in spec or "high" not in spec:
            continue
        lo, hi = float(spec["low"]), float(spec["high"])
        mask = (freqs >= lo) & (freqs <= hi)
        if not np.any(mask):
            continue
        if value_fmt is not None:
            label = f"{name}: {value_fmt(name)}"
        else:
            bp = band_power_rectangular(freqs, curve, lo, hi)
            label = f"{name}: {bp:.1f} {unit}".strip()
        ax.fill_between(
            freqs[mask], 0.0, curve[mask],
            color=spec.get("color", "gray"),
            alpha=float(spec.get("alpha", 0.30)),
            label=label,
            zorder=0 if name == "FullRange" else 4,
        )


def draw_psd_tile(ax: Axes, result, bands: dict, *, ci_alpha: float = 0.05) -> None:
    """Draw one epoch's PSD the V2 way: CI shading, band fills, black line.

    *result* is a :class:`~spectHR.analysis.psd.PSDResult` (``freqs`` /
    ``power`` / ``unit`` and optional ``ci_lower`` / ``ci_upper``).
    """
    if result is None or result.freqs.size == 0:
        ax.text(0.5, 0.5, "Insufficient data", ha="center", va="center",
                transform=ax.transAxes, color="gray")
        ax.set_xticks([]); ax.set_yticks([])
        return

    f, p = result.freqs, result.power
    x0, x1 = band_x_range(bands)
    ax.set_xlim(x0, x1)

    if result.ci_lower is not None and result.ci_upper is not None:
        ci_pct = int(round((1.0 - ci_alpha) * 100))
        ax.fill_between(f, result.ci_lower, result.ci_upper,
                        color="gray", alpha=0.20, zorder=1, label=f"{ci_pct} % CI")

    draw_band_fills(ax, f, p, bands, unit=strip_per_hz(result.unit))
    ax.plot(f, p, "k", linewidth=1.0, alpha=0.85, zorder=3)

    ymax = _scale_ymax(f, p, bands)
    ax.set_ylim(0.0, max(ymax * 1.1, 1e-12))
    ax.set_ylabel(strip_per_hz(result.unit) or "power", fontsize=8)
    ax.set_xlabel("Frequency (Hz)", fontsize=8)
    ax.legend(fontsize=6, loc="upper right", framealpha=0.6)
