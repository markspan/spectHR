import spectHR as cs
from spectHR.Tools.Logger import logger
from ipywidgets import Tab, Output, VBox
import ipyvuetify as v
import pandas as pd
import os

def HRApp(DataSet):
    """
    Creates an interactive Heart Rate Variability (HRV) analysis application using ipywidgets.
    
    The application consists of multiple tabs for preprocessing, Poincaré plots, descriptive statistics, 
    power spectral density (PSD) plots, and epoch visualization (Gantt charts). Each tab dynamically updates 
    based on user interaction, displaying relevant analyses and visualizations.

    Parameters:
    ----------
    DataSet : object
        A spectHRdataset object containing RTop data such as inter-beat intervals (IBIs), epochs, and more. 

    Returns:
    -------
    None
        Displays the interactive GUI application within the notebook.
    """
    
    # Create the initial preprocessing GUI using spectHR's prepPlot method
    GUI = cs.prepPlot(DataSet)  # Set dimensions for the preprocessing GUI
    
    # Initialize Output widgets for different tabs
    preProcessing = Output()
    
    with preProcessing:
        display(GUI)  # Display the GUI for preprocessing in the first tab
    
    # Create placeholders for the remaining tabs
    poincarePlot = Output()
    psdPlot = Output()
    descriptives = Output()
    Gantt = Output()

    tab_list = [v.Tab(children=['PreProcessing']),
        v.Tab(children=['Poincare']),
        v.Tab(children=['Descriptives']),
        v.Tab(children=['PSD']),
        v.Tab(children=['Epochs'])]

    content_list = [v.TabItem(children = [preProcessing]), 
        v.TabItem(children = [poincarePlot]),
        v.TabItem(children = [descriptives]),
        v.TabItem(children = [psdPlot]),
        v.TabItem(children = [Gantt])]
    
    # Create the Tab widget with all the Output widgets as children
    App = v.Tabs(v_model=0, children=tab_list + content_list)
    
    # Initialize empty series for PSD and descriptive statistics values
    DataSet.psd_Values = pd.Series()
    DataSet.descriptives_Values = pd.Series()
    
    # Define the callback function for handling tab switches
    def on_tab_change(change):
        """
        Callback function to handle tab changes in the HRV analysis application.
        
        Parameters:
        ----------
        change : dict
            A dictionary containing information about the change event. The key 'new' indicates
            the index of the newly selected tab.
        """
        tab_index = change['new']
        if tab_index == 1:  # Poincare tab selected
            with poincarePlot:
                poincarePlot.clear_output()  # Clear previous content
                display(cs.poincare(DataSet))  # Display Poincare plot for the dataset

            
        if tab_index == 2:  # Descriptives tab selected
            with descriptives:
                descriptives.clear_output()  # Clear previous content
                
                # Compute descriptive statistics grouped by epoch
                DataSet.descriptives_Values = cs.explode(DataSet)\
                    .groupby('epoch')['ibi']\
                    .agg([\
                        ('N', len),\
                        ('mean', 'mean'),\
                        ('std', 'std'),\
                        ('min', 'min'),\
                        ('max', 'max'),\
                        ('rmssd', cs.Tools.Params.rmssd),\
                        ('sdnn', cs.Tools.Params.sdnn),\
                        ('sdsd', cs.Tools.Params.sdsd),\
                        ('sd1', cs.Tools.Params.sd1),\
                        ('sd2', cs.Tools.Params.sd2),\
                        ('sd_ratio', cs.Tools.Params.sd_ratio),\
                        ('ellipse_area', cs.ellipse_area)\
                    ])
                
                # Merge PSD values if available
                if hasattr(DataSet, 'psd_Values'):
                    df = pd.DataFrame(list(DataSet.psd_Values.dropna()))
                    df['epoch'] = DataSet.psd_Values.dropna().index
                    pd.set_option('display.precision', 8)  # Set display precision for DataFrame
                    DataSet.descriptives_Values = pd.merge(DataSet.descriptives_Values, df, on='epoch', how='outer')
                
                 # Output widget to display the table
                table_output = Output()
                with table_output:
                    display(DataSet.descriptives_Values)  # Display the computed statistics
                # Create a button to save the table as a CSV file
                def save_to_csv(widget, event, data):
                    csv_filename = os.path.splitext(DataSet.filename)[0] + ".csv"
                    file_path = os.path.join(DataSet.datadir, csv_filename)
                    csv_data = DataSet.descriptives_Values.copy()
                    csv_data['id'] = os.path.splitext(DataSet.filename)[0]
                    # Reorder columns to make 'source_file' the leftmost column
                    columns = ['id'] + [col for col in csv_data.columns if col != 'id']
                    csv_data = csv_data[columns]
                    csv_data.to_csv(file_path, index=False)
                    logger.info(f"CSV file written to {file_path}")
                    # Create analysis helper if not there already:
                    if not os.path.isfile('ReadData.R'):
                    # R code as a static string
                        r_code = """
# Load necessary library
library(dplyr)

# Get a list of all CSV files in the current directory
csv_files <- list.files(pattern = "\\.csv$")
print(csv_files)
# Function to read a CSV file and validate its 'id' column
read_and_combine <- function(file) {
  # Read the CSV file
  df <- read.csv(file)
  names(df)
  # Ensure the 'id' column matches the filename (sanity check)
  stopifnot(all(df$id == tools::file_path_sans_ext(basename(file))))
  
  return(df)
}

# Read and combine all CSV files into a single dataframe
combined_data <- bind_rows(lapply(csv_files, read_and_combine))

# View the combined data
print(combined_data)
"""
                        
                        # Write the R code to a file
                        with open("ReadData.R", "w") as file:
                            file.write(r_code)
                        
                        logger.info("R code has been written to ReadData.R")
        
                save_button = v.Btn(
                    children=[
                        v.Icon(left=True, children=["fa-file-csv"]),  # Add a suitable Font Awesome icon
                        "Save as CSV"
                    ],
                    class_="ma-2",
                    color="primary",
                    outlined=True,
                )
                # Attach click event handler
                save_button.on_event('click', save_to_csv)

                # Combine the table and the button in a VBox
                layout = VBox(children=[table_output, save_button])
                
                # Display the VBox
                display(layout)
                #display(DataSet.descriptives_Values)  # Display the computed statistics
                
        if tab_index == 3:  # PSD tab selected
            with psdPlot:
                psdPlot.clear_output()  # Clear previous content
                
                # Compute PSD values using Welch's method
                Data = cs.explode(DataSet)
                DataSet.psd_Values = Data.groupby('epoch')[Data.columns.tolist()]\
                                         .apply(cs.welch_psd, nperseg=256, noverlap=128)
                
        if tab_index == 4:  # Gantt tab selected
            with Gantt:
                Gantt.clear_output()  # Clear previous content
                display(cs.gantt(DataSet, labels=True))  # Display Gantt chart visualization

        if change['old'] in [1,2]:
            # Save changes to the dataset after any tab interaction
            DataSet.save()
    
    # Attach the tab change observer to the Tab widget
    App.observe(on_tab_change, 'v_model')
    
    # Display the complete Tab application
    display(App)
