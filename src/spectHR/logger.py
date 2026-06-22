# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later

import logging

logger = logging.getLogger("spectHR")
if not logger.handlers:
    handler = logging.StreamHandler()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    # Bootstrap level used until the GUI applies the workspace's
    # ``Logging.level`` (see MainWindow._apply_log_level). INFO keeps the
    # pre-workspace start-up quiet; the workspace can raise it to DEBUG.
    logger.setLevel(logging.INFO)
