"""Latency tracking: record every sample's timing, summarise it, report on it.

Plan and definitions: .claude/docs/latency-tracking.md
"""

import logging

from .metrics import HUD_FIELDS, METRICS, Summary, summarize
from .recorder import RAW_DIR, REPORT_DIR, LatencyTracker, load_session

log = logging.getLogger(__name__)

__all__ = [
    "HUD_FIELDS",
    "METRICS",
    "RAW_DIR",
    "REPORT_DIR",
    "LatencyTracker",
    "Summary",
    "load_session",
    "make_tracker",
    "summarize",
]


def make_tracker(config, transport) -> LatencyTracker | None:
    """The tracker for this run, or None when logging is off or the log cannot be opened."""
    if not config.latency_log:
        return None
    try:
        return LatencyTracker(config.transport, transport)
    except OSError as e:
        log.warning("latency log disabled: %s", e)
        return None
