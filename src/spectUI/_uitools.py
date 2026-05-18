"""
_uitools.py - Shared GUI helpers used by the export-capable plot widgets.

Centralises three things that PSDPlotWidget, ProfilePlotWidget, and
ParametersPlotWidget previously duplicated:

* The fallback export-directory constant (DEFAULT_EXPORT_DIR).
* ``resolve_export_dir(workspace)`` -- pull the configured output folder
  out of a workspace dict, with a logged fallback when it's missing.
* ``show_export_summary(parent, context, summary, failures=())`` -- a
  consistent post-export message box used by every widget so the user
  sees the same dialog regardless of which view they exported from.

Keeping these in one place means a change to the dialog style (icon,
button set, wording) or to the workspace key only has to happen once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from platformdirs import user_documents_path
from PySide6.QtWidgets import QMessageBox, QWidget

from spectHR.Tools.Logger import logger


# Default location used when no workspace is supplied -- mirrors the
# ``OutputDirectory`` default in ``spectUI.workSpace._DEFAULT_WORKSPACE``.
DEFAULT_EXPORT_DIR: Path = user_documents_path() / "spectHR" / "export"


def resolve_export_dir(
    workspace: Optional[dict[str, Any]],
    *,
    context: str = "Export",
) -> Path:
    """
    Return the configured export directory, with a logged fallback.

    Looks up ``workspace["Directories"]["OutputDirectory"]`` and returns
    it as a :class:`Path`. When the workspace is ``None`` or the expected
    nesting is missing the function emits a warning and falls back to
    :data:`DEFAULT_EXPORT_DIR` so the export still has somewhere to land.

    Parameters
    ----------
    workspace : dict or None
        The workspace dictionary as loaded by ``LoadWorkspace``. May be
        ``None`` when a widget was constructed without one.
    context : str, optional
        Short label inserted into the warning message (e.g. ``"PSD"``,
        ``"Profile"``, ``"Parameters"``).  Defaults to ``"Export"``.

    Returns
    -------
    Path
        The directory the caller should write to.  Existence is **not**
        guaranteed; callers should call ``mkdir(parents=True,
        exist_ok=True)`` and handle ``OSError`` themselves.
    """
    if workspace is not None:
        try:
            return Path(workspace["Directories"]["OutputDirectory"])
        except (KeyError, TypeError):
            logger.warning(
                f"{context} export: workspace lacks "
                "Directories.OutputDirectory; falling back to default "
                "export folder."
            )
    return DEFAULT_EXPORT_DIR


def show_export_summary(
    parent: Optional[QWidget],
    *,
    context: str,
    summary: str,
    failures: Iterable[str] = (),
) -> None:
    """
    Show a uniform post-export message box.

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
        ``"Parameters"``, ``"HRV/PSD/Profiles"``, ...).
    summary : str
        The main message line.  Already shown to the logger by the
        caller; we present the exact same string here so the log file
        and the dialog stay in sync.
    failures : iterable of str, optional
        Per-file failure messages.  Empty by default.
    """
    failure_list = list(failures)
    if failure_list:
        body = summary + "\n\nProblems:\n  - " + "\n  - ".join(failure_list)
        QMessageBox.warning(parent, f"{context} export (with warnings)", body)
    else:
        QMessageBox.information(parent, f"{context} export", summary)
