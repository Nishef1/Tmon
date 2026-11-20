"""Hands freed memory back to the operating system after a large one-off build.

A build that loads years of bars or all statements leaves the Python heap holding gigabytes it no
longer uses. On the small server that pushes the API over its memory limit and the kernel starts
swapping it, which slows every page. glibc can return the free heap; elsewhere this does nothing.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc
import logging

log = logging.getLogger(__name__)


def release_memory() -> None:
    gc.collect()
    name = ctypes.util.find_library("c")
    if not name:
        return
    try:
        ctypes.CDLL(name).malloc_trim(0)
    except (OSError, AttributeError):
        log.debug("malloc_trim is not available here", exc_info=True)
