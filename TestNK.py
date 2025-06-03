# Load the NeuroKit package
import pickle

import matplotlib.pyplot as plt
import neurokit2 as nk

file_path = 'C:/Users/P154492/Documents/spectHR/cache/POLARBLE XDF file example .pkl'
# Load the data from the pickle file
with open(file_path, 'rb') as f:
    data = pickle.load(f)

hrv_time = nk.hrv_time(data.RTops['time'], show=True)
plt.show()
ecg_signals, info = nk.ecg_process(data.ecg.level, sampling_rate=130)
nk.ecg_plot(ecg_signals[1000:30000], info)
plt.show()

rsp_signals, info = nk.rsp_process(data.br.level, sampling_rate=200)
nk.rsp_plot(rsp_signals, info)
plt.show()
print(nk.ecg_intervalrelated(ecg_signals))
print(nk.rsp_intervalrelated(rsp_signals))

