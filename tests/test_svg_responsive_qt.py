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

# --- scaled to a fixed width, live figure size restored ---------------------
import re as _re

from matplotlib.figure import Figure

from spectUI.plot_export import _SVG_EXPORT_WIDTH_PT, _savefig_svg_scaled


def _viewbox_w(text):
    m = _re.search(r'viewBox="0 0 ([\d.]+) [\d.]+"', text)
    return float(m.group(1))


assert _SVG_EXPORT_WIDTH_PT == 1024.0

# A small tile and a larger figure must both come out at exactly the target
# width, regardless of their original on-screen size, with aspect preserved.
for name, figsize in (("tile", (3.2, 2.4)), ("wide", (6.4, 4.8))):
    fig = Figure(figsize=figsize)
    ax = fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 0], linewidth=1.0)
    ax.set_xlabel("Frequency (Hz)")
    orig = tuple(fig.get_size_inches())
    out = d / f"{name}.svg"
    # The export path saves scaled, then makes the result responsive.
    _savefig_svg_scaled(fig, out, 300)
    _make_svg_responsive(out)
    assert tuple(fig.get_size_inches()) == orig, f"{name}: figure size not restored"
    text = out.read_text(encoding="utf-8")
    assert abs(_viewbox_w(text) - 1024.0) < 1.0, (name, _viewbox_w(text))
    # Responsive rewrite still applies on top of the scaling.
    assert 'width="100%"' in text and 'height="100%"' in text

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
