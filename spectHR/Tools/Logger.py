import ipywidgets as widgets
import logging
import sys  # Needed for flushing output

class OutputWidgetHandler(logging.Handler):
    """
    A custom logging handler that redirects log messages to an `ipywidgets.Output` widget 
    in Jupyter Notebook or JupyterLab environments.

    This handler ensures that logs are only shown in the widget and not duplicated in 
    the notebook cell outputs, making it ideal for cleanly managing log messages in Jupyter.

    Features:
    - Displays logs in an interactive widget.
    - Supports clearing the log messages.
    - Prevents logs from appearing below the notebook cells by removing the default StreamHandler.

    Methods:
    - `emit`: Handles formatting and displaying log records in the widget.
    - `show_logs`: Displays the widget in the notebook.
    - `clear_logs`: Clears all log messages from the widget.
    """

    def __init__(self, *args, **kwargs):
        """
        Initializes the OutputWidgetHandler.

        Creates an `ipywidgets.Output` widget to display logs with a custom layout.
        """
        super(OutputWidgetHandler, self).__init__(*args, **kwargs)
        layout = {
            'width': '100%',  # Full-width display for the widget
            'height': '160px',  # Set a fixed height for better visualization
            'border': '1px solid black'  # Adds a visible border around the widget
        }
        self.out = widgets.Output(layout=layout)

    def emit(self, record):
        """
        Processes and displays a log record in the widget.

        Args:
            record (logging.LogRecord): The log message record to be displayed.
        """
        # Format the log record into a readable string
        formatted_record = self.format(record)
        # Redirect the formatted log message to the output widget
        with self.out:
            print(formatted_record)
            sys.stdout.flush()  # Flush the output immediately

    def show_logs(self):
        """
        Displays the `Output` widget containing the log messages in the notebook.
        """
        display(self.out)
    
    def clear_logs(self):
        """
        Clears all log messages from the widget.
        """
        self.out.clear_output()

# Remove the default Jupyter StreamHandler to avoid duplicate log outputs
# By default, Jupyter adds a handler that outputs logs to notebook cells.
#for handler in logging.root.handlers[:]:
#    logging.root.removeHandler(handler)

# Create a custom logger
logger = logging.getLogger(__name__)  # Use the module's name as the logger name

# Attach the custom OutputWidgetHandler
handler = OutputWidgetHandler()

# Set a log message format (timestamp, level, and message)
handler.setFormatter(logging.Formatter('%(asctime)s  - spectHR [%(levelname)s] %(message)s'))

# Add the handler to the logger
logger.addHandler(handler)

# Set the logging level (INFO ensures only relevant messages are logged)
logger.setLevel(logging.INFO)
