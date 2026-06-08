"""
Structured logging for ADCMT 7352A GUI
"""

import logging
import sys


def setup_logger(level=logging.INFO):
    logger = logging.getLogger("adcmt7352a")
    logger.setLevel(level)

    if logger.handlers:
        return logger

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def get_logger():
    return logging.getLogger("adcmt7352a")
