import spectHR as cs

def PreProcessFile(file_path):
    dataset = cs.SpectHRDataset(file_path, reset=True, flip='auto')
    dataset = cs.filterECGData(dataset, {"filterType": "highpass", "cutoff": 1})
    if not hasattr(dataset, 'RTops'):
        dataset = cs.calcPeaks(dataset)
    return dataset
   
