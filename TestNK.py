import pickle

import matplotlib.pyplot as plt
import neurokit2 as nk

file_path = 'DATA2.pkl'
# Load your data from the .pkl file
with open(file_path, 'rb') as f:
    data = pickle.load(f)

# Plot the ECG data with R-peaks
nk.ecg_plot(data['signals'], info={'sampling_rate': 2000})
plt.show()
a = nk.ecg_intervalrelated(data['signals'], sampling_rate=2000)
print(a)
a=3
