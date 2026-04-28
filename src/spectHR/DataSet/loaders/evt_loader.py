from __future__ import annotations
import numpy as np
from typing import Any
from collections import Counter

from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger

from spectHR.DataSet.loaders.EventCodeWindow import EventCodeWindow
from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from pathlib import Path
import struct

@register_loader(".evt")
def load_evt(physiodata, filename: str, **kwargs: Any) -> None:
    """
    Loader for (CARSPAN) evt objects. if nff files are availeable they will also be loaded.
    """
    EVTPath = Path(filename)
    logger.info(f"Loading EVT: {EVTPath}")
    loadEVT(physiodata, EVTPath)
    physiodata.has_ecg = False
    
    NFFPath = EVTPath.with_suffix('.nff')
    if NFFPath.exists():
        loadNFF(physiodata,NFFPath)
        logger.info(f"Loading dataset from CARSPAN nff File: {NFFPath.name}")
        # Lock R-peak times: the .evt timestamps are authoritative when an
        # accompanying .nff ECG signal exists. Otherwise preprocess_ecg()
        # would re-detect peaks from the ECG and overwrite the .evt times.
        for cs in physiodata.hrv_map.values():
            cs.rtops_locked = True
    else:
        logger.info(f"No corresponding NFF file found at: {NFFPath}")


def loadEVT(physiodata, filename: Path) -> None:
    """
    Load HRVdata and epochs from a CARSPAN .evt file into PhysioData.
    Uses the EventCodeWindow GUI when multiple non-RTop codes exist.
    """

    logger.info("Loading CARSPAN EVT RTop Data")

    # --------------------------------------------------
    # Read file
    # --------------------------------------------------
    with filename.open("r") as f:
        lines = f.readlines()

    if not any("[Data]" in line for line in lines):
        lines.insert(0, "[Data]\n")

    # --------------------------------------------------
    # Parse [Data] section
    # --------------------------------------------------
    in_data = False
    event_codes = []
    times = []

    for line in lines:
        if line.strip() == "[Data]":
            in_data = True
            continue

        if not in_data:
            continue

        parts = line.strip().split()
        if len(parts) < 2:
            continue

        try:
            code = int(parts[0])
            time = float(parts[1])
        except ValueError:
            continue

        event_codes.append(code)
        times.append(time)

    if not times:
        raise ValueError("EVT file contains no valid data.")

    event_codes = np.asarray(event_codes)
    times = np.asarray(times)

    # --------------------------------------------------
    # Determine RTop code (most frequent)
    # --------------------------------------------------
    rtop_code = Counter(event_codes).most_common(1)[0][0]
    logger.info(f"RTop event code assumed to be {rtop_code}")

    rtop_mask = event_codes == rtop_code
    rtop_times = times[rtop_mask]

    if rtop_times.size == 0:
        raise ValueError("No RTops found in EVT file.")

    # --------------------------------------------------
    # Create CardioSeries
    # --------------------------------------------------
    # Ensure band model exists (evt-only files may not have NFF)
    if not hasattr(physiodata, "band_map") or not physiodata.band_map:
        physiodata.band_map = {"ecg": {"ecg": "ecg"}}
    if getattr(physiodata, "active_band", None) is None:
        physiodata.active_band = "ecg"

    band = physiodata.active_band

    # Ensure HRV store exists
    if not hasattr(physiodata, "hrv_map") or physiodata.hrv_map is None:
        physiodata.hrv_map = {}

    cs = CardioSeries(rtop_times)
    cs._pd = physiodata
    physiodata.hrv_map[band] = cs

    # --------------------------------------------------
    # Determine epoch boundaries
    # --------------------------------------------------
    other_codes = event_codes[~rtop_mask]
    other_times = times[~rtop_mask]

    # Default: single epoch
    start_times = [float(times[0])]
    end_times = [float(times[-1])]

    unique_other_codes = np.unique(other_codes)

    if unique_other_codes.size > 2:
        # ----------------------------------------------
        # GUI-based code selection
        # ----------------------------------------------
        window = EventCodeWindow(
            other_codes,
            ignore=rtop_code,
        )
        window.exec()

        start_codes = window.start_codes
        stop_codes = window.stop_codes

        if start_codes and stop_codes:
            start_times = other_times[np.isin(other_codes, start_codes)]
            end_times = other_times[np.isin(other_codes, stop_codes)]

            if start_times.size != end_times.size:
                raise ValueError(
                    "Selected start/stop codes produce mismatched epochs."
                )
        else:
            logger.info("No codes selected — using full recording as single epoch")

    elif unique_other_codes.size == 2:
        # Deterministic pairing
        start_times = other_times[::2]
        end_times = other_times[1::2]

        if start_times.size != end_times.size:
            raise ValueError(
                "Mismatched start/stop events in EVT file."
            )

    # --------------------------------------------------
    # CARSPAN epoch-start convention
    # --------------------------------------------------
    # The CARSPAN system counts the last heartbeat *before* the Beginperiod
    # marker (code 21) as the first beat of the epoch — not the first beat
    # after the marker.  To reproduce CARSPAN's beat counts and IBI statistics
    # we therefore replace each epoch start time with the timestamp of the last
    # R-peak that occurred strictly before the original start-marker time.
    #
    # If no R-peak precedes a given start marker (e.g. the fallback single-epoch
    # whose start equals times[0]), the original marker time is kept unchanged.
    adjusted_start_times = []
    for st in start_times:
        preceding = rtop_times[rtop_times < st]
        if preceding.size > 0:
            adjusted = float(preceding[-1])
            logger.debug(
                f"Epoch start adjusted: {st:.3f} s → {adjusted:.3f} s "
                f"(last R-peak before marker, CARSPAN convention)."
            )
            adjusted_start_times.append(adjusted)
        else:
            # No R-peak before this marker; keep the original marker time.
            adjusted_start_times.append(float(st))
    start_times = np.asarray(adjusted_start_times)

    # --------------------------------------------------
    # Register epochs
    # --------------------------------------------------
    # physiodata.epochs.clear()
    raw_times = np.concatenate((start_times, end_times))
    n = len(start_times)
    raw_labels = (
        [f"Start Epoch #{i+1}" for i in range(n)] +
        [f"End Epoch #{i+1}"   for i in range(n)]
    )
    
    physiodata.events["TaskSeries"] = EventSeries(raw_times, raw_labels)

    logger.info(
        f"Loaded {len(raw_times)} epoch(s) "
        f"and {rtop_times.size} RTops"
    )


def loadNFF(physiodata, filename: Path, label: str = "ECG") -> None:
    """
    Load channel data and timestamps from a CARSPAN .nff file
    and attach it to PhysioData as physiodata.ecg.

    Parameters
    ----------
    physiodata : PhysioData
        Target dataset.
    filename : Path
        Path to the NFF file.
    label : str
        Channel label to load (default: 'ECG').
    """

    class TNFF:
        BLOCKSIZE = 512
        MAXCHAN = 128

        def __init__(self):
            self.current_channel = 0
            self.block_size_table = [0] * self.MAXCHAN
            self.sweep_offset = [0] * self.MAXCHAN
            self.num_channels = 0
            self.header = bytearray(512)
            self.channel_header = bytearray(256)
            self.labels = [""] * self.MAXCHAN
            self.file = None

        # ---------------- file handling ----------------

        def open_file(self, filename, mode="rb"):
            self.file = open(filename, mode)

        def close_file(self):
            if self.file:
                self.file.close()

        # ---------------- header parsing ----------------

        def read_nff_header(self):
            try:
                self.file.seek(0)
                self.header = self.file.read(512)
                self.num_channels = self._get_short(self.header, 13)

                for i in range(self.MAXCHAN):
                    self.block_size_table[i] = 0
                    self.sweep_offset[i] = 0

                for chan in range(1, self.num_channels + 1):
                    self._get_channel_header(chan)
                    self.block_size_table[chan] = self._get_block_size()
                    self.sweep_offset[chan] = (
                        self.sweep_offset[chan - 1]
                        + self.block_size_table[chan - 1]
                    )
                    self.labels[chan - 1] = self._get_label()

                self.block_size_table[0] = (
                    self.sweep_offset[self.num_channels]
                    + self.block_size_table[self.num_channels]
                )
                self.current_channel = 0
            except Exception as exc:
                self.close_file()
                raise RuntimeError("Not a valid NFF file") from exc

        # ---------------- low-level access ----------------

        def _get_short(self, data, offset):
            return struct.unpack("<h", data[offset * 2 : offset * 2 + 2])[0]

        def _get_integer(self, data, offset):
            return struct.unpack("<i", data[offset * 4 : offset * 4 + 4])[0]

        def get_interval(self, chan):
            self._get_channel_header(chan)
            return self._get_integer(self.channel_header, 14)

        def get_sample_rate(self):
            return 1_000_000 / self.get_interval(self.current_channel)

        def get_start_time(self):
            return self._get_integer(self.header, 16)

        def _get_channel_header(self, chan):
            if chan != self.current_channel:
                file_pos = 512 + 256 * (chan - 1)
                self.file.seek(file_pos)
                self.channel_header = self.file.read(256)
                self.current_channel = chan

        def _get_block_size(self):
            return self._get_integer(self.channel_header, 16)

        def _get_label(self):
            chars = []
            for i in range(18):
                ch = chr(self.channel_header[120 + i])
                chars.append(ch if 32 <= ord(ch) <= 122 else " ")
            return "".join(chars).strip()

        def _get_nr_samples(self):
            return self._get_integer(self.channel_header, 15)

        # ---------------- data reading ----------------

        def read_channel_data(self, chan):
            chan_block_size = self.BLOCKSIZE
            chan_sweep_offset = (chan - 1) * self.BLOCKSIZE
            n_samples = self._get_nr_samples()

            data = np.empty(n_samples, dtype=np.int16)

            self._init_read_nff()
            j = 0

            while True:
                buf = self._read_nff_sweep()
                if buf is None:
                    break

                for i in range(chan_block_size):
                    if j >= n_samples:
                        break
                    data[j] = buf[chan_sweep_offset + i]
                    j += 1

            return data

        def _init_read_nff(self):
            file_pos = 512 + 256 * self.num_channels
            self.file.seek(file_pos)

        def _read_nff_sweep(self):
            sweep_size = self.BLOCKSIZE * self.num_channels
            buf = self.file.read(sweep_size * 2)
            if len(buf) != sweep_size * 2:
                return None
            return struct.unpack("<" + str(sweep_size) + "h", buf)

    # --------------------------------------------------
    # Load file
    # --------------------------------------------------
    logger.info(f"Loading CARSPAN NFF: {filename.name}")

    nff = TNFF()
    nff.open_file(filename)
    nff.read_nff_header()

    if label not in nff.labels and nff.num_channels != 1:
        raise ValueError(f"Channel '{label}' not found in NFF file.")

    chan = 1 if nff.num_channels == 1 else nff.labels.index(label) + 1
    nff.current_channel = chan

    data = nff.read_channel_data(chan)

    sample_rate = nff.get_sample_rate()
    start_time = nff.get_start_time() / 1000.0

    timestamps = start_time + np.arange(len(data)) / sample_rate

    nff.close_file()

    logger.info(
        f"NFF loaded: channel='{label}', "
        f"samples={len(data)}, fs={sample_rate:.2f} Hz"
    )

    # --------------------------------------------------
    # Attach to PhysioData
    # --------------------------------------------------
    if not hasattr(physiodata, "timeseries") or physiodata.timeseries is None:
        physiodata.timeseries = {}

    physiodata.timeseries["ecg"] = TimeSeries(
        timestamps,
        data.astype(float),
    )
    
    # --------------------------------------------------
    # Normalize to 1-band model (band id = "ecg")
    # --------------------------------------------------
    physiodata.band_map = {"ecg": {"ecg": "ecg"}}
    physiodata.active_band = "ecg"
    physiodata.has_ecg = True
