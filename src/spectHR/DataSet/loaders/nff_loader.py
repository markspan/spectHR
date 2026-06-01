# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Loader for the ``.nff`` binary ECG format used by CARSPAN.

``.nff`` files store channel data as little-endian int16 samples in
sweep-interleaved blocks. :class:`TNFF` handles the binary layout;
:func:`load_nff` attaches the ECG channel to a :class:`PhysioData`
instance as a :class:`TimeSeries`.

NFF files are always paired with a companion ``.evt`` file.
:func:`load_nff` is called directly from :func:`load_evt` when a
matching ``.nff`` exists; it is not a standalone registered loader.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.Tools.Logger import logger


class TNFF:
    """Binary reader for a CARSPAN ``.nff`` file.

    Header layout (offsets in 16-bit words / 32-bit ints from the start
    of the 512-byte top header):

    * word 13 - number of channels (int16)
    * int  16 - recording start time, ms (int32)

    Per-channel header (256 bytes per channel, starting at offset 512):

    * int 14 - sample interval, μs (int32)
    * int 15 - number of samples (int32)
    * int 16 - block size in samples (int32)
    * bytes 120..137 - ASCII label (18 chars, space-padded)

    Sample data starts at ``512 + 256·N_channels`` and is stored
    sweep-interleaved: each sweep holds ``BLOCKSIZE`` samples per
    channel (default 512), back-to-back across channels.
    """

    BLOCKSIZE = 512
    MAXCHAN = 128

    def __init__(self) -> None:
        self.current_channel: int = 0
        self.block_size_table = [0] * self.MAXCHAN
        self.sweep_offset = [0] * self.MAXCHAN
        self.num_channels: int = 0
        self.header = bytearray(512)
        self.channel_header = bytearray(256)
        self.labels: list[str] = [""] * self.MAXCHAN
        self.file = None

    # ---------------- file handling ----------------

    def open_file(self, filename, mode: str = "rb") -> None:
        self.file = open(filename, mode)

    def close_file(self) -> None:
        if self.file:
            self.file.close()

    # ---------------- header parsing ----------------

    def read_nff_header(self) -> None:
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

    def _get_short(self, data, offset: int) -> int:
        return struct.unpack("<h", data[offset * 2 : offset * 2 + 2])[0]

    def _get_integer(self, data, offset: int) -> int:
        return struct.unpack("<i", data[offset * 4 : offset * 4 + 4])[0]

    def get_interval(self, chan: int) -> int:
        self._get_channel_header(chan)
        return self._get_integer(self.channel_header, 14)

    def get_sample_rate(self) -> float:
        return 1_000_000 / self.get_interval(self.current_channel)

    def get_start_time(self) -> int:
        return self._get_integer(self.header, 16)

    def _get_channel_header(self, chan: int) -> None:
        if chan != self.current_channel:
            file_pos = 512 + 256 * (chan - 1)
            self.file.seek(file_pos)
            self.channel_header = self.file.read(256)
            self.current_channel = chan

    def _get_block_size(self) -> int:
        return self._get_integer(self.channel_header, 16)

    def _get_label(self) -> str:
        chars = []
        for i in range(18):
            ch = chr(self.channel_header[120 + i])
            chars.append(ch if 32 <= ord(ch) <= 122 else " ")
        return "".join(chars).strip()

    def _get_nr_samples(self) -> int:
        return self._get_integer(self.channel_header, 15)

    # ---------------- data reading ----------------

    def read_channel_data(self, chan: int) -> np.ndarray:
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

    def _init_read_nff(self) -> None:
        file_pos = 512 + 256 * self.num_channels
        self.file.seek(file_pos)

    def _read_nff_sweep(self):
        sweep_size = self.BLOCKSIZE * self.num_channels
        buf = self.file.read(sweep_size * 2)
        if len(buf) != sweep_size * 2:
            return None
        return struct.unpack("<" + str(sweep_size) + "h", buf)


def load_nff(physiodata, filename: Path, label: str = "ECG") -> None:
    """Read the named channel from a ``.nff`` file into *physiodata*.

    Attaches the channel as ``physiodata.timeseries["ecg"]`` and sets
    ``band_map``, ``active_band``, and ``has_ecg``.

    Parameters
    ----------
    physiodata : PhysioData
    filename : Path
    label : str
        Channel label to read (default ``'ECG'``). Ignored when the
        file has exactly one channel.
    """
    logger.info(f"Loading NFF: {filename.name}")

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

    physiodata.timeseries["ecg"] = TimeSeries(
        timestamps,
        data.astype(float),
    )

    # Set up the single-band model.
    physiodata.band_map = {"ecg": {"ecg": "ecg"}}
    physiodata.active_band = "ecg"
    physiodata.has_ecg = True
