# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from spectHR.logger import logger


class DraggableVLine:
    """
    A draggable vertical line on a plot.

    Attributes:
        line (matplotlib.lines.Line2D): The line object representing the vertical line.
    """
    active_line = None  # Shared among all instances
    mode = 'Drag'
    line = None

    def __init__(self, ax, x_position, callback_drag=None, callback_remove=None, color='red'):
        """
        Initializes DraggableVLine at a specified x position.

        Args:
            ax (matplotlib.axes.Axes): The axes to place the vertical line on.
            x_position (float): The initial x-coordinate for the line.
            callback_drag (callable, optional): Called with (old_x, new_x) on release.
            callback_remove (callable, optional): Called with (old_x, new_x) when removed.
        """
        self.ax = ax
        y_top = self.ax.get_ylim()[1]

        self.line, = self.ax.plot(
            [x_position, x_position],
            [0.0, y_top],
            transform=self.ax.get_xaxis_transform(),
            color=color,
            lw=0.8,
            linestyle='-',
            alpha=0.5,
            picker=True,
            pickradius=10,
            zorder=6,
        )
        self.callback_drag = callback_drag
        self.callback_remove = callback_remove
        self.press = None
        self._canvas = None
        self._cids: list[int] = []
        self.connect(ax.figure)

    def update_y_extent(self):
        """
        Update vertical extent so the line ends at data y = 0
        and the current top of the axis.
        """
        if self.line is None:
            return
        y_top = self.ax.get_ylim()[1]
        self.line.set_ydata([0.0, y_top])

    def on_press(self, event):
        """
        Captures the initial click location if near the line.

        Args:
            event (matplotlib.backend_bases.Event): The mouse press event.
        """
        if (DraggableVLine.mode == 'Drag') or (DraggableVLine.mode == 'Remove'):
            if (
                DraggableVLine.active_line is None
                and event.xdata is not None
                and self.line.contains(event)[0]
            ):
                DraggableVLine.active_line = self.line
                self.press = self.line.get_xdata()[0]

    def on_drag(self, event):
        """
        Drags the line to follow the mouse's x position.

        Args:
            event (matplotlib.backend_bases.Event): The mouse drag event.
        """
        if DraggableVLine.mode == 'Drag':
            if DraggableVLine.active_line is self.line:
                if event.xdata is None:
                    return
                self.line.set_xdata([event.xdata, event.xdata])
                self.ax.figure.canvas.draw_idle()

    def on_release(self, event):
        """Fire the appropriate callback and reset drag state on mouse release.

        Does nothing when the line was not pressed (``self.press is None``) or
        the current mode is not ``'Drag'`` or ``'Remove'``.

        Args:
            event (matplotlib.backend_bases.Event): The mouse release event.
        """
        if DraggableVLine.mode not in ('Drag', 'Remove') or self.press is None:
            return

        if DraggableVLine.mode == 'Drag':
            if self.callback_drag:
                self.callback_drag(self.press, event.xdata)

        elif DraggableVLine.mode == 'Remove':
            if self.callback_remove:
                self.callback_remove(self.press, event.xdata)
            DraggableVLine.active_line = None
            try:
                self.line.remove()
            except NotImplementedError:
                pass
            finally:
                self.line = None  # Ensure the line reference is cleared

        self.press = None
        DraggableVLine.active_line = None

    def connect(self, fig):
        """
        Connects events for dragging the line.

        The connection ids are kept so :meth:`disconnect` can remove them
        again. Without this, every redraw rebuilds the R-top lines and
        leaks three canvas-level callbacks per line; after a few minutes of
        editing thousands of dead callbacks fire on every mouse-move and
        the whole view crawls.

        Args:
            fig (matplotlib.figure.Figure): The figure in which to capture events.
        """
        self._canvas = fig.canvas
        self._cids = [
            fig.canvas.mpl_connect('button_press_event', self.on_press),
            fig.canvas.mpl_connect('motion_notify_event', self.on_drag),
            fig.canvas.mpl_connect('button_release_event', self.on_release),
        ]

    def disconnect(self):
        """Remove this line's canvas callbacks. Safe to call more than once."""
        if self._canvas is not None:
            for cid in self._cids:
                self._canvas.mpl_disconnect(cid)
        self._cids = []
        self._canvas = None


class LineHandler:
    """
    Manages draggable lines on a plot, allowing add, remove, and drag operations.

    Attributes:
        draggable_lines (list): DraggableVLine objects currently on the plot.
        callback_remove (callable): Called when a line is removed.
        callback_drag (callable): Called when a line is dragged.
    """

    def __init__(self, ax, callback_remove=None, callback_drag=None):
        """
        Initializes LineHandler with an empty list of draggable lines and optional callbacks.

        Args:
            callback_remove (callable, optional): Callback for when a line is removed.
            callback_drag (callable, optional): Callback for when a line is dragged.
        """
        self.ax = ax
        self.draggable_lines = []
        self.callback_remove = callback_remove
        self.callback_drag = callback_drag
        DraggableVLine.mode = 'Drag'

    def add_line(self, x_position, color='red'):
        """
        Add a draggable vertical line at *x_position* on ``self.ax``.

        Args:
            x_position (float): The x-coordinate for the new line.
            color (str): Matplotlib colour string for the line (default ``'red'``).
        """
        self.draggable_lines.append(DraggableVLine(
            self.ax, x_position, self.callback_drag, self.callback_remove, color=color))

    def remove_line(self, line):
        """
        Removes a specified line from the set of draggable lines.

        Args:
            line (DraggableVLine): The line object to be removed.
        """
        if line in self.draggable_lines:
            line.disconnect()
            if line.line is not None and line.line.axes is not None:
                line.line.remove()  # Remove line from the plot
                line.line.axes.figure.canvas.draw_idle()
            self.draggable_lines.remove(line)

            if self.callback_remove:
                self.callback_remove(line)

    def clear(self):
        """
        Removes all draggable lines from the Axes and clears the `draggable_lines` list.

        Each line's canvas callbacks are disconnected so they do not pile up
        across redraws (see ``DraggableVLine.disconnect``).
        """
        for draggable_line in self.draggable_lines:
            draggable_line.disconnect()
            line = draggable_line.line
            if line is not None and line.axes:  # still attached to an Axes?
                line.remove()  # Remove the line from the plot
        self.draggable_lines.clear()

    def update_mode(self, mode):
        DraggableVLine.mode = mode
