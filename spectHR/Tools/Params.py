import numpy as np

def rmssd(ibi):
    ibi = np.asarray(ibi)
    nnd = np.diff(ibi)
    rmssd = np.sum([x**2 for x in nnd])
    rmssd = np.sqrt(1. / nnd.size * rmssd)
    return rmssd

def sdnn(ibi):
    ibi = np.asarray(ibi)
    return np.std(ibi)

def sd1(ibi):
    """
    Calculate the SD1 index, which is a measure of short-term variability 
    in the heart rate.

    SD1 is derived from the difference between consecutive inter-beat intervals (IBIs).
    
    Args:
        ibi (list or array): A list or array of inter-beat intervals (IBIs) in seconds.
    
    Returns:
        float: The SD1 value representing short-term variability in the IBIs.
    """
    ibi = np.asarray(ibi)
    return np.std(np.subtract(1000 * ibi[:-1],  1000 * ibi[1:]) / np.sqrt(2))

def sd2(ibi):
    """
    Calculate the SD2 index, which is a measure of long-term variability 
    in the heart rate.

    SD2 is derived from the sum of consecutive inter-beat intervals (IBIs).
    
    Args:
        ibi (list or array): A list or array of inter-beat intervals (IBIs) in seconds.
    
    Returns:
        float: The SD2 value representing long-term variability in the IBIs.
    """
    ibi = np.asarray(ibi)
    return np.std(np.add(1000 * ibi[:-1],  1000 * ibi[1:]) / np.sqrt(2))

def sd_ratio(ibi):
    """
    Calculate the SD1/SD2 ratio, which is used to assess the balance between short-term
    and long-term heart rate variability.

    The SD ratio is a simple ratio of SD1 (short-term variability) to SD2 (long-term variability).
    
    Args:
        ibi (list or array): A list or array of inter-beat intervals (IBIs) in seconds.
    
    Returns:
        float: The ratio of SD1 to SD2, representing the relative balance of short- to long-term variability.
    """
    return sd1(ibi) / sd2(ibi)

def ellipse_area(ibi):
    """
    Calculate the area of the Poincaré ellipse, which represents the heart rate variability 
    using the SD1 and SD2 indices.

    The area is calculated using the formula: π * SD1 * SD2.
    
    Args:
        ibi (list or array): A list or array of inter-beat intervals (IBIs) in seconds.
    
    Returns:
        float: The area of the Poincaré ellipse, representing the overall heart rate variability.
    """
    return np.pi * sd1(ibi) * sd2(ibi)

def sdsd(ibi):
    """
    Calculate the SD of the successive differences (SDSD), a time-domain measure of heart 
    rate variability that quantifies short-term fluctuations.

    This is calculated as the standard deviation of the differences between consecutive IBIs.
    
    Args:
        ibi (list or array): A list or array of inter-beat intervals (IBIs) in seconds.
    
    Returns:
        float: The SDSD value, representing the variability in the successive differences of IBIs.
    """
    try:
        ibi = np.asarray(ibi)
        ret = np.std(np.diff(ibi))
    except Exception as e:
        # If calculation fails, return NaN
        ret = np.nan
    return ret
