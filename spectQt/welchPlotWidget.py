import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from scipy.interpolate import interp1d
from scipy.signal import welch


class WelchPSDPlotWidget(QWidget):
    """
    A QWidget that plots the Welch PSD of an IBI time series.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welch PSD")

        self.canvas = FigureCanvas(Figure(figsize=(4, 600)))
        self.ax = self.canvas.figure.add_subplot(111)

        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        # Set size policy to expand vertically
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Set a minimum size for the widget
        self.setMinimumSize(400, 640)  # Adjust the height as needed

    def plot_psd(self, dataset, epoch, fs=4, logscale=False, nperseg=256, noverlap=128,
                interp_kind='linear', window='hamming', interpolate=True):
        """
        Plots the Welch PSD from the dataset for a specific epoch.
        """
        # Check visibility
        if hasattr(dataset, "active_epochs"):
            if dataset.active_epochs.get(epoch, True) is False:
                return  # Don't plot invisible epochs
        # Filter dataset for the specific epoch
        epoch_data = dataset[dataset['epoch'] == epoch]

        ibi_times = epoch_data['time']
        ibi_values = epoch_data['ibi']

        try:
            title = epoch.title()
        except Exception:
            title = "Whole Interval"

        # Interpolation
        time_uniform = np.arange(ibi_times.iloc[0], ibi_times.iloc[-1], 1 / fs)

        if interpolate:
            interp_func = interp1d(ibi_times, ibi_values, kind=interp_kind, fill_value='extrapolate')
            ibi_resampled = interp_func(time_uniform)
        else:
            ibi_resampled = ibi_values

        # Welch PSD
        #freqs, power = welch(ibi_resampled, fs=fs, window=window, nperseg=nperseg, noverlap=noverlap)
        try:
            freqs, power = welch(ibi_resampled, fs=fs, scaling='density', nfft=2**12, nperseg=nperseg, noverlap=noverlap, window=window)
        except ValueError:
            return -1
        # Power bands
        vlf_band = (0.003, 0.04)  # Very Low Frequency (VLF)
        lf_band = (0.04, 0.15)    # Low Frequency (LF)
        hf_band = (0.15, 0.4)     # High Frequency (HF)

        # Power bands
        #vlf_band = (0.02, 0.06)  # Very Low Frequency (VLF)
        #lf_band = (0.07, 0.14)    # Low Frequency (LF)
        #hf_band = (0.15, 0.4)     # High Frequency (HF)

        # Helper function to compute power in a specified frequency range using numerical integration
        def band_power(frequencies, power_spectrum, band):
            idx = np.logical_and(frequencies >= band[0], frequencies <= band[1])
            return np.trapezoid(power_spectrum[idx], frequencies[idx])

        # Calculate power in each frequency band
        vlf_power = band_power(freqs, power, vlf_band)
        lf_power = band_power(freqs, power, lf_band)
        hf_power = band_power(freqs, power, hf_band)
        lf_hf_ratio = lf_power / hf_power if hf_power != 0 else np.nan
        # 5. Store spectral measures in a dictionary
        spectral_measures = {
            'epoch': epoch,
            'VLF Power': vlf_power,
            'LF Power': lf_power,
            'HF Power': hf_power,
            'LF/HF Ratio': lf_hf_ratio
        }
        
        # Extract PSD values for each band
        vlf_psd = power[(freqs >= vlf_band[0]) & (freqs <= vlf_band[1])]
        lf_psd = power[(freqs >= lf_band[0]) & (freqs <= lf_band[1])]
        hf_psd = power[(freqs >= hf_band[0]) & (freqs <= hf_band[1])]

        # Filter freqs to get the values within the band
        vlf_freqs = freqs[(freqs >= vlf_band[0]) & (freqs <= vlf_band[1])]
        lf_freqs = freqs[(freqs >= lf_band[0]) & (freqs <= lf_band[1])]
        hf_freqs = freqs[(freqs >= hf_band[0]) & (freqs <= hf_band[1])]

        # Interpolate PSD values to ensure exact band boundaries
        vlf_psd_ex = np.insert(vlf_psd, 0, np.interp(vlf_band[0], freqs, power))
        vlf_psd_ex = np.append(vlf_psd_ex, np.interp(lf_band[0], freqs, power))

        lf_psd_ex = np.insert(lf_psd, 0, np.interp(vlf_band[1], freqs, power))
        lf_psd_ex = np.append(lf_psd_ex, np.interp(hf_band[0], freqs, power))

        hf_psd_ex = np.insert(hf_psd, 0, np.interp(lf_band[1], freqs, power))
        hf_psd_ex = np.append(hf_psd_ex, np.interp(hf_band[1], freqs, power))

        # Interpolate frequencies to ensure exact band boundaries
        vlf_freqs_ex = np.insert(vlf_freqs, 0, vlf_band[0])
        vlf_freqs_ex = np.append(vlf_freqs_ex, lf_band[0])

        lf_freqs_ex = np.insert(lf_freqs, 0, vlf_band[1])
        lf_freqs_ex = np.append(lf_freqs_ex, hf_band[0])

        hf_freqs_ex = np.insert(hf_freqs, 0, lf_band[1])
        hf_freqs_ex = np.append(hf_freqs_ex, hf_band[1])

        # Plot
        self.ax.clear()
        self.ax.plot(freqs, power, '-k', alpha=0.5, linewidth=0.5, label=f'PSD Spectrum {title}')

        # VLF fill area
        self.ax.fill_between(vlf_freqs_ex, 0, vlf_psd_ex, color='blue', alpha=0.3, label=f'VLF ({vlf_band[0]}-{vlf_band[1]} Hz): {vlf_power:.6f}')

        # LF fill area
        self.ax.fill_between(lf_freqs_ex, 0, lf_psd_ex, color='green', alpha=0.3, label=f'LF ({lf_band[0]}-{lf_band[1]} Hz): {lf_power:.6f}')

        # HF fill area
        self.ax.fill_between(hf_freqs_ex, 0, hf_psd_ex, color='red', alpha=0.3, label=f'HF ({hf_band[0]}-{hf_band[1]} Hz): {hf_power:.6f}')

        # LF/HF ratio as a legend entry
        self.ax.plot([], [], ' ', label=f'LF/HF Ratio: {lf_hf_ratio:.3f}')

        # Add plot labels and title
        self.ax.set_title('Power Spectral Density of IBI Series', fontsize=14)
        self.ax.set_xlabel('Frequency [$Hz$]', fontsize=12)
        self.ax.set_ylabel('PSD [$s^2/Hz$]', fontsize=12)
        self.ax.legend(loc='upper right')

        # Ensure the axes start at 0
        self.ax.set_xlim(left=0, right=0.4)
        self.ax.set_ylim(bottom=0)

        if logscale:
            # Set the y-axis to logarithmic scale
            self.ax.set_yscale('log')
            # Automatically adjust the y-limits based on the data
            self.ax.set_ylim(bottom=power.min() * 0.9, top=power.max() * 1.1)

        # Remove the top and right axes
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)

        # Keep only the left and bottom axes
        self.ax.spines['left'].set_visible(True)
        self.ax.spines['bottom'].set_visible(True)

        # Adjust ticks to match the remaining axes
        self.ax.yaxis.set_ticks_position('left')
        self.ax.xaxis.set_ticks_position('bottom')

        # Display the plot
        self.canvas.draw()
        return spectral_measures