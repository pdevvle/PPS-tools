"""Logging setup for PPS-Tools."""

import logging
import sys


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure and return the application logger."""
    logger = logging.getLogger("pps_tools")
    if logger.handlers:
        return logger

    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
