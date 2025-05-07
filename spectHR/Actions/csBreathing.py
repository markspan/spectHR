from scipy.signal import butter, filtfilt, find_peaks
import pandas as pd
import numpy as np

def calculate_breathing_signal(acc, rate):
    """
    Calculate the breathing signal from raw accelerometer data.
    
    This method processes the 3-axis accelerometer values to extract a breathing-related
    signal by:
    1. Applying a low-pass filter (gravity filter) to isolate the gravitational component.
    2. Subtracting the gravitational component to obtain dynamic acceleration.
    3. Applying a second low-pass filter (noise filter) to the norm of the dynamic acceleration.
    
    Notes:
    ------
    - Assumes `acc` is an Nx3 array (samples x [X, Y, Z] axes).
    - Sampling frequency is assumed to be 200 Hz (e.g., Polar H10 accelerometer).
    """
    
    # Constants
    SAMPLEFREQUENCY = rate  # Hz, fixed for Polar H10
    NYQUIST = 0.5 * SAMPLEFREQUENCY
    GRAVITY_CUTOFF = 0.04  # Hz
    NOISE_CUTOFF = 0.5  # Hz
    ORDER = 2
    
    # --- Step 1: Gravity Filter (very low-pass) ---
    # Design low-pass Butterworth filter for gravity component
    b_gravity, a_gravity = butter(ORDER, GRAVITY_CUTOFF / NYQUIST, btype='low')
    
    # Apply gravity filter independently to each accelerometer axis
    # Remove the gravity component to get the dynamic movement
    for axis in range(3):
        acc[:, axis] -= filtfilt(b_gravity, a_gravity, acc[:, axis])
  
    # Compute the norm of the dynamic acceleration
    acc = np.linalg.norm(acc, axis=1)
    
    # --- Step 3: Noise Filter (low-pass) ---
    # Design second low-pass Butterworth filter for dynamic acceleration norm
    b_noise, a_noise = butter(ORDER, NOISE_CUTOFF / NYQUIST, btype='low')
    
    # Apply the noise filter to obtain the breathing signal
    return filtfilt(b_noise, a_noise, acc)
