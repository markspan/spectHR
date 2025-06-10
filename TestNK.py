import matplotlib.pyplot as plt
import neurokit2 as nk

file_path = '.\\data\\1404251data.xdf'
data, header = nk.read_xdf(file_path)

signals, info = nk.eda_process(data["Aux13"], sampling_rate=4000)
info = {'sampling_rate': 4000 }
nk.eda_plot(signals, info=info)
plt.show()
signals, info = nk.eda_process(data["Bip12"], sampling_rate=4000)
nk.eda_plot(signals, info=info)
plt.show()
a=3