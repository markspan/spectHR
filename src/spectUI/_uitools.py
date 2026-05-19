"""
_uitools.py - Shared GUI helpers used by the export-capable plot widgets.

Currently exposes one function:

* :func:`show_export_summary` - a consistent post-export message box that
  every widget uses so the user sees the same dialog regardless of which
  view they exported from.

Note
----
The export-directory accessor that used to live here was moved to
``spectUI.workSpace.get_export_dir``. That belongs next to the rest of
the workspace-level helpers (``LoadWorkspace``, ``SaveWorkspace``,
``psd_method_from_workspace``, ...) -- the export directory is a
workspace concept, not a UI concept.
"""

from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtWidgets import QMessageBox, QWidget


def show_export_summary(
    parent: Optional[QWidget],
    *,
    context: str,
    summary: str,
    failures: Iterable[str] = (),
) -> None:
    """Show a uniform post-export message box.

    When *failures* is empty an :func:`QMessageBox.information` dialog
    is shown with title ``"{context} export"`` and *summary* as the
    body. When at least one failure is present the dialog is downgraded
    to :func:`QMessageBox.warning` with title
    ``"{context} export (with warnings)"`` and the failures appended as
    a bulleted list, so the user notices something went wrong without
    having to check the log file.

    Parameters
    ----------
    parent : QWidget or None
        Parent widget for the dialog -- positions the box over the
        widget that issued the export.
    context : str
        Short human label that names the export (``"PSD"``, ``"Profile"``,
        ``"Parameters"``, ...).
    summary : str
        The main message line. The caller should also have written this
        exact string to the logger so the dialog and the log file stay
        in sync.
    failures : iterable of str, optional
        Per-file failure messages. Empty by default.
    """
    failure_list = list(failures)
    if failure_list:
        body = summary + "\n\nProblems:\n  - " + "\n  - ".join(failure_list)
        QMessageBox.warning(parent, f"{context} export (with warnings)", body)
    else:
        QMessageBox.information(parent, f"{context} export", summary)
