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

    # ---------------- calibration ----------------
    #
    # CARSPAN stores a linear calibration (gain + offset) per channel in the
    # 256-byte channel header (``T_Nff.pas`` ``GetScaleFactor`` /
    # ``GetZeroLevel``).  Each value is a ``factor . 10^exponent`` pair stored
    # as two 32-bit ints.  Our ``_get_integer(header, n)`` int offset ``n`` maps
    # to the Pascal ``Int4Channel[n-10]`` (the copy loop is
    # ``for i:=10 to 24 do Int4Channel[i-10] := i4buf[i]``):
    #
    #   ZeroLevel  factor / exponent -> int offsets 10 / 11  (Int4Channel[0/1])
    #   ScaleFactor factor / exponent -> int offsets 12 / 13  (Int4Channel[2/3])
    #
    # The physical conversion CARSPAN applies (``T_EventFile.pas:1350``) is
    # ``physical = ScaleFactor . raw + ZeroLevel`` where the stored scale is
    # additionally multiplied by 1e6 (``ReadDataFileInfo``,
    # ``T_EventFile.pas:761``).

    def get_scale_factor(self, chan: int) -> float:
        """Per-sample gain ``factor . 10^exponent`` from the channel header.

        This is the *raw* NFF scale; the caller multiplies by 1e6 to match
        CARSPAN's ``ChanInfo.ScaleFactor := GetScaleFactor . 1000000``.
        """
        self._get_channel_header(chan)
        factor = self._get_integer(self.channel_header, 12)
        exponent = self._get_integer(self.channel_header, 13)
        return factor * (10.0 ** exponent)

    def get_zero_level(self, chan: int) -> float:
        """Per-sample additive offset ``factor . 10^exponent`` (physical units)."""
        self._get_channel_header(chan)
        factor = self._get_integer(self.channel_header, 10)
        exponent = self._get_integer(self.channel_header, 11)
        return factor * (10.0 ** exponent)

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
    """Read **every** channel from a ``.nff`` file into *physiodata*.

    Each channel is attached as ``physiodata.timeseries[key]``, where
    *key* is the channel label lowercased and stripped (e.g. ``"ecg"``,
    ``"resp"``, ``"bp"``). Time normalisation (subtracting the global
    earliest timestamp) is handled later by
    ``PhysioData._normalize_times_and_build_epochs`` for everything in
    ``timeseries``, so this loader stores absolute NFF timestamps and
    must not shift them itself.

    The band model is wired so ECG and RESP share the single ``"ecg"``
    band: ``band_map["ecg"]["rsp"] = "resp"`` is the hook that lets
    ``PhysioData.__getitem__("rsp")`` resolve to ``timeseries["resp"]``,
    which ``preprocess_ecg`` then feeds to
    ``RespirationSeries.from_timeseries``.

    Parameters
    ----------
    physiodata : PhysioData
    filename : Path
    label : str
        Retained for backwards compatibility with the previous
        single-channel API; no longer used for channel selection since
        all channels are now loaded.
    """
    logger.info(f"Loading NFF: {filename.name}")

    # Records, per timeseries key, whether the channel carried a usable
    # per-channel calibration in its NFF header. Consumed by
    # ``spectUI.preProcessFile.PreProcessFile`` so a manual calibration
    # (workspace ``Calibration.bp_scale`` / ``bp_zero``) is applied only to
    # channels the header left uncalibrated - mirroring CARSPAN's "when not
    # already included in the header" rule (manual sec. 8.1.2 / p. 70).
    physiodata.channel_calibrated = {}

    nff = TNFF()
    nff.open_file(filename)
    try:
        nff.read_nff_header()

        # The recording start time lives in the 512-byte top header and is
        # shared by every channel, so it is read once outside the loop.
        start_time = nff.get_start_time() / 1000.0

        for chan in range(1, nff.num_channels + 1):
            raw_label = nff.labels[chan - 1]
            # Derive the timeseries key from the channel label. Fall back to
            # a positional name when a channel carries no usable label so no
            # channel is silently dropped.
            key = raw_label.lower().strip() or f"chan{chan}"

            # ``get_interval`` loads this channel's 256-byte header (setting
            # ``current_channel``) so the subsequent ``read_channel_data``
            # reads the correct per-channel sample count.
            interval = nff.get_interval(chan)
            sample_rate = 1_000_000.0 / interval

            data = nff.read_channel_data(chan)
            timestamps = start_time + np.arange(len(data)) / sample_rate

            # Apply the per-channel calibration so amplitude channels (BP,
            # respiration, ...) come out in physical units (mmHg, V, ...)
            # rather than raw int16 ADC counts. CARSPAN:
            #   physical = (ScaleFactor x 1e6) x raw + ZeroLevel
            # The 1e6 reproduces ``ChanInfo.ScaleFactor := GetScaleFactor x 1e6``
            # (T_EventFile.pas:761). A zero / non-finite scale means the channel
            # carries no usable calibration (the case for the bundled example
            # recordings, whose header calibration fields are empty); we then
            # leave the raw counts untouched instead of multiplying the signal
            # away to zero. R-peak-derived metrics (IBI/HR) are unaffected
            # either way because they come from event timing, not amplitude.
            values = data.astype(float)
            scale = nff.get_scale_factor(chan) * 1_000_000.0
            zero = nff.get_zero_level(chan)
            calibrated = np.isfinite(scale) and scale != 0.0
            if calibrated:
                values = scale * values + zero

            physiodata.channel_calibrated[key] = calibrated
            physiodata.timeseries[key] = TimeSeries(timestamps, values)
            logger.info(
                f"NFF channel loaded: label='{raw_label}' → key='{key}', "
                f"samples={len(data)}, fs={sample_rate:.2f} Hz, "
                f"calibrated={calibrated}"
                + (f" (scale={scale:.6g}, zero={zero:.6g})" if calibrated else "")
            )
    finally:
        nff.close_file()

    # Wire the single-band model. Only one band exists for NFF (there is no
    # per-device suffix as in the XDF/Polar case), so ECG and RESP are
    # indexed under the same ``"ecg"`` band key. Mirrors the pattern in
    # ``xdf_loader._index_polar_bands``.
    band_streams: dict[str, str] = {}
    if "ecg" in physiodata.timeseries:
        band_streams["ecg"] = "ecg"
    if "resp" in physiodata.timeseries:
        # Key is the band role ``"rsp"``; value is the timeseries key ``"resp"``.
        band_streams["rsp"] = "resp"

    physiodata.band_map = {"ecg": band_streams}
    physiodata.active_band = "ecg"
    physiodata.has_ecg = "ecg" in physiodata.timeseries
