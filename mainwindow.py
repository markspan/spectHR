import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from ui_form2 import Ui_MainWindow
import spectQt as spQt

class MainWindow(QMainWindow):
    """
    Main application window for the spectQt ECG pre-processing interface.
    Displays a workspace tree and a matplotlib plot area for visualizing
    preprocessed data.
    """
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowTitle("spectHR - ECG Preprocessing")
        self.resize(1900, 800)
        self.ui.splitter.setSizes([200, 1700])
        # Initialize the workspace and tree
        self.workspace = spQt.LoadWorkspace()
        spQt.PopulateTree(self.ui.treeWidget, self.workspace)

        # Add PrepPlotWidget to its placeholder
        self.prep_plot_widget = spQt.PrepPlotWidget()
        layout1 = QVBoxLayout()
        layout1.addWidget(self.prep_plot_widget)
        self.ui.mplPreProcessing.setLayout(layout1)

        # Add PoincarePlotWidget to its separate placeholder
        self.poincare_plot_widget = spQt.PoincarePlotWidget()
        layout2 = QVBoxLayout()
        layout2.addWidget(self.poincare_plot_widget)
        self.ui.mplPoincare.setLayout(layout2)

        # Connect tree widget selection change signal to the file processing function
        self.ui.treeWidget.itemSelectionChanged.connect(self.on_file_selection)
    
    def on_file_selection(self):
        """
        Triggered when an item in the file tree is selected.
        Retrieves the corresponding file and visualizes its preprocessed data.
        """
        selected_items = self.ui.treeWidget.selectedItems()
        if not selected_items:
            return

        file_path = selected_items[0].text(0)  # File path from first column
        if file_path == 'XDF Files':
            return
        print(f"Selected file: {file_path}")

        # Load and process the selected file
        data = spQt.PreProcessFile(file_path)

        # Update the plot with preprocessed data
        self.show_preprocessing_plot(data)
        self.show_poincare_plot(data)

    def show_preprocessing_plot(self, data):
        """
        Display the preprocessed plot in the mplPreProcessing widget area.

        Parameters:
        - data: The processed signal data to visualize.
        """
        # Update the plot in the PrepPlotWidget
        self.prep_plot_widget.prepPlot(data)

    def show_poincare_plot(self, data):
        """
        Display the poincare plot in the mplPoincare widget area.

        Parameters:
        - data: The processed signal data to visualize.
        """
        # Update the plot in the poincarePlotWidget
        self.poincare_plot_widget.plot_poincare(data)
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
