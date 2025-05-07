import shutil
import os
import glob

def install_notebook():
    """Copy all .ipynb and .xdf files from notebooks/ to the user's home directory (~)."""
    home_dir = os.path.expanduser("~")  # Resolves to the user's home directory
    notebooks_dir = os.path.join(os.path.dirname(__file__), "notebooks")  # Path to packaged notebooks
    
    # Ensure home directory exists
    os.makedirs(home_dir, exist_ok=True)

    # Find all .ipynb and .xdf files in the notebooks directory
    for file_path in glob.glob(os.path.join(notebooks_dir, "*.*")):
        filename = os.path.basename(file_path)  # Extract filename
        dest_path = os.path.join(home_dir, filename)  # Destination in home dir

        # Copy file if it doesn't already exist
        if not os.path.exists(dest_path):
            shutil.copy(file_path, dest_path)
            print(f"Installed: {dest_path}")
        else:
            print(f"Skipped (already exists): {dest_path}")

# Execute the function on import
install_notebook()
