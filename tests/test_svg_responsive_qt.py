# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Exported SVGs scale to fill a browser window.

Subprocess-isolated (importing spectUI pulls Qt).  ``_make_svg_responsive``
replaces matplotlib's fixed pt width/height on the root <svg> with 100% so a
browser scales the figure to the viewport, keeping (or synthesising) a viewBox.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DRIVER = r"""
import tempfile
from pathlib import Path

from spectUI.plot_export import _make_svg_responsive

d = Path(tempfile.mkdtemp())

# matplotlib-style SVG: fixed pt width/height plus a viewBox.
svg1 = (
    '<?xml version="1.0" encoding="utf-8" standalone="no"?>\n'
    '<svg xmlns:xlink="http://www.w3.org/1999/xlink" width="460.8pt" '
    'height="345.6pt" viewBox="0 0 460.8 345.6" '
    'xmlns="http://www.w3.org/2000/svg" version="1.1">\n'
    '<rect width="10" height="10"/></svg>\n'
)
p1 = d / "a.svg"
p1.write_text(svg1, encoding="utf-8")
_make_svg_responsive(p1)
out1 = p1.read_text(encoding="utf-8")
assert 'width="100%"' in out1 and 'height="100%"' in out1, out1
assert 'viewBox="0 0 460.8 345.6"' in out1, out1
assert "460.8pt" not in out1 and "345.6pt" not in out1, out1

# No viewBox: one is synthesised from the numeric width/height.
svg2 = ('<svg xmlns="http://www.w3.org/2000/svg" width="200pt" height="100pt">'
        '<rect/></svg>')
p2 = d / "b.svg"
p2.write_text(svg2, encoding="utf-8")
_make_svg_responsive(p2)
out2 = p2.read_text(encoding="utf-8")
assert 'viewBox="0 0 200 100"' in out2, out2
assert 'width="100%"' in out2 and 'height="100%"' in out2, out2

# A non-SVG file must be left untouched and never raise.
p3 = d / "c.txt"
p3.write_text("not an svg", encoding="utf-8")
_make_svg_responsive(p3)
assert p3.read_text(encoding="utf-8") == "not an svg"

# --- line/font scaling: applied within the context, restored on exit --------
from matplotlib.figure import Figure

from spectUI.parameters import Parameters
from spectUI.plot_export import _scaled_line_and_font

fig = Figure(figsize=(3.2, 2.4))
ax = fig.add_subplot(111)
(line,) = ax.plot([0, 1, 2], [0, 1, 0], linewidth=2.0)
ax.set_xlabel("Frequency (Hz)")
lbl = ax.xaxis.get_label()
lw0 = line.get_linewidth()
fs0 = lbl.get_fontsize()

with _scaled_line_and_font(fig, 0.5):
    assert abs(line.get_linewidth() - lw0 * 0.5) < 1e-9, line.get_linewidth()
    assert abs(lbl.get_fontsize() - fs0 * 0.5) < 1e-9, lbl.get_fontsize()
# restored on exit
assert abs(line.get_linewidth() - lw0) < 1e-9
assert abs(lbl.get_fontsize() - fs0) < 1e-9

# factor 1.0 is a no-op
with _scaled_line_and_font(fig, 1.0):
    assert line.get_linewidth() == lw0

# The setting is exposed and defaults to 0.5.
p = Parameters.default()
assert p.export_line_font_scale == 0.5
p2 = Parameters.from_dict({"Export": {"vector_line_font_scale": 0.3}})
assert p2.export_line_font_scale == 0.3

print("SVG_RESPONSIVE_OK")
"""


def test_svg_export_is_responsive():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0 and "SVG_RESPONSIVE_OK" in proc.stdout, (
        f"svg-responsive test failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
