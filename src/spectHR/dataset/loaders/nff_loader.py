# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Loader for the ``.nff`` binary ECG format used by CARSPAN.

``.nff`` files store channel data as little-endian int16 samples in
sweep-interleaved blocks. :class:`TNFF` handles the binary layout;
:func:`load_nff` returns the channels as :class:`~spectHR.session.Samples`
for the loader to fold into a :class:`~spectHR.session.Session`.

NFF files are always paired with a companion ``.evt`` file.
:func:`load_nff` is called directly from :func:`load_evt` when a
matching ``.nff`` exists; it is not a standalone registered loader.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from spectHR.dataset.loaders.registry import register_loader
from spectHR.logger import logger

if TYPE_CHECKING:
    from spectHR.session import Samples, Session


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


def _load_nff_samples(path: Path) -> tuple[dict[str, "Samples"], dict[str, bool]]:
    """Parse a .nff file and return ``(samples_dict, channel_calibrated_dict)``.

    This is the low-level parser called by the EVT loader.  For standalone
    NFF loading use :func:`load_nff_session`.
    """
    from spectHR.session import Samples
    logger.info(f"Loading NFF: {path.name}")

    samples: dict[str, Samples] = {}
    calibrated: dict[str, bool] = {}

    nff = TNFF()
    nff.open_file(path)
    try:
        nff.read_nff_header()
        start_time = nff.get_start_time() / 1000.0

        for chan in range(1, nff.num_channels + 1):
            raw_label = nff.labels[chan - 1]
            key = raw_label.lower().strip() or f"chan{chan}"

            interval = nff.get_interval(chan)
            sample_rate = 1_000_000.0 / interval

            data = nff.read_channel_data(chan)
            timestamps = start_time + np.arange(len(data)) / sample_rate

            values = data.astype(float)
            scale = nff.get_scale_factor(chan) * 1_000_000.0
            zero  = nff.get_zero_level(chan)
            is_calibrated = np.isfinite(scale) and scale != 0.0
            if is_calibrated:
                values = scale * values + zero

            calibrated[key] = is_calibrated
            samples[key] = Samples(timestamps, values, name=key)
            logger.info(
                f"NFF channel loaded: label='{raw_label}' → key='{key}', "
                f"samples={len(data)}, fs={sample_rate:.2f} Hz, "
                f"calibrated={is_calibrated}"
                + (f" (scale={scale:.6g}, zero={zero:.6g})" if is_calibrated else "")
            )
    finally:
        nff.close_file()

    return samples, calibrated


@register_loader(".nff")
def load_nff_session(path: Path, **kwargs) -> "Session":
    """Load a standalone .nff file as a :class:`~spectHR.session.Session`.

    The resulting session has no epochs or events; call
    ``session.with_detected_beats()`` to detect R-peaks.
    """
    from spectHR.dataset.loaders._epochs import build_epochs
    from spectHR.session import Samples, Session
    samples, _calibrated = _load_nff_samples(path)

    # Normalize: shift times so the earliest channel starts at 0
    if samples:
        t_min = min(float(s.times[0]) for s in samples.values() if s.times.size)
        samples = {k: Samples(s.times - t_min, s.values, s.name) for k, s in samples.items()}

    t_start = 0.0
    t_end = max(
        (float(s.times[-1]) for s in samples.values() if s.times.size),
        default=0.0,
    )
    epochs = build_epochs([], [], t_start=t_start, t_end=t_end)
    return Session(name=path.stem, samples=samples, epochs=epochs)
