import easywebdav
import os
from pathlib import Path
from spectHR.Tools.Logger import logger


def initWebdav():
    """
    Initialize a WebDAV connection.

    This function creates and returns an `easywebdav` connection object 
    configured to access the WebDAV server using credentials and 
    parameters specified in the environment variables.

    Environment Variables:
    - `USER`: Username for the WebDAV server.
    - `webdavpass`: Password for the WebDAV server.
    - `unishare`: Base path on the WebDAV server.

    Returns:
        easywebdav.Client: A WebDAV client instance.
    
    Raises:
        KeyError: If required environment variables are not set.
    """
    try:
        # Retrieve necessary environment variables
        username = os.environ['USER']
        password = os.environ['webdavpass']
        base_path = os.environ['unishare']
    except KeyError as e:
        raise KeyError(f"Missing required environment variable: {e}") from e

    # Establish a WebDAV connection
    webdav = easywebdav.connect(
        host='unishare.rug.nl',  # Only the hostname
        username=username,
        password=password,
        protocol='https',  # Explicit protocol declaration
        path=f"{base_path}/XDFData"  # Path to the specific directory on the server
    )
    return webdav


def copyWebdav(file_path):
    """
    Copy a file from the WebDAV server to local storage if it does not exist locally.

    The function checks if the specified file exists locally. If not, it connects to
    the WebDAV server, retrieves a list of available `.xdf` files, and downloads the 
    specified file if present on the server.

    Args:
        file_path (str): Full path to the file to be checked/copied.

    Returns:
        bool: `True` if the file exists locally or was successfully downloaded, `False` otherwise.

    Logs:
        - Info messages for file checking, downloading, and copying operations.
    """
    # Resolve directory and filename
    datadir = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    full_path = Path(datadir) / filename

    logger.info(f'Loading "{filename}"')

    # Check if file exists locally
    if not full_path.exists():
        logger.info(f'File "{filename}" not found in local storage.')

        try:
            # Initialize WebDAV connection
            webdav = initWebdav()

            # List available files on the server
            logger.info('Fetching file list from WebDAV server...')
            remote_files = webdav.ls()
            xdf_files = [
                os.path.basename(remote.name) for remote in remote_files if remote.name.endswith('.xdf')
            ]

            # Check if the file exists on the server
            if filename in xdf_files:
                logger.info(f'Copying "{filename}" to local storage ({datadir}).')
                
                # Ensure local directory exists
                Path(datadir).mkdir(parents=True, exist_ok=True)
                
                # Download the file
                webdav.download(filename, str(full_path))
            else:
                logger.warning(f'File "{filename}" not found on WebDAV server.')
                return False
        except Exception as e:
            logger.error(f'Error during WebDAV file retrieval: {e}')
            return False

    return True