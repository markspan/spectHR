import matplotlib.pyplot as plt
import matplotlib.patches as patches
from spectHR.Tools.Logger import logger

class DraggableVLine:
    """
    A draggable vertical line on a plot.
    
    Attributes:
        line (matplotlib.lines.Line2D): The line object representing the vertical line.
    """
    active_line = None  # Shared among all instances
    mode = 'Drag'
    line = None
    
    def __init__(self, ax, x_position, callback_drag=None, callback_remove=None, color = 'red'):
        """
        Initializes DraggableVLine at a specified x position.
        
        Args:
            ax (matplotlib.axes.Axes): The axes to place the vertical line on.
            x_position (float): The initial x-coordinate for the line.
            callback_drag (callable, optional): Callback for when the line is dragged.
        """
        self.ax = ax
        self.line = self.ax.axvline(x=x_position, color=color, lw=.8, linestyle='-', picker=True, pickradius = 10,  alpha = .5)
        self.callback_drag = callback_drag
        self.callback_remove = callback_remove
        self.press = None
        self.connect(ax.figure)

    def on_press(self, event):
        """
        Captures the initial click location if near the line.
        
        Args:
            event (matplotlib.backend_bases.Event): The mouse press event.
        """
        if (DraggableVLine.mode == 'Drag') or (DraggableVLine.mode == 'Remove'):
            if (DraggableVLine.active_line is None) and (self.line.contains(event)[0]):
                DraggableVLine.active_line = self.line
                self.press = self.line.get_xdata()[0]      
                logger.info(f'setting active line to line at {self.press}')


    def on_drag(self, event):
        """
        Drags the line to follow the mouse's x position.
        
        Args:
            event (matplotlib.backend_bases.Event): The mouse drag event.
        """
        if DraggableVLine.mode == 'Drag':  
            if DraggableVLine.active_line is self.line:
                self.line.set_xdata([event.xdata, event.xdata])
                self.ax.figure.canvas.draw_idle()

    def on_release(self, event):
        """
        Releases the drag operation. Call the drag_callback with the new_x value
        
        Args:
            event (matplotlib.backend_bases.Event): The mouse release event.
        """
        if (DraggableVLine.mode != 'Drag' \
            and DraggableVLine.mode != 'Remove') \
                or self.press is None \
                or event.inaxes is not self.ax:
            return

        # Callback with updated x-position if set
        if DraggableVLine.mode == 'Drag' \
              or self.press is None \
                and self.callback_drag:
            self.callback_drag(self.press, event.xdata)

            
        if DraggableVLine.mode == 'Remove' \
             or self.press is None \
                and self.callback_remove:
            self.callback_remove(self.press, event.xdata)
            logger.info(f'release line at {self.press}')
            DraggableVLine.active_line = None
            self.line.remove()
        
        self.press = None
        DraggableVLine.active_line = None

            
    def connect(self, fig):
        """
        Connects events for dragging the line.
        
        Args:
            fig (matplotlib.figure.Figure): The figure in which to capture events.
        """
        fig.canvas.mpl_connect('button_press_event', self.on_press)
        fig.canvas.mpl_connect('motion_notify_event', self.on_drag)
        fig.canvas.mpl_connect('button_release_event', self.on_release)

class LineHandler:
    """
    Manages draggable lines on a plot, allowing add, remove, and drag operations.
    
    Attributes:
        draggable_lines (set): A set of DraggableVLine objects on the plot.
        callback_add (callable): Function to call when a line is added.
        callback_remove (callable): Function to call when a line is removed.
    """
    
    def __init__(self, ax, callback_remove=None, callback_drag=None):
        """
        Initializes LineHandler with an empty set of draggable lines and optional callbacks.
        
        Args:
            callback_add (callable, optional): Callback for when a line is added.
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
        Adds a draggable line at the specified x position without plotting it.
        
        Args:
            ax (matplotlib.axes.Axes): The axes on which to add the line.
            x_position (float): The x-coordinate for the new line.
        """
        self.draggable_lines.append(DraggableVLine(self.ax, x_position, self.callback_drag, self.callback_remove, color=color))

        
    def remove_line(self, line):
        """
        Removes a specified line from the set of draggable lines.
        
        Args:
            line (DraggableVLine): The line object to be removed.
        """
        if line in self.draggable_lines:
            line.line.remove()  # Remove line from the plot
            self.draggable_lines.discard(line)
            plt.draw()
            
            if self.callback_remove:
                self.callback_remove(line)
    
    def clear(self):
        """
        Removes all draggable lines from the Axes and clears the `draggable_lines` list.
        """
        for draggable_line in self.draggable_lines:
            line = draggable_line.line
            if line.axes:  # Check if the line is still associated with an Axes
                line.remove()  # Remove the line from the plot
        self.draggable_lines.clear()  # Clear the internal list of draggable lines
        plt.draw()  # Redraw the canvas
   
    def update_mode(self, mode):
        logger.info(f'Changed mode to {mode}')
        DraggableVLine.mode = mode

