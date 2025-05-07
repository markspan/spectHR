import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import welch
from scipy.interpolate import interp1d
from spectHR.Tools.Logger import logger

def welch_psd(Dataset, interpolate = True, fs=4, logscale = False,  nperseg=256, noverlap=128, interp_kind = 'linear', window='hamming'):
    """
    Analyzes the frequency domain of an Inter-Beat Interval (IBI) series using Welch's PSD method
    and visualizes the spectral power in VLF, LF, and HF bands.

    This function interpolates the IBI series onto a uniform time grid, calculates the Power Spectral
    Density (PSD) using Welch's method, and integrates the power in the physiologically relevant bands:
    VLF (0.003–0.04 Hz), LF (0.04–0.15 Hz), and HF (0.15–0.4 Hz). The results are plotted, highlighting
    these bands in different colors, and key measures are labeled on the plot.

    An alternative to this approuch would be the use of the  Lomb-Scargle periodogram:
    https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.lombscargle.html#scipy.signal.lombscargle

    Parameters:
    -----------
    Dataset: SpectHRDataset.RTops dataframe containing:
        ibi_times : array-like
            Timestamps of the IBIs (in seconds), typically derived from the R-peak times of an ECG.
        ibi_values : array-like
            Inter-Beat Interval values (in seconds), i.e., the time between successive heartbeats.
            
    interpolate : Boolean, optional
        Does the ibi range need to be resampled. This is advised for the welch method.
        Default: True
        
    fs : int, optional
        Resampling frequency in Hz (default: 4 Hz). This should be at least 2x the HF upper limit (0.4 Hz)
        to satisfy the Nyquist criterion and ensure accurate PSD estimation.
        
    logscale: plot the y-axis on a log scale, defaults to False

    Returns:
    --------
    spectral_measures : dict
        A dictionary containing the following spectral measures:
        - 'VLF Power': Power in the Very Low Frequency band (0.003–0.04 Hz).
        - 'LF Power': Power in the Low Frequency band (0.04–0.15 Hz).
        - 'HF Power': Power in the High Frequency band (0.15–0.4 Hz).
        - 'LF/HF Ratio': Ratio of LF power to HF power, an indicator of sympathovagal balance.

    References:
    -----------
    - Task Force of the European Society of Cardiology and the North American Society of Pacing
      and Electrophysiology. "Heart rate variability: Standards of measurement, physiological
      interpretation, and clinical use." *Circulation* 93.5 (1996): 1043-1065.
    - Mulder, L. J. M., and van Roon, A. "Spectral Analysis of Heart Rate Variability." In *Tools and 
      Techniques for Stress Assessment and Management* (1998).

    Notes:
    ------
    - Welch's method is used for spectral estimation due to its robustness against noise and short epochs.
    - Interpolation ensures uniform sampling, which is a requirement for Fourier-based methods like Welch.
    - The LF/HF ratio is commonly used to assess autonomic nervous system regulation.
    """
    
    ibi_times = Dataset['time']
    ibi_values= Dataset['ibi']
    
    # Hack to get the epoch name if called through groupby.apply
    try:
        titlestring = Dataset['epoch'].iloc[0].title()
    except AttributeError:
        titlestring = "Whole Interval"
        
    # 1. Interpolate IBI values onto a uniform time grid
    # Use .iloc for Pandas Series positional indexing
    time_uniform = np.arange(ibi_times.iloc[0], ibi_times.iloc[-1], 1/fs)  # Regular time grid at fs Hz
    if (interpolate):
        # Linear interpolation of IBI values to match the uniform grid
        interp_func = interp1d(ibi_times, ibi_values, kind=interp_kind, fill_value='extrapolate')
        ibi_resampled = interp_func(time_uniform)
    else:
        ibi_resampled = ibi_values
        
    # 2. Compute the Power Spectral Density (PSD) using Welch's method
    # Welch's method parameters:
    # - nperseg: Segment size (256 samples at fs=4 Hz -> 64-second segments)
    # - noverlap: 50% overlap between segments (128 samples)
    # - window: Hamming window to minimize spectral leakage
    # if a ValueError occurs (usually the epoch is too small for a calculation using the default 
    # parameters) the function returns empty. This will lead to the wanted 'NaN'values in the descriptives
    ibi_resampled = ibi_resampled-np.mean(ibi_resampled)
    
    try:
        freqs, psd = welch(ibi_resampled, fs=fs, scaling='density', nfft=2**12, nperseg=nperseg, noverlap=noverlap, window=window)
    except ValueError:
        return
        
    # 3. Define frequency bands of interest for HRV analysis
    vlf_band = (0.003, 0.04)  # Very Low Frequency (VLF)
    lf_band = (0.04, 0.15)    # Low Frequency (LF)
    hf_band = (0.15, 0.4)     # High Frequency (HF)

    # Helper function to compute power in a specified frequency range using numerical integration
    def band_power(frequencies, power_spectrum, band):
        """
        Computes the power within a specific frequency band using the trapezoidal rule.

        Parameters:
        - frequencies: array of frequency values.
        - power_spectrum: array of PSD values corresponding to the frequencies.
        - band: tuple (f_low, f_high) defining the frequency range.

        Returns:
        - Power within the specified band.
        """
        idx = np.logical_and(frequencies >= band[0], frequencies <= band[1])
        return np.trapz(power_spectrum[idx], frequencies[idx])  # Integrate PSD over the band

    # 4. Calculate power in each frequency band
    vlf_power = band_power(freqs, psd, vlf_band)
    lf_power = band_power(freqs, psd, lf_band)
    hf_power = band_power(freqs, psd, hf_band)
    lf_hf_ratio = lf_power / hf_power  # LF/HF Ratio (sympathovagal balance)

    # 5. Store spectral measures in a dictionary
    spectral_measures = {
        'VLF Power': vlf_power,
        'LF Power': lf_power,
        'HF Power': hf_power,
        'LF/HF Ratio': lf_hf_ratio
    }
    
    """
    6: The blocks below are there only to get the areas filled upto the actual band boundaries
    """
    # Extract PSD values for each band
    vlf_psd = psd[(freqs >= vlf_band[0]) & (freqs <= vlf_band[1])]
    lf_psd = psd[(freqs >= lf_band[0]) & (freqs <= lf_band[1])]
    hf_psd = psd[(freqs >= hf_band[0]) & (freqs <= hf_band[1])]
    
    # Filter freqs to get the values within the band
    vlf_freqs = freqs[(freqs >= vlf_band[0]) & (freqs <= vlf_band[1])]
    lf_freqs = freqs[(freqs >= lf_band[0]) & (freqs <= lf_band[1])]
    hf_freqs = freqs[(freqs >= hf_band[0]) & (freqs <= hf_band[1])]
    
    # Interpolate PSD values to ensure exact band boundaries
    vlf_psd_ex = np.insert(vlf_psd, 0, np.interp(vlf_band[0], freqs, psd))  # Add exact vlf_band[0]
    vlf_psd_ex = np.append(vlf_psd_ex, np.interp(lf_band[0], freqs, psd))  # Add exact lf_band[0]
    
    lf_psd_ex = np.insert(lf_psd, 0, np.interp(vlf_band[1], freqs, psd))  # Add exact vlf_band[1]
    lf_psd_ex = np.append(lf_psd_ex, np.interp(hf_band[0], freqs, psd))  # Add exact hf_band[0]
    
    hf_psd_ex = np.insert(hf_psd, 0, np.interp(lf_band[1], freqs, psd))  # Add exact lf_band[1]
    hf_psd_ex = np.append(hf_psd_ex, np.interp(hf_band[1], freqs, psd))  # Add exact hf_band[1]
    
    # Interpolate frequencies to ensure exact band boundaries
    vlf_freqs_ex = np.insert(vlf_freqs, 0, vlf_band[0])  # Add exact vlf_band[0]
    vlf_freqs_ex = np.append(vlf_freqs_ex, lf_band[0])  # Add exact lf_band[0]
    
    lf_freqs_ex = np.insert(lf_freqs, 0, vlf_band[1])  # Add exact vlf_band[1]
    lf_freqs_ex = np.append(lf_freqs_ex, hf_band[0])  # Add exact hf_band[0]
    
    hf_freqs_ex = np.insert(hf_freqs, 0, lf_band[1])  # Add exact lf_band[1]
    hf_freqs_ex = np.append(hf_freqs_ex, hf_band[1])  # Add exact hf_band[1]
    
    # 7. Create a graphical representation of the PSD with highlighted bands
    plt.figure(figsize=(7.5, 5))
    plt.plot(freqs, psd, '-k', alpha = .5, linewidth=.5, label=f'PSD Spectrum {titlestring}')
        
    # VLF fill area (extend to start of LF)
    plt.fill_between(vlf_freqs_ex, 0, vlf_psd_ex,
                     color='blue', alpha=0.3, label=f'VLF ({vlf_band[0]}-{vlf_band[1]} Hz): {vlf_power:.6f}')
    
    # LF fill area (extend to start of HF)
    plt.fill_between(lf_freqs_ex, 0, lf_psd_ex,
                     color='green', alpha=0.3, label=f'LF ({lf_band[0]}-{lf_band[1]} Hz): {lf_power:.6f}')
    
    # HF fill area (starts at LF's interpolated end)
    plt.fill_between(hf_freqs_ex, 0, hf_psd_ex, 
                     color='red', alpha=0.3, label=f'HF ({hf_band[0]}-{hf_band[1]} Hz): {hf_power:.6f}')
    
    # LF/HF ratio as a legend entry
    plt.plot([], [], ' ', label=f'LF/HF Ratio: {lf_hf_ratio:.3f}')
    

    # Add plot labels and title
    plt.title('Power Spectral Density of IBI Series', fontsize=14)
    plt.xlabel('Frequency [$Hz$]', fontsize=12)
    plt.ylabel('PSD [$s^2/Hz$]', fontsize=12)
    plt.legend(loc='upper right')
    
    # Ensure the axes starts at 0
    plt.xlim(left = 0,  right = .4)
    plt.ylim(bottom = 0)
    
    if logscale:
        # Set the y-axis to logarithmic scale
        plt.yscale('log')
        
        # Automatically adjust the y-limits based on the data
        plt.ylim(bottom=psd.min() * 0.9, top=psd.max() * 1.1)  # Optionally add some margin

    # Remove the top and right axes
    ax = plt.gca()  # Get current axes
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # Keep only the left and bottom axes
    ax.spines['left'].set_visible(True)
    ax.spines['bottom'].set_visible(True)
    
    # Adjust ticks to match the remaining axes
    ax.yaxis.set_ticks_position('left')
    ax.xaxis.set_ticks_position('bottom')

    # Display the plot
    plt.tight_layout()
    plt.show()

    return spectral_measures