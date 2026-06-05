#!/usr/bin/env python3
"""Draw the spectHR HDF5 export structure as a tree diagram."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

# ── palette ──────────────────────────────────────────────────────────────────
C_ROOT   = "#1b3d6e"   # file root
C_EPOCH  = "#25659b"   # epoch group
C_GRP    = "#3282b8"   # required sub-group
C_OPT    = "#4898c4"   # optional sub-group (dashed border)
C_BAND   = "#6fb3d8"   # band sub-group
C_ATTR   = "#daeaf5"   # attribute chip
C_DS     = "#fff8e1"   # dataset chip
C_TXT    = "white"
C_BG     = "#f0f4f8"

# ── helpers ───────────────────────────────────────────────────────────────────

def box(ax, x, y, w, h, color, label, fontsize=8.5, bold=True,
        dashed=False, radius=0.06, text_color=C_TXT):
    lw = 1.2 if not dashed else 1.0
    ls = "--" if dashed else "-"
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.02,rounding_size={radius}",
        facecolor=color, edgecolor="white",
        linewidth=lw, linestyle=ls, zorder=3,
    )
    ax.add_patch(rect)
    weight = "bold" if bold else "normal"
    ax.text(x + w / 2, y + h / 2, label,
            ha="center", va="center",
            fontsize=fontsize, fontweight=weight,
            color=text_color, zorder=4, clip_on=True)
    return rect


def chip(ax, x, y, w, h, label, color, fontsize=6.5, text_color=C_TXT, icon=""):
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.04",
        facecolor=color, edgecolor="none",
        linewidth=0, zorder=4,
    )
    ax.add_patch(rect)
    ax.text(x + 0.05, y + h / 2, f"{icon}{label}",
            ha="left", va="center",
            fontsize=fontsize, color=text_color,
            family="monospace", zorder=5, clip_on=True)


def vline(ax, x, y1, y2, color="#aabccc", lw=0.8, dashed=False):
    ls = (0, (4, 3)) if dashed else "-"
    ax.plot([x, x], [y1, y2], color=color, lw=lw, linestyle=ls, zorder=1)


def hline(ax, x1, x2, y, color="#aabccc", lw=0.8, dashed=False):
    ls = (0, (4, 3)) if dashed else "-"
    ax.plot([x1, x2], [y, y], color=color, lw=lw, linestyle=ls, zorder=1)


def connector(ax, px, py_bottom, cx, cy_top, dashed=False):
    """L-shaped connector: down from parent bottom, across, up to child top."""
    mid_y = (py_bottom + cy_top) / 2
    color = "#8aaabb"
    lw = 0.8
    ls = (0, (4, 3)) if dashed else "-"
    ax.plot([px, px], [py_bottom, mid_y], color=color, lw=lw, linestyle=ls, zorder=1)
    ax.plot([px, cx], [mid_y, mid_y],     color=color, lw=lw, linestyle=ls, zorder=1)
    ax.plot([cx, cx], [mid_y, cy_top],    color=color, lw=lw, linestyle=ls, zorder=1)


# ── chip lists ────────────────────────────────────────────────────────────────
# Returns the y-coordinate below the last chip drawn.

def draw_chips(ax, x, y, w, items, color, icon, fontsize=6.5):
    ch = 0.22
    gap = 0.03
    for label in items:
        chip(ax, x, y - ch, w, ch, label, color, fontsize=fontsize, icon=icon,
             text_color="#1a2a3a" if color == C_ATTR else C_TXT)
        y -= ch + gap
    return y  # bottom y after last chip


# ── figure ────────────────────────────────────────────────────────────────────
FIG_W, FIG_H = 22, 28
fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
ax.set_xlim(0, FIG_W)
ax.set_ylim(0, FIG_H)
ax.axis("off")
fig.patch.set_facecolor(C_BG)
ax.set_facecolor(C_BG)

# ── title ─────────────────────────────────────────────────────────────────────
ax.text(FIG_W / 2, 27.4, "{basename}.h5  — spectHR export structure",
        ha="center", va="center", fontsize=13, fontweight="bold", color="#1b3d6e")

# ═══════════════════════════════════════════════════════════════════════
# ROOT  (file-level attrs)
# ═══════════════════════════════════════════════════════════════════════
ROOT_X, ROOT_Y, ROOT_W, ROOT_H = 8.5, 25.8, 5, 0.45
box(ax, ROOT_X, ROOT_Y, ROOT_W, ROOT_H, C_ROOT, "{basename}.h5", fontsize=9)

root_attrs = ["subject", "exported_at", "specthr_export_version"]
ry = ROOT_Y
cw = ROOT_W - 0.1
cx = ROOT_X + 0.05
for a in root_attrs:
    ry -= 0.25
    chip(ax, cx, ry, cw, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")

ROOT_BOT = ry - 0.05  # bottom of root block

# ═══════════════════════════════════════════════════════════════════════
# EPOCH  (one per epoch)
# ═══════════════════════════════════════════════════════════════════════
EP_X, EP_Y = 7.5, ROOT_BOT - 0.35
EP_W, EP_H = 7, 0.42
box(ax, EP_X, EP_Y, EP_W, EP_H, C_EPOCH,
    "/{epoch}/   (one group per epoch, e.g. \"Epoch 1\")", fontsize=8.5)

# connector from root
vline(ax, ROOT_X + ROOT_W / 2, ROOT_BOT, EP_Y + EP_H)
ax.annotate("", xy=(ROOT_X + ROOT_W / 2, EP_Y + EP_H),
            xytext=(ROOT_X + ROOT_W / 2, ROOT_BOT),
            arrowprops=dict(arrowstyle="-|>", color="#8aaabb", lw=0.9))

# epoch attrs (scalars)
ep_attrs_left  = ["subject",  "count",  "mean_ibi",  "rmssd",  "sdnn",  "sd1",  "sd2"]
ep_attrs_right = ["lf_power", "hf_power", "vlf_power", "lf_hf", "bp_sbp", "bp_dbp", "resp_mvo", "rsa", "rsa0", "…"]

ew = 3.4
ey = EP_Y
for a in ep_attrs_left:
    ey -= 0.25
    chip(ax, EP_X + 0.05, ey, ew - 0.1, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")

ey2 = EP_Y
for a in ep_attrs_right:
    ey2 -= 0.25
    chip(ax, EP_X + ew + 0.05, ey2, ew - 0.1, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")

EP_BOT = min(ey, ey2) - 0.1

# label
ax.text(EP_X + EP_W / 2, EP_BOT + 0.04,
        "all scalar metrics as group attributes", ha="center", va="top",
        fontsize=6, color="#4a6a8a", style="italic")

# ═══════════════════════════════════════════════════════════════════════
# Five sub-groups of epoch  (spaced horizontally)
# ═══════════════════════════════════════════════════════════════════════
#    /psd/  /profile/  /transfer/*  /transfer_profile/*  /respiration/*
# x-centres:  2.2   5.8   9.4   13.6   18.8
BRANCH_Y = EP_BOT - 0.50
GH = 0.38   # group header height
GW = 3.8    # group box width

branches = [
    # (x_centre, label, optional, color)
    (2.2,  "/psd/",              False, C_GRP),
    (6.4,  "/profile/",          False, C_GRP),
    (10.9, "/transfer/",         True,  C_OPT),
    (15.5, "/transfer_profile/", True,  C_OPT),
    (19.8, "/respiration/",      True,  C_OPT),
]

EP_CX = EP_X + EP_W / 2   # epoch centre x

# horizontal connector bar at BRANCH_Y + GH
CONN_Y = BRANCH_Y + GH + 0.25
hline(ax, 2.2, 19.8, CONN_Y)
vline(ax, EP_CX, EP_BOT, CONN_Y)

for bx, blabel, bopt, bcol in branches:
    # vertical drop to box top
    vline(ax, bx, CONN_Y, BRANCH_Y + GH, dashed=bopt)
    box(ax, bx - GW / 2, BRANCH_Y, GW, GH, bcol, blabel,
        fontsize=8, dashed=bopt)

# ─────────── /psd/ detail ───────────────────────────────────────────
px = 2.2
py = BRANCH_Y - 0.08

psd_attrs = ["method", "unit", "psd_unit", "freq_resolution"]
psd_ds    = ["freqs [N_f]", "power [N_f]"]

aw = GW - 0.12
for a in psd_attrs:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")
for d in psd_ds:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

# band sub-group
py -= 0.38
BAND_W = GW - 0.2
box(ax, px - BAND_W/2, py, BAND_W, 0.34, C_BAND, "/{band}/  ×N", fontsize=7.5)
vline(ax, px, py + 0.34, py + 0.34 + 0.04)
band_attrs = ["low", "high", "integrated_power", "unit"]
band_ds    = ["freqs [N_b]", "power [N_b]"]
for a in band_attrs:
    py -= 0.25
    chip(ax, px - BAND_W/2 + 0.06, py, BAND_W - 0.12, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")
for d in band_ds:
    py -= 0.25
    chip(ax, px - BAND_W/2 + 0.06, py, BAND_W - 0.12, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

PSD_BOT = py

# ─────────── /profile/ detail ────────────────────────────────────────
px = 6.4
py = BRANCH_Y - 0.08

prof_attrs = ["method", "unit", "window_s", "step_s",
              "adaptive_band", "adaptive_source", "n_windows"]
prof_ds    = ["timestamps [N_w]", "t_rel [N_w]", "resp_freqs [N_w]*"]

aw = GW - 0.12
for a in prof_attrs:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")
for d in prof_ds:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

py -= 0.38
BAND_W = GW - 0.2
box(ax, px - BAND_W/2, py, BAND_W, 0.34, C_BAND, "/{band}/  ×N", fontsize=7.5)
band_attrs = ["mean", "std", "min", "max", "t_max"]
band_ds    = ["power [N_w]"]
for a in band_attrs:
    py -= 0.25
    chip(ax, px - BAND_W/2 + 0.06, py, BAND_W - 0.12, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")
for d in band_ds:
    py -= 0.25
    chip(ax, px - BAND_W/2 + 0.06, py, BAND_W - 0.12, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

PROF_BOT = py

# ─────────── /transfer/ detail ───────────────────────────────────────
px = 10.9
py = BRANCH_Y - 0.08

tf_attrs = ["method", "freq_resolution", "smooth", "min_coherence", "f_max"]
tf_ds    = ["freqs [N_f]", "modulus [N_f]",
            "phase_wrapped [N_f]", "phase_unwrapped [N_f]", "coherence [N_f]"]

aw = GW - 0.12
for a in tf_attrs:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")
for d in tf_ds:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

py -= 0.38
BAND_W = GW - 0.2
box(ax, px - BAND_W/2, py, BAND_W, 0.34, C_BAND, "/{band}/  ×N", fontsize=7.5)
band_attrs = ["low", "high", "modulus", "phase_wrapped",
              "phase_unwrapped", "weighted_coherence",
              "n_points", "n_coherent"]
band_ds    = ["freqs [N_b]", "modulus_raw [N_b]",
              "phase_wrapped_raw [N_b]",
              "phase_unwrapped_raw [N_b]",
              "coherence_raw [N_b]"]
for a in band_attrs:
    py -= 0.25
    chip(ax, px - BAND_W/2 + 0.06, py, BAND_W - 0.12, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")
for d in band_ds:
    py -= 0.25
    chip(ax, px - BAND_W/2 + 0.06, py, BAND_W - 0.12, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

TF_BOT = py

# ─────────── /transfer_profile/ detail ───────────────────────────────
px = 15.5
py = BRANCH_Y - 0.08

tfp_attrs = ["method", "window_s", "step_s", "smooth",
             "min_coherence", "f_max", "n_windows"]
tfp_ds    = ["timestamps [N_w]"]

aw = GW - 0.12
for a in tfp_attrs:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")
for d in tfp_ds:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

py -= 0.38
BAND_W = GW - 0.2
box(ax, px - BAND_W/2, py, BAND_W, 0.34, C_BAND, "/{band}/  ×N", fontsize=7.5)
band_ds = ["modulus [N_w]", "phase [N_w]",
           "phase_unwrapped [N_w]",
           "weighted_coherence [N_w]", "n_coherent [N_w]"]
for d in band_ds:
    py -= 0.25
    chip(ax, px - BAND_W/2 + 0.06, py, BAND_W - 0.12, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

TFP_BOT = py

# ─────────── /respiration/ detail ────────────────────────────────────
px = 19.8
py = BRANCH_Y - 0.08

rsp_attrs = ["lag_s", "n_breaths", "n_valid"]
rsp_ds    = ["rsa [N_br]", "rsa0 [N_br]", "breath_times [N_br]"]

aw = GW - 0.12
for a in rsp_attrs:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, a, C_ATTR, icon="@ ", text_color="#1a2a3a")
for d in rsp_ds:
    py -= 0.25
    chip(ax, px - GW/2 + 0.06, py, aw, 0.22, d, C_DS, icon="[] ", text_color="#1a2a3a")

RSP_BOT = py

# ═══════════════════════════════════════════════════════════════════════
# LEGEND
# ═══════════════════════════════════════════════════════════════════════
LEG_BOT = min(PSD_BOT, PROF_BOT, TF_BOT, TFP_BOT, RSP_BOT) - 0.5
lx = 1.0
ly = LEG_BOT

legend_items = [
    (C_ROOT,  "File root"),
    (C_EPOCH, "Epoch group"),
    (C_GRP,   "Required sub-group"),
    (C_OPT,   "Optional sub-group  (needs rsp / bp channel)"),
    (C_BAND,  "Band sub-group  (×N per configured band)"),
    (C_ATTR,  "@ attribute  (scalar)"),
    (C_DS,    "[] dataset  (float64 array)"),
]
for lcolor, ltxt in legend_items:
    rect = FancyBboxPatch(
        (lx, ly), 0.5, 0.22,
        boxstyle="round,pad=0.02,rounding_size=0.04",
        facecolor=lcolor, edgecolor="none",
    )
    ax.add_patch(rect)
    ax.text(lx + 0.6, ly + 0.11, ltxt, va="center", fontsize=7,
            color="#1a2a3a" if lcolor in (C_ATTR, C_DS) else C_TXT)
    ly -= 0.30

ax.text(lx, ly - 0.1,
        "*  resp_freqs present only for adaptive-band profiles\n"
        "   [N_f] = PSD frequency bins · [N_w] = profile windows\n"
        "   [N_b] = in-band frequency bins · [N_br] = breath cycles",
        va="top", fontsize=6.5, color="#4a6a8a", style="italic")

# ═══════════════════════════════════════════════════════════════════════
# save
# ═══════════════════════════════════════════════════════════════════════
for out, opts in [
    ("/home/user/spectHR/images/h5_structure.png", {"dpi": 150}),
    ("/home/user/spectHR/images/h5_structure.pdf", {}),
]:
    fig.savefig(out, bbox_inches="tight", facecolor=C_BG, **opts)
    print(f"Saved → {out}")
